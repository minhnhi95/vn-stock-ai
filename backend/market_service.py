"""
Helpers cho thị trường chứng khoán Việt Nam:
- Trạng thái phiên giao dịch (giờ mở/đóng cửa, nghỉ trưa, cuối tuần)
- Cache TTL đơn giản trong process
- Fetch giá thời gian thực và dữ liệu cơ bản (fundamentals) qua vnstock

Tất cả thời gian dùng giờ Việt Nam (UTC+7).
"""
from __future__ import annotations

import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional, Tuple

try:
    from vnstock import Quote, Finance
    HAS_VNSTOCK = True
except ImportError:
    HAS_VNSTOCK = False

VN_TZ = timezone(timedelta(hours=7))


# ---------- Phiên giao dịch ----------

def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def market_status(when: Optional[datetime] = None) -> Dict[str, Any]:
    """Trả về trạng thái phiên: OPEN / LUNCH / CLOSED + lý do."""
    dt = when or now_vn()
    weekday = dt.weekday()  # 0 = Mon, 6 = Sun
    if weekday >= 5:
        return {"status": "CLOSED", "reason": "Cuối tuần", "is_open": False}

    t = dt.time()
    morning_open = (9, 0)
    morning_close = (11, 30)
    afternoon_open = (13, 0)
    afternoon_close = (15, 0)

    def hm(h, m):
        return h * 60 + m

    cur = hm(t.hour, t.minute)
    if cur < hm(*morning_open):
        return {"status": "CLOSED", "reason": "Chưa mở cửa", "is_open": False}
    if hm(*morning_open) <= cur < hm(*morning_close):
        return {"status": "OPEN", "reason": "Phiên sáng", "is_open": True}
    if hm(*morning_close) <= cur < hm(*afternoon_open):
        return {"status": "LUNCH", "reason": "Nghỉ trưa", "is_open": False}
    if hm(*afternoon_open) <= cur < hm(*afternoon_close):
        return {"status": "OPEN", "reason": "Phiên chiều", "is_open": True}
    return {"status": "CLOSED", "reason": "Đã đóng cửa", "is_open": False}


# ---------- Cache TTL trong-process (thread-safe) ----------

class TTLCache:
    def __init__(self):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if time.time() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)

    def get_or_set(self, key: str, ttl_seconds: float, producer: Callable[[], Any]) -> Any:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = producer()
        if value is not None:
            self.set(key, value, ttl_seconds)
        return value


_cache = TTLCache()


# ---------- Realtime price ----------

REALTIME_TTL_SECONDS = 5.0
LAST_CLOSE_TTL_SECONDS = 300.0  # giá đóng cửa không đổi trong phiên nghỉ -> cache lâu hơn
FUNDAMENTALS_TTL_SECONDS = 3600.0  # 1 giờ


def fetch_realtime_price(symbol: str) -> Dict[str, Any]:
    """
    Lấy giá khớp gần nhất từ vnstock intraday. Cache 5s để giảm tải khi nhiều client poll.
    Trả về: { price, time, volume, source, market }
    """
    symbol = symbol.strip().upper()
    cache_key = f"realtime:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    if not HAS_VNSTOCK:
        return {"price": None, "error": "vnstock không khả dụng", "cached": False}

    last_error = None
    for source in ("VCI", "KBS"):
        try:
            q = Quote(symbol=symbol, source=source)
            df = q.intraday(page_size=1)
            if df is None or df.empty:
                continue
            row = df.iloc[0]
            price_raw = float(row["price"])
            # vnstock thường trả giá theo đơn vị nghìn (73.7 thay vì 73700)
            price_vnd = price_raw * 1000.0 if price_raw < 1000 else price_raw
            payload = {
                "symbol": symbol,
                "price": price_vnd,
                "time": str(row.get("time", "")),
                "volume": int(row.get("volume", 0) or 0),
                "match_type": str(row.get("match_type", "")).lower() or None,
                "source": source,
                "is_intraday": True,
                "cached": False,
            }
            _cache.set(cache_key, payload, REALTIME_TTL_SECONDS)
            return payload
        except Exception as e:
            last_error = str(e)
            continue

    # Ngoài giờ khớp lệnh (và với mã ít thanh khoản) intraday thường rỗng.
    # Rơi về giá đóng cửa phiên gần nhất để UI vẫn có số hiển thị.
    fallback = _fetch_last_close(symbol)
    if fallback is not None:
        _cache.set(cache_key, fallback, LAST_CLOSE_TTL_SECONDS)
        return fallback

    return {"symbol": symbol, "price": None, "error": last_error or "Không có dữ liệu", "cached": False}


