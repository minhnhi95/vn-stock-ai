"""
Insider deals tracker — giao dịch cổ phiếu của lãnh đạo + cổ đông nội bộ.

vnstock 4.x KHÔNG có Company.insider_deals(). Phải gọi Company(symbol,
source='VCI').events() — DataFrame gộp mọi loại sự kiện doanh nghiệp, phân biệt
bằng cột `category`:
    MAJOR_SHAREHOLDER_TRADING  -> giao dịch nội bộ  (module này)
    DIVIDEND                   -> cổ tức            (calendar_service)
    SHAREHOLDER_MEETING        -> ĐHĐCĐ
Chi tiết giao dịch không có cột riêng, tất cả nằm trong chuỗi `event_title_vi`
dạng "Nguyễn Văn Khoa - Đăng kí Mua 428,368 FPT" nên phải parse bằng regex.

Giá trị giao dịch (VND) không có trong events() — module ước lượng bằng
số lượng × giá đóng cửa gần nhất và đánh dấu value_estimated=True.

Cache 1 giờ theo convention (giống fundamentals).

Exports:
- get_insider_deals(symbol, last_n)            — N giao dịch gần nhất
- get_recent_insider_activity(symbols, days)   — tổng kết mua/bán cross-symbol
- format_insider_for_prompt(data)              — text inject vào AI prompt
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from market_service import TTLCache, VN_TZ

try:
    from vnstock import Company
    HAS_COMPANY = True
except ImportError:
    HAS_COMPANY = False


INSIDER_TTL_SECONDS = 3600.0  # 1 giờ — giao dịch nội bộ không đổi liên tục
LARGE_TRADE_VND = 1_000_000_000.0  # > 1 tỷ VND coi là giao dịch lớn

_cache = TTLCache()


# ---------- Helpers ----------

def _safe_str(v) -> str:
    try:
        return str(v).strip() if v is not None else ""
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


def _safe_int(v) -> Optional[int]:
    f = _safe_float(v)
    return int(f) if f is not None else None


def _parse_date(s: str) -> Optional[datetime]:
    """Parse ngày từ nhiều format vnstock có thể trả."""
    s = (s or "").strip()
    if not s:
        return None
    # Cắt phần thời gian nếu có (vnstock đôi khi trả 'YYYY-MM-DD HH:MM:SS')
    s_date = s.split(" ")[0].split("T")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s_date, fmt).replace(tzinfo=VN_TZ)
        except ValueError:
            continue
    return None


# Cột `category` của events() — giá trị ổn định, đáng tin hơn là đoán theo tên.
INSIDER_CATEGORIES = {"MAJOR_SHAREHOLDER_TRADING", "INSIDER_TRADING"}

# "Nguyễn Văn Khoa - Đăng kí Mua 428,368 FPT"
# "CTCP Tập đoàn ABC - Đã bán 1.000.000 HPG"
_TITLE_RE = re.compile(
    r"^(?P<person>.+?)\s*[-–—]\s*"
    r"(?P<status>Đăng\s*k[ýí]|Đã)?\s*"
    r"(?P<action>Mua|Bán)\s+"
    r"(?P<shares>[\d.,]+)\s*"
    r"(?P<ticker>[A-Z]{3})?",
    re.IGNORECASE,
)


def _is_insider_event(row_dict: Dict[str, Any]) -> bool:
    """Row có phải giao dịch nội bộ không — ưu tiên cột category."""
    category = _safe_str(row_dict.get("category")).upper()
    if category:
        if category in INSIDER_CATEGORIES:
            return True
        # category có giá trị rõ ràng khác -> chắc chắn không phải insider.
        return False

    # Version không có `category`: dựa vào tên sự kiện.
    for key in ("event_name_vi", "event_name", "type", "event_type"):
        text = _safe_str(row_dict.get(key)).lower()
        if text and ("nội bộ" in text or "insider" in text or "noi bo" in text):
            return True
    return False


def _parse_shares(raw: str) -> Optional[int]:
    """'428,368' hoặc '1.000.000' -> int. Dấu phân cách khác nhau tuỳ nguồn."""
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else None


def _pick_col(cols_lower: Dict[str, str], *candidates: str) -> Optional[str]:
    """Lấy tên cột thực từ map lower→real, thử exact rồi substring."""
    for cand in candidates:
        if cand in cols_lower:
            return cols_lower[cand]
    for cand in candidates:
        for low, real in cols_lower.items():
            if cand in low:
                return real
    return None


def _first_date(row_dict: Dict[str, Any], *keys: str) -> Optional[str]:
    """Ngày đầu tiên parse được trong các cột ưu tiên, trả ISO 'YYYY-MM-DD'."""
    for key in keys:
        parsed = _parse_date(_safe_str(row_dict.get(key)))
        if parsed:
            return parsed.date().isoformat()
    return None


def _normalize_insider_row(symbol: str, row_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Chuẩn hoá 1 row events() về schema deal mà frontend đang đọc."""
    title = _safe_str(row_dict.get("event_title_vi")) or _safe_str(row_dict.get("event_title_en"))
    event_name = _safe_str(row_dict.get("event_name_vi"))

    match = _TITLE_RE.match(title) if title else None
    if match is None:
        # Không parse được chi tiết thì vẫn giữ lại dòng để người dùng thấy có
        # hoạt động nội bộ, chỉ là thiếu số liệu.
        if not title:
            return None
        return {
            "symbol": symbol,
            "date": _first_date(row_dict, "start_date", "public_date", "display_date1"),
            "person": title,
            "role": event_name,
            "type": "UNKNOWN",
            "shares": None,
            "value": None,
            "value_estimated": False,
            "reason": event_name or title,
            "registered": False,
        }

    action = match.group("action").lower()
    status = _safe_str(match.group("status")).lower()
    shares = _parse_shares(match.group("shares"))

    return {
        "symbol": symbol,
        "date": _first_date(row_dict, "start_date", "public_date", "display_date1"),
        "end_date": _first_date(row_dict, "end_date", "display_date2"),
        "person": _safe_str(match.group("person")),
        "role": event_name,
        "type": "BUY" if action.startswith("mua") else "SELL",
        "shares": shares,
        "value": None,          # events() không có giá trị VND — điền sau khi biết giá
        "value_estimated": False,
        # "Đăng ký" = mới đăng ký, chưa chắc khớp; "Đã" = đã thực hiện.
        "registered": status.startswith("đăng"),
        "reason": title,
    }


