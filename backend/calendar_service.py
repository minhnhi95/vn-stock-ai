"""
Lịch sự kiện doanh nghiệp Việt Nam (cổ tức, BCTC, ĐHCĐ, ngày GDKHQ).

Nguồn dữ liệu: vnstock 4.0.4 — Company(symbol, source='VCI').events()

CRITICAL FINDING (Phase 1 probe):
    vnstock 4.0.4 KHÔNG expose riêng .dividends() / .insider_deals() trên Company.
    Tất cả 3 loại sự kiện (dividends, insider_deals, earnings/AGM events) được
    UNIFIED qua MỘT call duy nhất: Company(symbol, source='VCI').events().
    Schema events() trả DataFrame có các cột:
        - event_name (tên sự kiện, tiếng Việt) ví dụ "Trả cổ tức bằng tiền mặt"
        - event_code (mã loại sự kiện)
        - public_date / issue_date / notify_date (ngày công bố / phát hành)
        - exer_date / exec_date / exercise_date (ngày GDKHQ — ex-dividend)
        - record_date (ngày chốt danh sách)
        - payment_date (ngày thanh toán cổ tức)
        - value / rate / dividend_ratio / cash_dividend (tỷ lệ / giá trị cổ tức)
        - currency (mặc định VND nếu không có)
    Schema có thể thay đổi giữa các source (VCI / TCBS) — dùng substring fallback.

Conventions:
- Defensive try/except quanh mọi vnstock call
- Cache TTL 6 giờ (sự kiện ít đổi)
- Trả {available: false, reason: "..."} khi fail
- ThreadPoolExecutor cho batch nhiều symbol
- Type hints + comment tiếng Việt
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from market_service import TTLCache, now_vn, VN_TZ

try:
    from vnstock import Company
    HAS_COMPANY = True
except ImportError:
    HAS_COMPANY = False


# ---------- Cache + constants ----------

_cache = TTLCache()

# TTL 6 giờ: sự kiện doanh nghiệp công bố trước nhiều ngày, không cần refresh thường xuyên.
CALENDAR_TTL_SECONDS = 6 * 3600.0

# Cap số worker để không bị HOSE/VCI rate-limit khi user query nhiều mã.
_MAX_WORKERS = 6

# Từ khóa nhận diện loại sự kiện (event_name / event_code tiếng Việt + EN).
# Substring matching, case-insensitive.
_DIVIDEND_KEYWORDS = (
    "cổ tức", "co tuc", "dividend", "div", "chia thưởng",
    "chia thuong", "phát hành thêm", "phat hanh them",
)
_EARNINGS_KEYWORDS = (
    "báo cáo tài chính", "bao cao tai chinh", "bctc", "earnings",
    "kết quả kinh doanh", "ket qua kinh doanh", "công bố lnst",
    "cong bo lnst", "quarterly report", "annual report",
)
_AGM_KEYWORDS = (
    "đại hội", "dai hoi", "đhcđ", "dhcd", "agm", "egm",
    "đại hội cổ đông", "dai hoi co dong", "shareholder meeting",
)


# ---------- Helpers parse DataFrame ----------

def _safe_str(v) -> str:
    try:
        if v is None:
            return ""
        s = str(v).strip()
        # pandas NaN / NaT đều stringify thành "nan" / "NaT"
        if s.lower() in ("nan", "nat", "none"):
            return ""
        return s
    except Exception:
        return ""


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _pick_col(df_cols_lower: Dict[str, str], *candidates: str) -> Optional[str]:
    """
    Tìm cột thực tế trong dataframe dựa trên list ứng viên (case-insensitive).
    Ưu tiên exact match, fallback substring.
    df_cols_lower: dict {lowercase_name: original_name}.
    """
    # Exact match (lowercase)
    for cand in candidates:
        c = cand.lower()
        if c in df_cols_lower:
            return df_cols_lower[c]
    # Substring fallback — chọn cột đầu tiên chứa keyword
    for cand in candidates:
        c = cand.lower()
        for low, orig in df_cols_lower.items():
            if c in low:
                return orig
    return None


def _parse_date(value) -> Optional[datetime]:
    """
    Parse date từ vnstock — có thể là pd.Timestamp, datetime, hoặc string ISO.
    Trả datetime aware (VN timezone) hoặc None.
    """
    if value is None:
        return None
    # pandas Timestamp / datetime
    if hasattr(value, "to_pydatetime"):
        try:
            dt = value.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            return dt
        except Exception:
            pass
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=VN_TZ)

    s = _safe_str(value)
    if not s:
        return None
    # Thử các format phổ biến: '2026-06-15', '2026-06-15 00:00:00', '15/06/2026'
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s[:19] if len(s) >= 19 else s, fmt)
            return dt.replace(tzinfo=VN_TZ)
        except ValueError:
            continue
    # Last resort: fromisoformat
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        return dt
    except ValueError:
        return None


def _classify_event(event_name: str, event_code: str = "") -> str:
    """
    Phân loại sự kiện thành: 'dividend' / 'earnings' / 'agm' / 'other'.
    Dựa vào substring keyword trong event_name + event_code.
    """
    haystack = f"{event_name} {event_code}".lower()
    for kw in _DIVIDEND_KEYWORDS:
        if kw in haystack:
            return "dividend"
    for kw in _EARNINGS_KEYWORDS:
        if kw in haystack:
            return "earnings"
    for kw in _AGM_KEYWORDS:
        if kw in haystack:
            return "agm"
    return "other"


# ---------- Core fetch (1 symbol) ----------

def _fetch_events_raw(symbol: str) -> Dict[str, Any]:
    """
    Gọi vnstock Company.events() cho 1 mã, trả về list events đã normalize.
    Cache 6 giờ per symbol.

    Returns:
        {available: bool, symbol, events: List[Dict], reason?: str, source?: str}
    """
    symbol = symbol.strip().upper()
    cache_key = f"events:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    if not HAS_COMPANY:
        return {"available": False, "symbol": symbol, "events": [], "reason": "vnstock không khả dụng"}

    last_error: Optional[str] = None
    for source in ("VCI", "TCBS"):
        try:
            company = Company(symbol=symbol, source=source)
            if not hasattr(company, "events"):
                last_error = f"Company({source}) không có method events()"
                continue
            df = company.events()
            if df is None or df.empty:
                last_error = f"events() rỗng ở source={source}"
                continue

            # Build lowercase column index để pick cột linh hoạt
            cols_lower = {str(c).lower(): str(c) for c in df.columns}

            name_col = _pick_col(cols_lower, "event_name", "event_title", "title", "ten_su_kien")
            code_col = _pick_col(cols_lower, "event_code", "code", "ma_su_kien")
            exec_col = _pick_col(
                cols_lower,
                "exer_date", "exec_date", "exercise_date", "ex_date",
                "ex_dividend_date", "ngay_gdkhq",
            )
            record_col = _pick_col(cols_lower, "record_date", "ngay_chot_ds", "ngay_chot_danh_sach")
            payment_col = _pick_col(
                cols_lower,
                "payment_date", "pay_date", "ngay_thanh_toan", "ngay_tra_co_tuc",
            )
            public_col = _pick_col(
                cols_lower,
                "public_date", "issue_date", "notify_date", "publish_date", "ngay_cong_bo",
            )
            rate_col = _pick_col(
                cols_lower,
                "rate", "dividend_ratio", "cash_dividend", "value", "amount",
                "ty_le", "gia_tri",
            )
            currency_col = _pick_col(cols_lower, "currency", "don_vi", "unit")
            desc_col = _pick_col(cols_lower, "description", "note", "mo_ta", "ghi_chu", "content")

            if name_col is None and code_col is None:
                last_error = f"Schema events() không có cột tên/mã ở source={source}, cols={list(df.columns)[:5]}"
                continue

            events: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                event_name = _safe_str(row.get(name_col)) if name_col else ""
                event_code = _safe_str(row.get(code_col)) if code_col else ""
                if not event_name and not event_code:
                    continue

                exec_dt = _parse_date(row.get(exec_col)) if exec_col else None
                record_dt = _parse_date(row.get(record_col)) if record_col else None
                payment_dt = _parse_date(row.get(payment_col)) if payment_col else None
                public_dt = _parse_date(row.get(public_col)) if public_col else None

                rate_val = _safe_float(row.get(rate_col)) if rate_col else None
                currency = _safe_str(row.get(currency_col)) if currency_col else ""
                desc = _safe_str(row.get(desc_col)) if desc_col else ""

                event_type = _classify_event(event_name, event_code)

                events.append({
                    "symbol": symbol,
                    "type": event_type,
                    "event_name": event_name,
                    "event_code": event_code,
                    "exec_date": exec_dt.isoformat() if exec_dt else None,
                    "record_date": record_dt.isoformat() if record_dt else None,
                    "payment_date": payment_dt.isoformat() if payment_dt else None,
                    "public_date": public_dt.isoformat() if public_dt else None,
                    "rate": rate_val,
                    "currency": currency or ("VND" if event_type == "dividend" else ""),
                    "description": desc,
                    "source": source,
                })

            if not events:
                last_error = f"Parse events thành công nhưng không có row hợp lệ ở source={source}"
                continue

            payload = {
                "available": True,
                "symbol": symbol,
                "source": source,
                "events": events,
                "fetched_at": now_vn().isoformat(),
                "cached": False,
            }
            _cache.set(cache_key, payload, CALENDAR_TTL_SECONDS)
            return payload
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue

    return {
        "available": False,
        "symbol": symbol,
        "events": [],
        "reason": last_error or "Không lấy được events từ vnstock",
    }


# ---------- Batch fetch nhiều symbols ----------

def _fetch_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch song song qua ThreadPoolExecutor. Trả dict {symbol: payload}."""
    results: Dict[str, Dict[str, Any]] = {}
    unique = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not unique:
        return results

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(unique))) as ex:
        future_map = {ex.submit(_fetch_events_raw, sym): sym for sym in unique}
        for fut in as_completed(future_map):
            sym = future_map[fut]
            try:
                results[sym] = fut.result()
            except Exception as e:
                results[sym] = {
                    "available": False,
                    "symbol": sym,
                    "events": [],
                    "reason": f"Worker exception: {e}",
                }
    return results