def _fetch_last_close(symbol: str) -> Optional[Dict[str, Any]]:
    """Giá đóng cửa phiên gần nhất từ dữ liệu ngày. is_intraday=False để UI ghi rõ."""
    start = (now_vn() - timedelta(days=14)).strftime("%Y-%m-%d")
    end = now_vn().strftime("%Y-%m-%d")
    for source in ("VCI", "KBS"):
        try:
            df = Quote(symbol=symbol, source=source).history(start=start, end=end, interval="1D")
            if df is None or df.empty:
                continue
            row = df.iloc[-1]
            close_raw = _safe_float(row.get("close"))
            if close_raw is None:
                continue
            return {
                "symbol": symbol,
                "price": close_raw * 1000.0 if close_raw < 1000 else close_raw,
                "time": str(row.get("time", "")),
                "volume": int(row.get("volume", 0) or 0),
                "match_type": None,
                "source": f"{source}/daily-close",
                "is_intraday": False,
                "cached": False,
            }
        except Exception:
            continue
    return None


# ---------- Fundamentals ----------

def _safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


# Đơn vị hiển thị chuẩn của payload fundamentals:
#   pe, pb, debt_to_equity, beta  -> lần (ratio)
#   roe, roa, *_margin, *_growth, dividend_yield -> phần trăm (đã nhân 100)
#   eps, bvps -> VND/cổ phiếu
#
# Mỗi source trả đơn vị khác nhau nên map kèm hệ số quy đổi:
#   ("item_id ứng viên", hệ_số)
# KBS đã trả sẵn %; VCI trả proportion (0.187 = 18.7%).
_RATIO_MAPS: Dict[str, Dict[str, Tuple[Tuple[str, ...], float]]] = {
    "KBS": {
        "pe": (("pe_ratio",), 1.0),
        "pb": (("pb_ratio",), 1.0),
        "roe": (("roe_trailling", "roe"), 1.0),
        "roa": (("roa_trailling", "roa"), 1.0),
        "eps": (("trailing_eps",), 1.0),
        "bvps": (("book_value_per_share_bvps",), 1.0),
        "beta": (("beta",), 1.0),
        "revenue_growth": (("net_revenue",), 1.0),
        "earnings_growth": (
            ("profit_after_tax_for_shareholders_of_the_parent_company", "profit_before_tax"),
            1.0,
        ),
        # KBS "Nợ vay trên Vốn chủ sở hữu" trả %, quy về lần cho khớp quy ước P/E.
        "debt_to_equity": (("debt_to_equity",), 0.01),
        "dividend_yield": (("dividend_yield",), 100.0),
        "net_margin": (("net_margin",), 1.0),
        "gross_margin": (("gross_margin",), 1.0),
    },
    "VCI": {
        "pe": (("pe_ratio",), 1.0),
        "pb": (("pb_ratio",), 1.0),
        "roe": (("roe",), 100.0),
        "roa": (("roa",), 100.0),
        "eps": ((), 1.0),  # VCI ratio() không expose EPS
        "bvps": ((), 1.0),
        "beta": ((), 1.0),
        "revenue_growth": ((), 1.0),
        "earnings_growth": ((), 1.0),
        "debt_to_equity": (("debt_to_equity", "debtPerEquity"), 1.0),
        "dividend_yield": (("dividend_yield",), 100.0),
        "net_margin": (("net_margin",), 100.0),
        "gross_margin": (("gross_margin",), 100.0),
    },
}