def _fetch_insider_events(symbol: str) -> List[Dict[str, Any]]:
    """
    Gọi vnstock Company.events() và filter rows là giao dịch nội bộ.
    Trả [] nếu không lấy được — caller xử lý fallback.
    """
    if not HAS_COMPANY:
        return []

    last_err = None
    for source in ("VCI", "KBS"):
        try:
            c = Company(symbol=symbol, source=source)
            if not hasattr(c, "events"):
                continue
            df = c.events()
            if df is None or df.empty:
                continue

            records: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                if not _is_insider_event(row_dict):
                    continue
                normalized = _normalize_insider_row(symbol, row_dict)
                if normalized:
                    records.append(normalized)

            if records:
                # Mới nhất trước; dòng thiếu ngày đẩy xuống cuối.
                records.sort(key=lambda r: r.get("date") or "0000-00-00", reverse=True)
                return records
        except Exception as e:
            last_err = str(e)
            continue

    if last_err:
        print(f"[insider] events() failed for {symbol}: {last_err}")
    return []


def _attach_estimated_values(symbol: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Quy đổi số lượng ra VND bằng giá gần nhất.

    Đây là ƯỚC LƯỢNG: giá khớp thật của từng giao dịch nội bộ không được công bố
    trong events(). Đánh dấu value_estimated để UI/prompt nói rõ.
    """
    try:
        from market_service import fetch_realtime_price

        price = (fetch_realtime_price(symbol) or {}).get("price")
    except Exception:
        price = None

    if not price or price <= 0:
        return records

    for r in records:
        if r.get("shares"):
            r["value"] = float(r["shares"]) * float(price)
            r["value_estimated"] = True
    return records


# ---------- Public API ----------

def get_insider_deals(symbol: str, last_n: int = 20) -> List[Dict[str, Any]]:
    """
    Trả về tối đa last_n giao dịch insider gần nhất cho symbol.
    Cache 1 giờ. Không có dữ liệu → trả [].
    """
    symbol = symbol.strip().upper()
    cache_key = f"insider:{symbol}"

    cached = _cache.get(cache_key)
    if cached is None:
        records = _fetch_insider_events(symbol)
        # Cache cả list rỗng để tránh hammer API khi mã không có insider data
        _cache.set(cache_key, records, INSIDER_TTL_SECONDS)
        cached = records

    # Quy đổi giá trị NGOÀI cache: giá lấy từ market_service (đã có cache riêng
    # và fallback giá đóng cửa). Nếu gộp vào cache 1 giờ ở trên thì một lần
    # vnstock rate-limit sẽ khoá cột "giá trị" ở mức rỗng suốt cả tiếng.
    selected = [dict(r) for r in cached[: max(0, int(last_n))]]
    return _attach_estimated_values(symbol, selected)


def summarize_deals(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Gộp danh sách deal thành số tổng cho UI.
    Trả cả theo giá trị (VND ước lượng) và theo số lượng cổ phiếu.
    """
    buy_value = sum(d.get("value") or 0.0 for d in deals if d.get("type") == "BUY")
    sell_value = sum(d.get("value") or 0.0 for d in deals if d.get("type") == "SELL")
    buy_shares = sum(d.get("shares") or 0 for d in deals if d.get("type") == "BUY")
    sell_shares = sum(d.get("shares") or 0 for d in deals if d.get("type") == "SELL")
    return {
        "buy_value": buy_value,
        "sell_value": sell_value,
        "net": buy_value - sell_value,
        "buy_shares": buy_shares,
        "sell_shares": sell_shares,
        "net_shares": buy_shares - sell_shares,
        "count": len(deals),
        "value_estimated": any(d.get("value_estimated") for d in deals),
    }


def get_insider_report(symbol: str, days: int = 30, last_n: int = 20) -> Dict[str, Any]:
    """
    Payload hoàn chỉnh cho panel: deals trong `days` ngày + summary.

    Giao dịch nội bộ thưa (có mã cả quý mới có 1 lần), nên khi cửa sổ `days`
    rỗng thì trả về các giao dịch gần nhất và bật cờ `window_empty` để UI đổi
    nhãn thay vì hiện "không có gì".
    """
    symbol = symbol.strip().upper()
    all_deals = get_insider_deals(symbol, last_n=200)
    if not all_deals:
        return {
            "symbol": symbol,
            "days": days,
            "deals": [],
            "summary": summarize_deals([]),
            "period_label": f"{days} ngày qua",
            "window_empty": False,
        }

    cutoff = (datetime.now(VN_TZ) - timedelta(days=max(1, int(days)))).date().isoformat()
    in_window = [d for d in all_deals if (d.get("date") or "") >= cutoff]

    window_empty = not in_window
    deals = (in_window or all_deals)[: max(1, int(last_n))]
    if window_empty:
        newest = deals[0].get("date") or "?"
        period_label = f"Gần nhất: {newest}"
    else:
        period_label = f"{days} ngày qua"

    return {
        "symbol": symbol,
        "days": days,
        "deals": deals,
        "summary": summarize_deals(deals),
        "period_label": period_label,
        "window_empty": window_empty,
    }


def get_recent_insider_activity(symbols: List[str], days: int = 30) -> Dict[str, Any]:
    """
    Tổng kết hoạt động insider trên nhiều mã trong N ngày gần nhất.
    Trả:
        {
          "available": bool,
          "window_days": int,
          "since": "YYYY-MM-DD",
          "per_symbol": {SYMBOL: {buy_value, sell_value, net_value, signal, trades:[...]}},
          "top_buyers": [{symbol, net_value}, ...],
          "top_sellers": [{symbol, net_value}, ...],
          "large_trades": [...],
        }
    signal: STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL — dựa trên |net_value|.
    """
    if not symbols:
        return {"available": False, "reason": "Danh sách symbol trống"}

    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(days=max(1, int(days)))
    cutoff_iso = cutoff.date().isoformat()

    per_symbol: Dict[str, Dict[str, Any]] = {}
    large_trades: List[Dict[str, Any]] = []
    any_data = False

    for sym in symbols:
        sym = sym.strip().upper()
        if not sym:
            continue
        deals = get_insider_deals(sym, last_n=200)
        if not deals:
            per_symbol[sym] = {
                "available": False,
                "buy_value_vnd": 0.0,
                "sell_value_vnd": 0.0,
                "net_value_vnd": 0.0,
                "signal": "NEUTRAL",
                "trade_count": 0,
                "trades": [],
            }
            continue

        any_data = True
        buy_value = 0.0
        sell_value = 0.0
        in_window: List[Dict[str, Any]] = []
        for d in deals:
            # Lọc theo cửa sổ ngày — thiếu ngày thì giữ lại, không loại oan.
            if d.get("date") and d["date"] < cutoff_iso:
                continue
            in_window.append(d)
            val = d.get("value") or 0.0
            if d.get("type") == "BUY":
                buy_value += val
            elif d.get("type") == "SELL":
                sell_value += val
            if val >= LARGE_TRADE_VND:
                large_trades.append(d)

        net_value = buy_value - sell_value
        # Signal strength: dựa trên |net| so với LARGE_TRADE_VND
        abs_net = abs(net_value)
        if abs_net >= 5 * LARGE_TRADE_VND:
            signal = "STRONG_BUY" if net_value > 0 else "STRONG_SELL"
        elif abs_net >= LARGE_TRADE_VND:
            signal = "BUY" if net_value > 0 else "SELL"
        else:
            signal = "NEUTRAL"

        per_symbol[sym] = {
            "available": True,
            "buy_value_vnd": buy_value,
            "sell_value_vnd": sell_value,
            "net_value_vnd": net_value,
            "signal": signal,
            "trade_count": len(in_window),
            "trades": in_window[:10],  # Top 10 gần nhất để UI hiển thị
        }

    # Top buyers / sellers (chỉ tính mã có data)
    ranked = [
        {"symbol": s, "net_value_vnd": d["net_value_vnd"], "signal": d["signal"]}
        for s, d in per_symbol.items() if d.get("available")
    ]
    top_buyers = sorted([r for r in ranked if r["net_value_vnd"] > 0], key=lambda r: r["net_value_vnd"], reverse=True)[:5]
    top_sellers = sorted([r for r in ranked if r["net_value_vnd"] < 0], key=lambda r: r["net_value_vnd"])[:5]

    # Sort large trades theo value giảm dần
    large_trades.sort(key=lambda d: d.get("value_vnd") or 0.0, reverse=True)

    return {
        "available": any_data,
        "window_days": int(days),
        "since": cutoff_iso,
        "per_symbol": per_symbol,
        "top_buyers": top_buyers,
        "top_sellers": top_sellers,
        "large_trades": large_trades[:20],
        "reason": None if any_data else "Không có dữ liệu insider cho bất kỳ mã nào",
    }


# ---------- Format cho AI prompt ----------

def _format_vnd(v: Optional[float]) -> str:
    """Định dạng số VND sang tỷ/triệu để prompt ngắn gọn."""
    if v is None:
        return "N/A"
    abs_v = abs(v)
    sign = "-" if v < 0 else ""
    if abs_v >= 1e9:
        return f"{sign}{abs_v / 1e9:.2f} tỷ VND"
    if abs_v >= 1e6:
        return f"{sign}{abs_v / 1e6:.1f} triệu VND"
    return f"{sign}{abs_v:,.0f} VND"


def format_insider_for_prompt(data: Any) -> str:
    """
    Format insider data cho AI prompt.
    Chấp nhận:
    - list[dict] (output của get_insider_deals)
    - dict (output của get_recent_insider_activity)
    """
    # Case dict: recent activity summary
    if isinstance(data, dict):
        if not data.get("available"):
            return f"Giao dịch nội bộ: Không có dữ liệu ({data.get('reason', '')})."

        lines = [f"Giao dịch nội bộ ({data.get('window_days', 30)} ngày gần nhất):"]
        per_symbol = data.get("per_symbol", {})
        for sym, info in per_symbol.items():
            if not info.get("available"):
                continue
            lines.append(
                f"- {sym}: mua {_format_vnd(info['buy_value_vnd'])}, "
                f"bán {_format_vnd(info['sell_value_vnd'])}, "
                f"net {_format_vnd(info['net_value_vnd'])} → tín hiệu {info['signal']} "
                f"({info['trade_count']} giao dịch)"
            )

        if data.get("top_buyers"):
            lines.append("\nMã được nội bộ mua ròng mạnh nhất:")
            for r in data["top_buyers"][:3]:
                lines.append(f"  • {r['symbol']}: +{_format_vnd(r['net_value_vnd'])} ({r['signal']})")
        if data.get("top_sellers"):
            lines.append("\nMã bị nội bộ bán ròng mạnh nhất:")
            for r in data["top_sellers"][:3]:
                lines.append(f"  • {r['symbol']}: {_format_vnd(r['net_value_vnd'])} ({r['signal']})")

        large = data.get("large_trades", [])
        if large:
            lines.append(f"\nGiao dịch lớn (> 1 tỷ VND), tối đa 5:")
            for d in large[:5]:
                lines.append(
                    f"  • {d['symbol']} - {d.get('person_name', 'N/A')} "
                    f"({d.get('position') or 'cổ đông'}): "
                    f"{d['action']} {d.get('volume') or 0:,} cp, "
                    f"giá trị {_format_vnd(d.get('value_vnd'))} - {d.get('date') or 'N/A'}"
                )
        return "\n".join(lines)

    # Case list: deals của 1 symbol
    if isinstance(data, list):
        if not data:
            return "Giao dịch nội bộ: Không có dữ liệu trong thời gian gần đây."
        lines = ["Giao dịch nội bộ gần nhất:"]
        buy_total = 0.0
        sell_total = 0.0
        for i, d in enumerate(data[:10], 1):
            person = d.get("person") or "N/A"
            role = f" ({d['role']})" if d.get("role") else ""
            vol = d.get("shares") or 0
            val = d.get("value") or 0.0
            val_str = _format_vnd(d.get("value"))
            if d.get("value_estimated"):
                val_str += " (ước tính theo giá hiện tại)"
            date_str = d.get("date") or "N/A"
            status = "đăng ký" if d.get("registered") else "đã thực hiện"
            large_marker = " [LỚN]" if val >= LARGE_TRADE_VND else ""
            lines.append(
                f"{i}. [{date_str}] {person}{role}: {d.get('type', 'N/A')} {vol:,} cp "
                f"({status}), giá trị {val_str}{large_marker}"
            )
            if d.get("type") == "BUY":
                buy_total += val
            elif d.get("type") == "SELL":
                sell_total += val

        net = buy_total - sell_total
        lines.append(
            f"\nTổng kết: mua {_format_vnd(buy_total)}, bán {_format_vnd(sell_total)}, "
            f"net {_format_vnd(net)}"
        )
        return "\n".join(lines)

    return "Giao dịch nội bộ: Định dạng dữ liệu không hợp lệ."
