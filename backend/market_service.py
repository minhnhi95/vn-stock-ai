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
    for source in ("VCI", "TCBS", "KBS"):
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
                "cached": False,
            }
            _cache.set(cache_key, payload, REALTIME_TTL_SECONDS)
            return payload
        except Exception as e:
            last_error = str(e)
            continue

    return {"symbol": symbol, "price": None, "error": last_error or "Không có dữ liệu", "cached": False}


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


def _latest_period_column(columns) -> Optional[str]:
    """
    Tìm cột giai đoạn mới nhất trong dataframe ratio của vnstock.
    Columns format: 'YYYY-Qn' (vd '2026-Q1') hoặc 'YYYY'.
    """
    period_cols = []
    for c in columns:
        s = str(c)
        # Match 'YYYY-Q1..4' hoặc 'YYYY'
        if len(s) >= 4 and s[:4].isdigit():
            period_cols.append(s)
    if not period_cols:
        return None
    # Sort lexicographically — 'YYYY-Qn' và 'YYYY' đều sort đúng theo thời gian
    period_cols.sort(reverse=True)
    return period_cols[0]


def _row_value(df, item_id_candidates, latest_col):
    """
    Tìm hàng có item_id khớp 1 trong candidates, trả về giá trị cột latest_col.
    vnstock dùng item_id thường viết camelCase hoặc snake_case khác nhau giữa
    các source và version.
    """
    if "item_id" not in df.columns or latest_col is None:
        return None
    item_ids = df["item_id"].astype(str).str.lower()
    for cand in item_id_candidates:
        mask = item_ids == cand.lower()
        if mask.any():
            return _safe_float(df.loc[mask, latest_col].iloc[0])
    # Fallback: substring contains
    for cand in item_id_candidates:
        mask = item_ids.str.contains(cand.lower(), na=False)
        if mask.any():
            return _safe_float(df.loc[mask, latest_col].iloc[0])
    return None


def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    """
    Lấy chỉ số tài chính cơ bản (P/E, P/B, ROE, EPS, tăng trưởng) qua vnstock.

    Schema vnstock VCI Finance.ratio(): hàng = chỉ số, cột = quý ('YYYY-Q1').
    Cache 1 giờ. Defensive với 2 source (VCI / TCBS) và 3 period (quarter/year/no-arg).
    """
    symbol = symbol.strip().upper()
    cache_key = f"fundamentals:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    if not HAS_VNSTOCK:
        return {"symbol": symbol, "available": False, "reason": "vnstock không khả dụng"}

    payload: Dict[str, Any] = {"symbol": symbol, "available": False}
    last_error = None

    for source in ("VCI", "TCBS"):
        try:
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
                continue

            latest_col = _latest_period_column(ratios.columns)
            if latest_col is None:
                last_error = f"Không tìm thấy cột giai đoạn trong {list(ratios.columns)[:5]}"
                continue

            # item_id candidates dựa trên vnstock VCI thực tế. Đặt strict trước (exact match),
            # fallback substring trong _row_value.
            # item_id thực tế trong vnstock 4.x VCI: pe_ratio, pb_ratio, roe, roa,
            # debt_to_equity, dividend_yield, gross_margin, net_margin, ...
            # KBS có thể khác — substring fallback trong _row_value.
            raw = {
                "pe": _row_value(ratios, ["pe_ratio", "pe"], latest_col),
                "pb": _row_value(ratios, ["pb_ratio", "pb"], latest_col),
                "roe": _row_value(ratios, ["roe"], latest_col),
                "roa": _row_value(ratios, ["roa"], latest_col),
                "eps": _row_value(ratios, ["eps", "basic_eps"], latest_col),
                "revenue_growth": _row_value(ratios, ["revenue_yoy", "revenue_growth"], latest_col),
                "earnings_growth": _row_value(ratios, ["profit_yoy", "earnings_growth", "post_tax_profit_growth", "net_profit_yoy"], latest_col),
                "debt_to_equity": _row_value(ratios, ["debt_to_equity", "debtperequity", "de"], latest_col),
                "dividend_yield": _row_value(ratios, ["dividend_yield"], latest_col),
                "net_margin": _row_value(ratios, ["net_margin"], latest_col),
                "gross_margin": _row_value(ratios, ["gross_margin"], latest_col),
            }

            # vnstock trả tỷ lệ dạng proportion (0.187 = 18.7%). Quy đổi sang %
            # để UI và prompt AI dùng đơn vị nhất quán. P/E và P/B vẫn giữ nguyên.
            def _pct(v):
                return v * 100 if isinstance(v, (int, float)) else None

            built = {
                **raw,
                "roe": _pct(raw["roe"]),
                "roa": _pct(raw["roa"]),
                "revenue_growth": _pct(raw["revenue_growth"]),
                "earnings_growth": _pct(raw["earnings_growth"]),
                "dividend_yield": _pct(raw["dividend_yield"]),
                "net_margin": _pct(raw["net_margin"]),
                "gross_margin": _pct(raw["gross_margin"]),
            }

            if all(v is None for v in built.values()):
                # Schema khác hoàn toàn — thử source khác
                last_error = f"Không pick được chỉ số nào từ source={source}, latest_col={latest_col}"
                continue

            payload = {
                "symbol": symbol,
                "available": True,
                "source": source,
                "period": latest_col,
                **built,
                "cached": False,
            }
            _cache.set(cache_key, payload, FUNDAMENTALS_TTL_SECONDS)
            return payload
        except Exception as e:
            last_error = str(e)
            continue

    payload["reason"] = last_error or "Không lấy được dữ liệu cơ bản"
    return payload


def format_fundamentals_for_prompt(f: Dict[str, Any]) -> str:
    if not f.get("available"):
        return f"Dữ liệu cơ bản: Không khả dụng ({f.get('reason', '')})."

    def fmt(v, suffix=""):
        if v is None:
            return "N/A"
        return f"{v:.2f}{suffix}"

    return (
        "Chỉ số cơ bản (gần nhất):\n"
        f"- P/E: {fmt(f.get('pe'))}\n"
        f"- P/B: {fmt(f.get('pb'))}\n"
        f"- ROE: {fmt(f.get('roe'), '%') }\n"
        f"- ROA: {fmt(f.get('roa'), '%') }\n"
        f"- EPS: {fmt(f.get('eps'))}\n"
        f"- Tăng trưởng doanh thu: {fmt(f.get('revenue_growth'), '%')}\n"
        f"- Tăng trưởng LNST: {fmt(f.get('earnings_growth'), '%')}\n"
        f"- Nợ/Vốn chủ: {fmt(f.get('debt_to_equity'))}\n"
        f"- Cổ tức (yield): {fmt(f.get('dividend_yield'), '%')}\n"
    )