# Thứ tự thử source. KBS trả kỳ gần nhất (vd 2026-Q2); VCI ở vnstock free tier
# hiện đứng ở 2018 nên chỉ dùng làm phương án dự phòng.
_FUNDAMENTALS_SOURCES = ("KBS", "VCI")


def _parse_period(label: Optional[str]) -> Optional[Tuple[int, int]]:
    """
    'YYYY-Qn' -> (YYYY, n); 'YYYY' -> (YYYY, 4). Trả None nếu không parse được.
    Hậu tố lạ do trùng tên cột ('2025-Q4_1') được bỏ qua.
    """
    if not label:
        return None
    s = str(label).strip()
    if len(s) < 4 or not s[:4].isdigit():
        return None
    year = int(s[:4])
    quarter = 4
    marker = s.find("Q", 4)
    if marker != -1 and marker + 1 < len(s) and s[marker + 1].isdigit():
        quarter = int(s[marker + 1])
    return (year, quarter)


def _latest_period_column(columns) -> Optional[str]:
    """
    Tìm cột giai đoạn mới nhất trong dataframe ratio của vnstock.
    Columns format: 'YYYY-Qn' (vd '2026-Q1') hoặc 'YYYY'.
    """
    dated = [(_parse_period(c), str(c)) for c in columns]
    dated = [(key, name) for key, name in dated if key is not None]
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return dated[0][1]


def _row_value(df, item_id_candidates, latest_col):
    """
    Tìm hàng có item_id khớp 1 trong candidates, trả về giá trị cột latest_col.

    Cột trong df có thể trùng tên (vnstock lặp label giữa các kỳ) nên chọn theo
    vị trí cột đầu tiên khớp, tránh việc df[col] trả về DataFrame thay vì Series.
    """
    if "item_id" not in df.columns or latest_col is None or not item_id_candidates:
        return None
    try:
        col_pos = list(df.columns).index(latest_col)
    except ValueError:
        return None

    item_ids = df["item_id"].astype(str).str.lower()
    for cand in item_id_candidates:
        mask = item_ids == cand.lower()
        if mask.any():
            return _safe_float(df.iloc[mask.values.argmax(), col_pos])
    # Fallback: substring contains — chỉ với candidate đủ dài để không khớp nhầm.
    for cand in item_id_candidates:
        if len(cand) < 4:
            continue
        mask = item_ids.str.contains(cand.lower(), na=False, regex=False)
        if mask.any():
            return _safe_float(df.iloc[mask.values.argmax(), col_pos])
    return None


def _fetch_fundamentals_from_source(symbol: str, source: str) -> Optional[Dict[str, Any]]:
    """
    Đọc ratio() của 1 source và quy đổi về schema chuẩn. None nếu source không dùng được.
    """
    field_map = _RATIO_MAPS.get(source)
    if field_map is None:
        return None

    fin = Finance(symbol=symbol, source=source)
    ratios = None
    for kwargs in ({"period": "quarter"}, {"period": "year"}, {}):
        try:
            ratios = fin.ratio(**kwargs) if hasattr(fin, "ratio") else None
            if ratios is not None and not ratios.empty:
                break
        except Exception:
            continue

    if ratios is None or ratios.empty:
        return None

    latest_col = _latest_period_column(ratios.columns)
    if latest_col is None:
        return None

    built: Dict[str, Any] = {}
    for field, (candidates, scale) in field_map.items():
        raw = _row_value(ratios, candidates, latest_col)
        built[field] = raw * scale if raw is not None else None

    if all(v is None for v in built.values()):
        return None

    period = _parse_period(latest_col)
    return {
        "symbol": symbol,
        "available": True,
        "source": source,
        "period": str(latest_col).split("_")[0],
        "period_key": period,
        **built,
    }


