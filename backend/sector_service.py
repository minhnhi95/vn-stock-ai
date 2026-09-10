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
from symbol_utils import is_vn_symbol

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
MAX_SYMBOLS_PER_SECTOR = 3

# Cấp ICB dùng làm "ngành". vnstock trả long-format: mỗi mã có 4 dòng ứng với
# icb_level 1..4. Cấp 2 là mức người dùng nghĩ tới khi nói "ngành"
# (Ngân hàng, Bất động sản, Bán lẻ...); cấp 1 quá rộng ("Tài chính"),
# cấp 3-4 quá vụn. Gộp cả 4 cấp lại như trước sẽ ra heatmap có cả
# "Tài chính" lẫn "Dịch vụ tài chính" — cha và con đứng cạnh nhau.
ICB_SECTOR_LEVEL = 2

# Tổng số ngành tối đa — chỉ tính top N ngành theo số mã (skip ngành nhỏ).
# 8 ngành × 3 mã = 24 calls → vừa khít 20 req/min window (sẽ pause sau 20 calls).
MAX_INDUSTRIES = 8

# % thay đổi của 1 mã chỉ đổi khi có phiên mới; cache dài để lần dựng heatmap sau
# không phải fetch lại mã đã lấy được, dành hạn mức cho mã còn thiếu.
SYMBOL_CHANGE_TTL_SECONDS = 1800.0

# Fallback VN30 — dùng chung market_universe để UI nhất quán.
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


def _is_stock_ticker(symbol: str) -> bool:
    """Mã cổ phiếu niêm yết VN = đúng 3 chữ cái. Loại quỹ/trái phiếu/chứng quyền."""
    return is_vn_symbol(symbol)


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

    # Hai schema đã gặp ở vnstock 4.x:
    #   (a) long-format: symbol, organ_name, com_type_code, icb_level, icb_code, icb_name
    #       -> mỗi mã 4 dòng, phải lọc icb_level.
    #   (b) wide-format: symbol, icb_name1..4, icb_code1..4
    #       -> chọn thẳng cột cấp 2.
    symbol_col = _pick_col(df_sbi, ["symbol", "ticker", "code"])
    if symbol_col is None:
        return None

    level_col = _pick_col(df_sbi, ["icb_level", "level"])
    if level_col is not None:
        # (a) long-format — giữ đúng một cấp ICB.
        name_col = _pick_col(df_sbi, ["icb_name", "industry", "sector"])
        code_col = _pick_col(df_sbi, ["icb_code", "industry_code"])
        if name_col is None:
            return None
        levels = df_sbi[level_col].astype(str).str.strip()
        filtered = df_sbi[levels == str(ICB_SECTOR_LEVEL)]
        if filtered.empty:
            filtered = df_sbi[levels == "1"]  # version nào chỉ có cấp 1 thì dùng tạm
        if filtered.empty:
            return None
        df_sbi = filtered
    else:
        # (b) wide-format — ưu tiên cấp 2, thiếu thì lùi dần.
        name_col = _pick_col(df_sbi, ["icb_name2", "icb_name3", "icb_name1", "industry", "sector"])
        code_col = _pick_col(df_sbi, ["icb_code2", "icb_code3", "icb_code1", "industry_code"])
        if name_col is None:
            return None

    # Gộp theo industry
    buckets: Dict[str, Dict[str, Any]] = {}
    for _, row in df_sbi.iterrows():
        sym = _safe_str(row.get(symbol_col)).upper()
        name = _safe_str(row.get(name_col))
        # Listing trả cả chứng chỉ quỹ ("A+ Fund"), trái phiếu, chứng quyền.
        # Mã cổ phiếu niêm yết VN luôn đúng 3 chữ cái.
        if not _is_stock_ticker(sym):
            continue
        if not name or name.lower() in ("nan", "none", ""):
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

            symbols = [s for s in symbols if is_vn_symbol(s)]
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

    # Cache theo TỪNG mã, không chỉ theo cả heatmap. vnstock free tier chỉ cho
    # 20 req/phút nên mỗi lần dựng heatmap thường có vài mã bị rate-limit; nếu
    # vứt hết kết quả đi thì lần nào cũng chỉ đủ 2-3 ngành. Giữ lại từng mã lấy
    # được để các lần sau lấp dần cho đủ.
    cache_key = f"change:{sym}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    end_dt = datetime.now(VN_TZ).date()
    start_dt = end_dt - timedelta(days=14)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    for source in ("VCI", "KBS"):
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

            payload = {
                "symbol": sym,
                "price": last_vnd,
                "change_pct": change_pct,
                "source": source,
            }
            _cache.set(cache_key, payload, SYMBOL_CHANGE_TTL_SECONDS)
            return payload
        except Exception:
            continue

    return None


def _fetch_changes_batch(symbols: List[str]) -> List[Dict[str, Any]]:
    """
    Pull giá song song bằng ThreadPoolExecutor (I/O bound — pattern giống
    quét song song). Loại bỏ None.
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

    # Chỉ lấy được giá của ~20 mã mỗi phút (vnstock free tier), nên phải chọn
    # mã ĐẠI DIỆN chứ không phải mã đầu tiên theo bảng chữ cái: lấy đầu danh sách
    # sẽ ra AAS/AAV/ABR/ACS — toàn penny, và "Xây dựng -9%" thực chất là một mã
    # micro-cap. Dùng rổ VN100 làm proxy thanh khoản/vốn hoá.
    vn100 = set(get_vn100_symbols())

    ranked = []
    for ind in industries:
        blue_chips = [s for s in ind.get("symbols", []) if s in vn100]
        if not blue_chips:
            # Ngành không có đại diện trong VN100 thì không đủ tiêu biểu để lên heatmap.
            continue
        ranked.append((len(blue_chips), ind, blue_chips))

    if not ranked:
        return {
            "available": False,
            "reason": "Không ngành nào có mã thuộc rổ VN100 để làm đại diện",
            "sectors": [],
        }

    # Xếp hạng theo số mã VN100 trong ngành = mức độ quan trọng với thị trường,
    # thay vì tổng số mã niêm yết (khiến ngành toàn penny xếp trên Ngân hàng).
    ranked.sort(key=lambda item: item[0], reverse=True)
    ranked = ranked[:MAX_INDUSTRIES]
    industries = [ind for _, ind, _ in ranked]

    all_symbols: List[str] = []
    seen: set = set()
    sector_symbols_map: Dict[str, List[str]] = {}
    for _, ind, blue_chips in ranked:
        picked = blue_chips[:MAX_SYMBOLS_PER_SECTOR]
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
            # Con số là trung bình của MẤY mã này thôi, không phải cả ngành —
            # UI cần nói rõ để người dùng không đọc nhầm thành chỉ số ngành.
            "symbols_used": [r["symbol"] for r in rows],
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
        "requested_industries": len(industries),
        "cached": False,
    }
    # Chỉ cache khi kết quả tương đối đầy đủ. Nếu rate limit làm rụng quá nửa số
    # ngành, để lần gọi sau thử lại — mã đã lấy được vẫn nằm trong cache riêng
    # nên lần sau rẻ hơn nhiều.
    if len(sectors_out) >= max(1, len(industries) // 2):
        _cache.set("sector_heatmap", payload, HEATMAP_TTL_SECONDS)
    return payload