# ---------- Public API ----------

def get_dividend_calendar(symbols: List[str], days_ahead: int = 30) -> List[Dict[str, Any]]:
    """
    Lịch chia cổ tức sắp tới cho danh sách mã.

    Filter:
        - type == 'dividend'
        - exec_date HOẶC payment_date nằm trong [now, now + days_ahead]
        - Nếu cả 2 date đều None: bỏ qua (không xác định được mốc thời gian)

    Args:
        symbols: list mã (sẽ uppercase + dedup).
        days_ahead: số ngày tới (default 30).

    Returns:
        List[Dict] sort theo exec_date tăng dần. Mỗi item:
            {symbol, type, event_name, exec_date, payment_date, record_date,
             rate, currency, source, description}
        Item lỗi: {symbol, available: false, reason: ...}
    """
    if not symbols:
        return []

    now = now_vn()
    horizon = now + timedelta(days=max(days_ahead, 0))

    batch = _fetch_batch(symbols)
    out: List[Dict[str, Any]] = []

    for sym, payload in batch.items():
        if not payload.get("available"):
            out.append({
                "symbol": sym,
                "available": False,
                "reason": payload.get("reason", "Không có dữ liệu"),
            })
            continue

        for ev in payload.get("events", []):
            if ev.get("type") != "dividend":
                continue

            exec_dt = _parse_date(ev.get("exec_date"))
            payment_dt = _parse_date(ev.get("payment_date"))
            # Mốc filter: ưu tiên exec_date (ngày GDKHQ), fallback payment_date.
            anchor = exec_dt or payment_dt
            if anchor is None:
                continue
            if anchor < now or anchor > horizon:
                continue

            out.append({
                "symbol": ev.get("symbol"),
                "type": "dividend",
                "event_name": ev.get("event_name"),
                "exec_date": ev.get("exec_date"),
                "payment_date": ev.get("payment_date"),
                "record_date": ev.get("record_date"),
                "rate": ev.get("rate"),
                "currency": ev.get("currency") or "VND",
                "source": ev.get("source"),
                "description": ev.get("description"),
            })

    # Sort theo exec_date tăng dần; item lỗi (None) đẩy về cuối.
    def _sort_key(item: Dict[str, Any]):
        d = _parse_date(item.get("exec_date")) if item.get("exec_date") else None
        return (d is None, d or datetime.max.replace(tzinfo=VN_TZ))

    out.sort(key=_sort_key)
    return out