def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    """
    Lấy chỉ số tài chính cơ bản (P/E, P/B, ROE, EPS, tăng trưởng) qua vnstock.

    Schema vnstock Finance.ratio(): hàng = chỉ số (cột 'item_id'), cột = kỳ ('YYYY-Qn').
    Thử lần lượt các source, trả về kết quả có kỳ MỚI NHẤT — quan trọng vì VCI
    trên free tier vẫn đang trả số liệu 2018, dùng nhầm sẽ hiển thị P/E cũ 8 năm.
    Cache 1 giờ.
    """
    symbol = symbol.strip().upper()
    cache_key = f"fundamentals:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    if not HAS_VNSTOCK:
        return {"symbol": symbol, "available": False, "reason": "vnstock không khả dụng"}

    best: Optional[Dict[str, Any]] = None
    last_error = None
    current_year = now_vn().year

    for source in _FUNDAMENTALS_SOURCES:
        try:
            result = _fetch_fundamentals_from_source(symbol, source)
        except Exception as e:
            last_error = str(e)
            continue
        if result is None:
            continue
        if best is None or (result.get("period_key") or (0, 0)) > (best.get("period_key") or (0, 0)):
            best = result
        # Kỳ gần đây thì dừng luôn, khỏi tốn thêm request (vnstock free tier 20 req/phút).
        year = (result.get("period_key") or (0, 0))[0]
        if year >= current_year - 1:
            break

    if best is None:
        return {
            "symbol": symbol,
            "available": False,
            "reason": last_error or "Không lấy được dữ liệu cơ bản",
        }

    year = (best.pop("period_key", None) or (0, 0))[0]
    if year and year < current_year - 1:
        best["stale"] = True
        best["stale_note"] = f"Nguồn {best['source']} chỉ có số liệu đến {best['period']}."
    best["cached"] = False
    _cache.set(cache_key, best, FUNDAMENTALS_TTL_SECONDS)
    return best


def format_fundamentals_for_prompt(f: Dict[str, Any]) -> str:
    if not f.get("available"):
        return f"Dữ liệu cơ bản: Không khả dụng ({f.get('reason', '')})."

    def fmt(v, suffix="", prec=2):
        if v is None:
            return "N/A"
        return f"{v:,.{prec}f}{suffix}"

    lines = [
        f"Chỉ số cơ bản (kỳ {f.get('period', 'gần nhất')}, nguồn {f.get('source', '?')}):",
        f"- P/E: {fmt(f.get('pe'))}",
        f"- P/B: {fmt(f.get('pb'))}",
        f"- ROE: {fmt(f.get('roe'), '%')}",
        f"- ROA: {fmt(f.get('roa'), '%')}",
        f"- EPS (4 quý gần nhất): {fmt(f.get('eps'), ' VND', 0)}",
        f"- Giá trị sổ sách/cp: {fmt(f.get('bvps'), ' VND', 0)}",
        f"- Biên lợi nhuận gộp: {fmt(f.get('gross_margin'), '%')}",
        f"- Biên lợi nhuận ròng: {fmt(f.get('net_margin'), '%')}",
        f"- Tăng trưởng doanh thu: {fmt(f.get('revenue_growth'), '%')}",
        f"- Tăng trưởng LNST: {fmt(f.get('earnings_growth'), '%')}",
        f"- Nợ vay/Vốn chủ: {fmt(f.get('debt_to_equity'))}",
        f"- Cổ tức (yield): {fmt(f.get('dividend_yield'), '%')}",
        f"- Beta: {fmt(f.get('beta'))}",
    ]
    if f.get("stale"):
        lines.append(
            f"- LƯU Ý: {f.get('stale_note', 'Số liệu cơ bản đã cũ')} — "
            "không dùng các chỉ số này để kết luận định giá hiện tại."
        )
    return "\n".join(lines) + "\n"
