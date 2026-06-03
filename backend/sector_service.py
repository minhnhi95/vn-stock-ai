"""
Heatmap ngành (sector heatmap) cho thị trường chứng khoán Việt Nam.

Chức năng:
- Liệt kê ngành ICB + mã thuộc ngành (Listing.symbols_by_industries / industries_icb)
- Tính % thay đổi trung bình theo ngành dựa trên giá đóng cửa 2 phiên gần nhất
- Lấy danh sách rổ chỉ số VN30 / VN100 (cache 24h, có fallback hardcoded)

Tại sao gom các helper trên cùng module:
- Cùng một mục tiêu UI: hiển thị bức tranh tổng thể thị trường theo ngành / theo rổ.
- Cùng phụ thuộc vnstock Listing + Quote — tiện share TTLCache + ThreadPoolExecutor.

Probe finding quan trọng (Phase 1):
- Listing().industries_icb() FAIL với default source; PHẢI truyền source='VCI'.
- vnstock 4.0.4 KHÔNG có foreign_trade khả dụng — không dùng ở module này.

Convention: defensive try/except quanh mọi vnstock call, trả {available: false, reason}
khi fail. Reason / comment dùng tiếng Việt.
"""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from market_service import TTLCache, VN_TZ

try:
    from vnstock import Listing, Quote
    HAS_VNSTOCK = True
except ImportError:
    HAS_VNSTOCK = False


# ---------- Constants ----------

# Cache TTL: rổ chỉ số / danh sách ngành ít đổi → 24h là hợp lý.
LISTING_TTL_SECONDS = 24 * 3600.0
# Heatmap đổi theo phiên — vnstock free tier 20 req/min nên cache 30 phút để
# không trigger rate limit liên tục. Stale-while-revalidate friendly.
HEATMAP_TTL_SECONDS = 1800.0

# Số worker song song. vnstock free tier 20 req/min → 3 worker là ngưỡng an toàn.
# 8 worker hit limit trong < 1 phút và kill process.
MAX_WORKERS = 3

# Số mã tối đa lấy mỗi ngành — giảm xuống để tổng số call < 20 với 4-6 ngành chính.
MAX_SYMBOLS_PER_SECTOR = 5

# Fallback VN30 — đồng bộ với backtest_service.VN30_SYMBOLS để UI nhất quán.
_FALLBACK_VN30 = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

# Fallback VN100 — bổ sung 70 mã ngoài VN30 (mid-cap thường xuyên có trong rổ).
# Khi vnstock fail, dùng list này để tránh trả empty.
_FALLBACK_VN100_EXTRA = [
    "AAA", "ANV", "APH", "BFC", "BMP", "BSI", "BWE", "CII", "CMG", "CTD",
    "CTR", "CTS", "DBC", "DCM", "DGC", "DGW", "DIG", "DPM", "DXG", "DXS",
    "EIB", "EVF", "FRT", "FTS", "GEX", "GMD", "HAG", "HCM", "HDC", "HDG",
    "HHV", "HSG", "HT1", "IJC", "IMP", "KBC", "KDC", "KDH", "KOS", "LPB",
    "NKG", "NLG", "NT2", "NVL", "OCB", "ORS", "PAN", "PC1", "PDR", "PHR",
    "PNJ", "PPC", "PTB", "PVD", "PVS", "PVT", "REE", "SBT", "SCS", "SIP",
    "SJS", "SZC", "TCH", "TLG", "TV2", "VCG", "VCI", "VGC", "VHC", "VIX",
]

_cache = TTLCache()


# ---------- Helpers ----------

def _safe_str(v) -> str:
    try:
        return str(v).strip() if v is not None else ""
    except Exception:
        return ""