def get_upcoming_events(symbols: List[str], days_ahead: int = 60) -> List[Dict[str, Any]]:
    """
    Tất cả sự kiện sắp tới: AGM, BCTC, GDKHQ cổ tức.

    Khác `get_dividend_calendar`:
        - KHÔNG filter theo type (lấy hết dividend + earnings + agm + other)
        - Horizon mặc định rộng hơn (60 ngày — ĐHCĐ + BCTC quý thường công bố sớm)

    Returns:
        List[Dict] sort theo mốc thời gian (exec_date hoặc public_date) tăng dần.
    """
    if not symbols:
        return []

    now = now_vn()
    horizon = now + timedelta(days=max(days_ahead, 0))

    batch = _fetch_batch(symbols)
    out: List[Dict[str, Any]] = []

    for sym, payload in batch.items():
        if not payload.get("available"):
            out.append({
                "symbol": sym,
                "available": False,
                "reason": payload.get("reason", "Không có dữ liệu"),
            })
            continue

        for ev in payload.get("events", []):
            exec_dt = _parse_date(ev.get("exec_date"))
            payment_dt = _parse_date(ev.get("payment_date"))
            public_dt = _parse_date(ev.get("public_date"))
            # Ưu tiên exec_date (mốc giao dịch quan trọng nhất với NĐT);
            # fallback payment_date rồi public_date.
            anchor = exec_dt or payment_dt or public_dt
            if anchor is None:
                continue
            if anchor < now or anchor > horizon:
                continue

            out.append({
                "symbol": ev.get("symbol"),
                "type": ev.get("type"),
                "event_name": ev.get("event_name"),
                "event_code": ev.get("event_code"),
                "exec_date": ev.get("exec_date"),
                "payment_date": ev.get("payment_date"),
                "record_date": ev.get("record_date"),
                "public_date": ev.get("public_date"),
                "rate": ev.get("rate"),
                "currency": ev.get("currency"),
                "description": ev.get("description"),
                "source": ev.get("source"),
            })

    def _sort_key(item: Dict[str, Any]):
        anchor_str = item.get("exec_date") or item.get("payment_date") or item.get("public_date")
        d = _parse_date(anchor_str) if anchor_str else None
        return (d is None, d or datetime.max.replace(tzinfo=VN_TZ))

    out.sort(key=_sort_key)
    return out


