"""
Insider deals tracker — giao dịch cổ phiếu của lãnh đạo + cổ đông nội bộ.

Theo probe Phase 1: vnstock 4.0.4 KHÔNG expose Company.insider_deals() riêng biệt.
Phải gọi unified endpoint Company(symbol, source='VCI').events() — trả về DataFrame
gộp 3 loại sự kiện: dividends, insider_deals, earnings/AGM. Service này filter
type insider_deals trước khi normalize.

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


def _classify_action(text: str) -> str:
    """Phân loại BUY / SELL / REGISTER_BUY / REGISTER_SELL / UNKNOWN từ text tiếng Việt."""
    t = (text or "").lower()
    # Đã thực hiện
    if any(k in t for k in ("đã mua", "da mua", "mua vào", "mua vao", "bought", "purchased")):
        return "BUY"
    if any(k in t for k in ("đã bán", "da ban", "bán ra", "ban ra", "sold")):
        return "SELL"
    # Đăng ký
    if any(k in t for k in ("đăng ký mua", "dang ky mua", "register to buy", "intends to buy")):
        return "REGISTER_BUY"
    if any(k in t for k in ("đăng ký bán", "dang ky ban", "register to sell", "intends to sell")):
        return "REGISTER_SELL"
    # Generic fallback
    if "mua" in t:
        return "BUY"
    if "bán" in t or "ban" in t:
        return "SELL"
    return "UNKNOWN"


def _is_insider_event(row_dict: Dict[str, Any]) -> bool:
    """
    Heuristic detect row là insider_deal trong events() DataFrame.
    Probe finding cho thấy events() có cột type/event_type — value có thể là:
    - 'insider_deal', 'insider_trading', 'GIAO_DICH_CO_DONG_NOI_BO', ...
    Fallback: nếu có cột volume + price + person_name → coi là insider.
    """
    type_keys = ("type", "event_type", "category", "event_category", "loai_su_kien")
    for k in type_keys:
        v = row_dict.get(k)
        if v is None:
            continue
        s = str(v).lower()
        if any(tok in s for tok in (
            "insider", "co_dong_noi_bo", "co dong noi bo",
            "noi_bo", "noibo", "giao_dich", "transaction",
        )):
            return True
        # Loại sự kiện rõ ràng KHÔNG phải insider
        if any(tok in s for tok in ("dividend", "co_tuc", "agm", "earnings", "report")):
            return False
    # Fallback: có name + volume + price thì hầu như là insider
    has_name = any(row_dict.get(k) for k in ("person_name", "name", "ten_nguoi", "shareholder"))
    has_vol = any(row_dict.get(k) for k in ("volume", "quantity", "so_luong", "shares"))
    return has_name and has_vol


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


def _normalize_insider_row(symbol: str, row_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Chuẩn hóa 1 row từ events() về schema insider deal nội bộ."""
    cols_lower = {k.lower(): k for k in row_dict.keys()}

    name_col = _pick_col(cols_lower, "person_name", "shareholder", "name", "ten_nguoi", "ten")
    position_col = _pick_col(cols_lower, "position", "chuc_vu", "title", "role")
    action_col = _pick_col(cols_lower, "action", "type_transaction", "transaction_type", "loai_giao_dich", "description", "title")
    volume_col = _pick_col(cols_lower, "volume", "quantity", "so_luong", "shares", "khoi_luong")
    price_col = _pick_col(cols_lower, "price", "avg_price", "gia", "gia_giao_dich")
    value_col = _pick_col(cols_lower, "value", "gia_tri", "total_value", "transaction_value")
    date_col = _pick_col(cols_lower, "date", "transaction_date", "ngay_giao_dich", "public_date", "ngay")
    note_col = _pick_col(cols_lower, "note", "ghi_chu", "description", "content", "title")

    person = _safe_str(row_dict.get(name_col)) if name_col else ""
    position = _safe_str(row_dict.get(position_col)) if position_col else ""

    # Action: kết hợp action_col và note_col để phân loại
    action_text = " ".join([
        _safe_str(row_dict.get(action_col)) if action_col else "",
        _safe_str(row_dict.get(note_col)) if note_col else "",
    ])
    action = _classify_action(action_text)

    volume = _safe_int(row_dict.get(volume_col)) if volume_col else None
    price_raw = _safe_float(row_dict.get(price_col)) if price_col else None
    # vnstock thường trả giá theo nghìn đồng (ví dụ 73.7 thay vì 73700)
    price_vnd = None
    if price_raw is not None:
        price_vnd = price_raw * 1000.0 if price_raw < 1000 else price_raw

    value_raw = _safe_float(row_dict.get(value_col)) if value_col else None
    # value đôi khi trả tỷ đồng — heuristic: nếu value < 1e6 và có volume*price hợp lý thì *1e9
    value_vnd: Optional[float] = None
    if value_raw is not None:
        if value_raw < 1e6 and volume and price_vnd:
            value_vnd = value_raw * 1e9
        else:
            value_vnd = value_raw
    elif volume and price_vnd:
        value_vnd = float(volume) * price_vnd

    date_str = _safe_str(row_dict.get(date_col)) if date_col else ""
    parsed_date = _parse_date(date_str)

    # Phải có ít nhất 1 trong: person hoặc volume — nếu trống cả 2 thì bỏ
    if not person and not volume:
        return None

    return {
        "symbol": symbol,
        "person_name": person or "N/A",
        "position": position or "",
        "action": action,
        "volume": volume,
        "price_vnd": price_vnd,
        "value_vnd": value_vnd,
        "is_large_trade": bool(value_vnd and value_vnd >= LARGE_TRADE_VND),
        "date": date_str,
        "date_iso": parsed_date.date().isoformat() if parsed_date else None,
        "note": _safe_str(row_dict.get(note_col)) if note_col else "",
    }