def _pick_col(df, candidates: List[str]) -> Optional[str]:
    """
    Tìm tên cột thực tế khớp 1 trong candidates (case-insensitive).
    vnstock đôi khi đổi tên cột giữa các version → fallback substring.
    """
    if df is None or len(df.columns) == 0:
        return None
    cols_lower = {str(c).lower(): str(c) for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    # Fallback substring
    for cand in candidates:
        c_low = cand.lower()
        for col_lower, col_orig in cols_lower.items():
            if c_low in col_lower:
                return col_orig
    return None


# ---------- Listing: industries & rổ chỉ số ----------

def _fetch_industries_raw() -> Optional[List[Dict[str, Any]]]:
    """
    Lấy mapping symbol ↔ industry (ICB) từ vnstock.

    Probe finding: phải truyền source='VCI' — default source raise NotImplementedError.
    Return list of dicts gộp theo industry: [{name, code, symbols: [...]}]
    """
    if not HAS_VNSTOCK:
        return None

    last_error: Optional[str] = None
    # Thử 2 endpoint: symbols_by_industries (đầy đủ + có mã) ưu tiên trước,
    # rồi mới industries_icb (chỉ có tên ngành, không có mã).
    try:
        listing = Listing(source="VCI")
    except Exception as e:
        last_error = str(e)
        try:
            # Một số version Listing không nhận source ở constructor
            listing = Listing()
        except Exception as e2:
            return None

    df_sbi = None
    for getter_name in ("symbols_by_industries", "industries_icb"):
        try:
            getter = getattr(listing, getter_name, None)
            if getter is None:
                continue
            df_sbi = getter()
            if df_sbi is not None and not df_sbi.empty:
                break
        except Exception as e:
            last_error = f"{getter_name}: {e}"
            continue

    if df_sbi is None or df_sbi.empty:
        return None

    # Cố gắng tìm cột symbol + cột tên ngành. vnstock VCI thực tế có:
    #   symbol, icb_name1..4, icb_code1..4, organ_name, ...
    # Ưu tiên icb_name2 (sector cấp 2) — thường là level người dùng quan tâm
    # (Banking, Real Estate, Steel, ...). Nếu thiếu, fallback icb_name3 / icb_name1.
    symbol_col = _pick_col(df_sbi, ["symbol", "ticker", "code"])
    name_col = _pick_col(df_sbi, ["icb_name2", "icb_name3", "icb_name1", "icb_name", "industry", "sector"])
    code_col = _pick_col(df_sbi, ["icb_code2", "icb_code3", "icb_code1", "icb_code", "industry_code"])

    if symbol_col is None or name_col is None:
        return None

    # Gộp theo industry
    buckets: Dict[str, Dict[str, Any]] = {}
    for _, row in df_sbi.iterrows():
        sym = _safe_str(row.get(symbol_col)).upper()
        name = _safe_str(row.get(name_col))
        if not sym or not name or name.lower() in ("nan", "none", ""):
            continue
        code = _safe_str(row.get(code_col)) if code_col else ""
        key = name
        if key not in buckets:
            buckets[key] = {
                "name": name,
                "code": code,
                "symbols": [],
            }
        if sym not in buckets[key]["symbols"]:
            buckets[key]["symbols"].append(sym)

    if not buckets:
        return None

    # Sort theo số lượng mã (ngành lớn lên trước)
    result = sorted(buckets.values(), key=lambda b: len(b["symbols"]), reverse=True)
    return result


def get_industries() -> List[Dict[str, Any]]:
    """
    Trả về danh sách ngành ICB kèm mã thuộc ngành. Cache 24h.

    Return: [{name, code, count, symbols: [str, ...]}]
    Trả [] khi vnstock fail.
    """
    cached = _cache.get("industries")
    if cached is not None:
        return cached

    raw = _fetch_industries_raw()
    if raw is None:
        return []

    payload = [
        {
            "name": b["name"],
            "code": b["code"],
            "count": len(b["symbols"]),
            "symbols": b["symbols"],
        }
        for b in raw
    ]
    _cache.set("industries", payload, LISTING_TTL_SECONDS)
    return payload


def _fetch_index_constituents(index_name: str) -> Optional[List[str]]:
    """
    Lấy danh sách mã thuộc rổ chỉ số (VN30 / VN100 / HNX30 / VNMID...).
    vnstock Listing có method `symbols_by_group(group)`.
    """
    if not HAS_VNSTOCK:
        return None

    try:
        listing = Listing(source="VCI")
    except Exception:
        try:
            listing = Listing()
        except Exception:
            return None

    for getter_name in ("symbols_by_group", "symbols_by_exchange"):
        try:
            getter = getattr(listing, getter_name, None)
            if getter is None:
                continue
            res = getter(index_name)
            # vnstock có thể trả Series, DataFrame, hoặc list
            if res is None:
                continue
            if hasattr(res, "empty") and res.empty:
                continue
            # Series of strings
            if hasattr(res, "tolist"):
                symbols = [_safe_str(s).upper() for s in res.tolist()]
            elif hasattr(res, "columns"):
                # DataFrame — pick cột symbol
                col = _pick_col(res, ["symbol", "ticker", "code"])
                if col is None:
                    continue
                symbols = [_safe_str(s).upper() for s in res[col].tolist()]
            else:
                symbols = [_safe_str(s).upper() for s in list(res)]

            symbols = [s for s in symbols if s and s.isalpha() and 2 <= len(s) <= 4]
            if symbols:
                return symbols
        except Exception:
            continue

    return None


def get_vn30_symbols() -> List[str]:
    """Danh sách VN30. Cache 24h. Fallback hardcoded nếu vnstock fail."""
    cached = _cache.get("vn30")
    if cached is not None:
        return cached

    symbols = _fetch_index_constituents("VN30") or _FALLBACK_VN30
    # Dedup giữ thứ tự
    seen = set()
    deduped = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    _cache.set("vn30", deduped, LISTING_TTL_SECONDS)
    return deduped


def get_vn100_symbols() -> List[str]:
    """
    Danh sách VN100. Cache 24h. Fallback = VN30 + 70 mã hardcoded khi vnstock fail.
    """
    cached = _cache.get("vn100")
    if cached is not None:
        return cached

    symbols = _fetch_index_constituents("VN100")
    if not symbols:
        # Fallback: union VN30 + extra
        symbols = list(get_vn30_symbols()) + list(_FALLBACK_VN100_EXTRA)

    seen = set()
    deduped = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    _cache.set("vn100", deduped, LISTING_TTL_SECONDS)
    return deduped


# ---------- Heatmap: % change theo ngành ----------

def _fetch_two_session_change(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Lấy giá đóng cửa 2 phiên gần nhất → tính % change.

    Dùng Quote.history với khoảng 10 ngày để chắc chắn lấy được 2 phiên
    (phòng trường hợp có ngày nghỉ lễ).

    Trả None khi fail để gọi `_run_safe` ở trên loại bỏ.
    """
    if not HAS_VNSTOCK:
        return None

    sym = symbol.strip().upper()
    if not sym:
        return None

    end_dt = datetime.now(VN_TZ).date()
    start_dt = end_dt - timedelta(days=14)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    for source in ("VCI", "TCBS", "KBS"):
        try:
            q = Quote(symbol=sym, source=source)
            df = q.history(start=start_str, end=end_str, interval="1D")
            if df is None or df.empty or len(df) < 2:
                continue

            close_col = _pick_col(df, ["close", "Close"])
            if close_col is None:
                continue

            last = float(df[close_col].iloc[-1])
            prev = float(df[close_col].iloc[-2])
            if prev <= 0:
                continue

            change_pct = (last / prev - 1.0) * 100.0
            # vnstock giá theo nghìn (vd 73.7 thay vì 73700) — % không bị ảnh hưởng,
            # nhưng quy đổi để phía caller hiển thị tham khảo cũng nhất quán.
            last_vnd = last * 1000.0 if last < 1000 else last

            return {
                "symbol": sym,
                "price": last_vnd,
                "change_pct": change_pct,
                "source": source,
            }
        except Exception:
            continue

    return None


def _fetch_changes_batch(symbols: List[str]) -> List[Dict[str, Any]]:
    """
    Pull giá song song bằng ThreadPoolExecutor (I/O bound — pattern giống
    backtest_service.run_batch_backtest). Loại bỏ None.
    """
    out: List[Dict[str, Any]] = []
    if not symbols:
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_fetch_two_session_change, s): s for s in symbols}
        for f in concurrent.futures.as_completed(futures):
            try:
                r = f.result()
                if r is not None:
                    out.append(r)
            except Exception:
                continue
    return out


def get_sector_heatmap() -> Dict[str, Any]:
    """
    Tính % thay đổi trung bình theo ngành (avg of constituent stocks).

    Pipeline:
    1. Lấy danh sách ngành ICB (cache 24h).
    2. Với mỗi ngành, lấy giá 2 phiên gần nhất của các mã (limit MAX_SYMBOLS_PER_SECTOR).
    3. Tính avg %, xác định top_gainer / top_loser.

    Cache 5 phút (HEATMAP_TTL_SECONDS) — heatmap không cần realtime.

    Return shape:
    {
      available: bool,
      reason?: str,
      generated_at: str (ISO),
      sectors: [
        {name, code, count, avg_change_pct, top_gainer: {symbol, change_pct}, top_loser: {...}}
      ]
    }
    """
    cached = _cache.get("sector_heatmap")
    if cached is not None:
        return {**cached, "cached": True}

    if not HAS_VNSTOCK:
        return {"available": False, "reason": "vnstock không khả dụng", "sectors": []}

    industries = get_industries()
    if not industries:
        return {
            "available": False,
            "reason": "Không lấy được danh sách ngành ICB từ vnstock",
            "sectors": [],
        }

    # Gom tất cả mã cần fetch thành 1 set để tránh fetch trùng giữa các ngành
    # (1 mã chỉ thuộc 1 ngành ICB cấp 2 trong thực tế, nhưng dữ liệu đôi khi
    # bị duplicate giữa các ngành con — defensive dedup).
    all_symbols: List[str] = []
    seen: set = set()
    sector_symbols_map: Dict[str, List[str]] = {}
    for ind in industries:
        # Giới hạn số mã/ngành để tránh ngành lớn (Real Estate ~50 mã) làm chậm
        picked = ind["symbols"][:MAX_SYMBOLS_PER_SECTOR]
        sector_symbols_map[ind["name"]] = picked
        for s in picked:
            if s not in seen:
                seen.add(s)
                all_symbols.append(s)

    # Fetch song song toàn bộ symbol một lần
    changes = _fetch_changes_batch(all_symbols)
    by_symbol: Dict[str, Dict[str, Any]] = {c["symbol"]: c for c in changes}

    sectors_out: List[Dict[str, Any]] = []
    for ind in industries:
        syms = sector_symbols_map.get(ind["name"], [])
        # Chỉ lấy mã có dữ liệu thành công
        rows = [by_symbol[s] for s in syms if s in by_symbol]
        if not rows:
            # Bỏ qua ngành không có data — tránh nhiễu UI
            continue

        avg = sum(r["change_pct"] for r in rows) / len(rows)
        top_gainer = max(rows, key=lambda r: r["change_pct"])
        top_loser = min(rows, key=lambda r: r["change_pct"])

        sectors_out.append({
            "name": ind["name"],
            "code": ind["code"],
            "count": len(rows),
            "total_symbols": len(syms),
            "avg_change_pct": round(avg, 3),
            "top_gainer": {
                "symbol": top_gainer["symbol"],
                "change_pct": round(top_gainer["change_pct"], 3),
            },
            "top_loser": {
                "symbol": top_loser["symbol"],
                "change_pct": round(top_loser["change_pct"], 3),
            },
        })

    if not sectors_out:
        return {
            "available": False,
            "reason": "Không lấy được giá cho bất kỳ mã nào trong các ngành",
            "sectors": [],
        }

    # Sort theo avg desc — ngành tăng mạnh nhất lên trước (UI mặc định)
    sectors_out.sort(key=lambda s: s["avg_change_pct"], reverse=True)

    payload: Dict[str, Any] = {
        "available": True,
        "generated_at": datetime.now(VN_TZ).isoformat(),
        "sectors": sectors_out,
        "cached": False,
    }
    _cache.set("sector_heatmap", payload, HEATMAP_TTL_SECONDS)
    return payload