def get_dividend_history(symbol: str, last_n: int = 10) -> List[Dict[str, Any]]:
    """
    Lịch sử chia cổ tức của 1 mã (đã thực hiện trong quá khứ).

    Filter:
        - type == 'dividend'
        - exec_date HOẶC payment_date <= now

    Args:
        symbol: mã chứng khoán.
        last_n: số sự kiện gần nhất (default 10).

    Returns:
        List[Dict] sort theo exec_date GIẢM dần (mới nhất đầu).
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return []

    payload = _fetch_events_raw(symbol)
    if not payload.get("available"):
        return [{
            "symbol": symbol,
            "available": False,
            "reason": payload.get("reason", "Không có dữ liệu"),
        }]

    now = now_vn()
    history: List[Dict[str, Any]] = []

    for ev in payload.get("events", []):
        if ev.get("type") != "dividend":
            continue
        exec_dt = _parse_date(ev.get("exec_date"))
        payment_dt = _parse_date(ev.get("payment_date"))
        anchor = exec_dt or payment_dt
        if anchor is None or anchor > now:
            # Chưa xảy ra → thuộc calendar, không phải history.
            continue

        history.append({
            "symbol": ev.get("symbol"),
            "type": "dividend",
            "event_name": ev.get("event_name"),
            "exec_date": ev.get("exec_date"),
            "payment_date": ev.get("payment_date"),
            "record_date": ev.get("record_date"),
            "rate": ev.get("rate"),
            "currency": ev.get("currency") or "VND",
            "source": ev.get("source"),
            "description": ev.get("description"),
        })

    def _sort_key(item: Dict[str, Any]):
        d = _parse_date(item.get("exec_date") or item.get("payment_date"))
        # Đảo dấu để sort giảm: dùng tuple (has_date, -timestamp).
        return (d is None, -(d.timestamp() if d else 0))

    history.sort(key=_sort_key)
    return history[: max(last_n, 0)]


def format_calendar_for_prompt(items: List[Dict[str, Any]]) -> str:
    """
    Format lịch sự kiện thành text gọn cho AI prompt context.
    Bỏ qua các record lỗi (available=false).
    """
    valid = [it for it in items if it.get("available", True) is not False]
    if not valid:
        return "Lịch sự kiện sắp tới: Không có sự kiện nào trong khung thời gian."

    lines = ["Lịch sự kiện sắp tới:"]
    for i, it in enumerate(valid, 1):
        sym = it.get("symbol", "?")
        typ = it.get("type", "?")
        name = it.get("event_name") or it.get("event_code") or typ
        when = it.get("exec_date") or it.get("payment_date") or it.get("public_date") or "?"
        # Cắt timezone offset cho dễ đọc
        when_short = when[:10] if isinstance(when, str) and len(when) >= 10 else when
        rate = it.get("rate")
        rate_str = f" — tỷ lệ {rate}" if rate is not None else ""
        currency = it.get("currency") or ""
        lines.append(f"{i}. [{sym}] {when_short} — {name} ({typ}){rate_str} {currency}".rstrip())
    return "\n".join(lines)