# ---------- Fetch chính ----------

def _fetch_insider_events(symbol: str) -> List[Dict[str, Any]]:
    """
    Gọi vnstock Company.events() và filter rows là insider_deal.
    Defensive với nhiều source. Trả [] nếu không lấy được — caller xử lý fallback.
    """
    if not HAS_COMPANY:
        return []

    last_err = None
    for source in ("VCI", "TCBS"):
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
                # Sort theo ngày giảm dần (mới nhất trước). Row không có date_iso đẩy xuống cuối.
                records.sort(
                    key=lambda r: r.get("date_iso") or "0000-00-00",
                    reverse=True,
                )
                return records
        except Exception as e:
            last_err = str(e)
            continue

    if last_err:
        print(f"[insider] events() failed for {symbol}: {last_err}")
    return []


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

    return cached[: max(0, int(last_n))]


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
            # Lọc theo cửa sổ ngày — nếu thiếu date_iso thì bỏ qua điều kiện
            if d.get("date_iso") and d["date_iso"] < cutoff_iso:
                continue
            in_window.append(d)
            val = d.get("value_vnd") or 0.0
            if d["action"] in ("BUY", "REGISTER_BUY"):
                buy_value += val
            elif d["action"] in ("SELL", "REGISTER_SELL"):
                sell_value += val
            if d.get("is_large_trade"):
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
            person = d.get("person_name", "N/A")
            pos = f" ({d['position']})" if d.get("position") else ""
            vol = d.get("volume") or 0
            val_str = _format_vnd(d.get("value_vnd"))
            date_str = d.get("date") or "N/A"
            large_marker = " [LỚN]" if d.get("is_large_trade") else ""
            lines.append(
                f"{i}. [{date_str}] {person}{pos}: {d['action']} {vol:,} cp, "
                f"giá trị {val_str}{large_marker}"
            )
            val = d.get("value_vnd") or 0.0
            if d["action"] in ("BUY", "REGISTER_BUY"):
                buy_total += val
            elif d["action"] in ("SELL", "REGISTER_SELL"):
                sell_total += val

        net = buy_total - sell_total
        lines.append(
            f"\nTổng kết: mua {_format_vnd(buy_total)}, bán {_format_vnd(sell_total)}, "
            f"net {_format_vnd(net)}"
        )
        return "\n".join(lines)

    return "Giao dịch nội bộ: Định dạng dữ liệu không hợp lệ."
