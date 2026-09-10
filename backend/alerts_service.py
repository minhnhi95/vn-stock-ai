"""
Alert engine — người dùng định nghĩa rule cảnh báo, engine đánh giá khi được gọi.

Triết lý lưu trữ:
- Lưu trong DB dùng chung với portfolio (SQLite khi dev, Postgres khi deploy).
- Lý do: alerts là dữ liệu nhỏ (vài chục → vài trăm rule cho 1 user), không cần SQL.
- KHÔNG quay lại file JSON: production chạy 2 gunicorn worker (mỗi worker một bản
  state riêng, ghi đè lẫn nhau) và filesystem Railway/Render là ephemeral nên
  redeploy sẽ xoá sạch alert người dùng đã đặt.

Các loại điều kiện hỗ trợ:
- price_above / price_below  : so giá realtime với threshold (VND)
- rsi_above / rsi_below      : so RSI(14) phiên gần nhất với threshold
- ema_cross_up               : EMA20 vừa cắt LÊN EMA50 (phiên gần nhất so với phiên trước)
- ema_cross_down             : EMA20 vừa cắt XUỐNG EMA50
- ai_signal_change           : khuyến nghị AI thay đổi so với lần check trước
                                (threshold không dùng — đặt 0)
- news_new                   : có tin mới về doanh nghiệp kể từ lúc đặt cảnh báo
                                (threshold không dùng — đặt 0)

Workflow:
1. POST /alerts → create_alert(...)
2. Frontend (hoặc cron) gọi GET /alerts/check → check_alerts()
   - engine group rule theo symbol để fetch dữ liệu 1 lần / symbol
   - rule nào triggered: set triggered_at + active=False (one-shot), trả về list

Tất cả comment + reason đều tiếng Việt.
"""
from __future__ import annotations

import storage_service as storage
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

VN_TZ = timezone(timedelta(hours=7))

# Import phòng thủ: alerts engine phụ thuộc stock_service để lấy chỉ báo,
# market_service để lấy giá realtime, ai_service để check signal change.
# Nếu module nào fail import (vd thiếu dep) → engine vẫn run, chỉ skip condition đó.
try:
    from market_service import fetch_realtime_price, TTLCache
    HAS_MARKET = True
except Exception:
    HAS_MARKET = False

    class TTLCache:  # type: ignore[no-redef]
        """Stub fallback nếu market_service không import được."""

        def get(self, key):
            return None

        def set(self, key, value, ttl_seconds):
            pass

try:
    from stock_service import fetch_stock_data
    HAS_STOCK = True
except Exception:
    HAS_STOCK = False

try:
    from news_service import get_recent_news
    HAS_NEWS = True
except Exception:
    HAS_NEWS = False


# ---------- Hằng số ----------

# Cache giá + chỉ báo trong 1 lần check_alerts để mỗi symbol fetch 1 lần.
# TTL ngắn (10s) vì check_alerts thường chạy theo poll interval >= 30s.
_SYMBOL_DATA_TTL = 10.0

# Tập hợp condition hợp lệ — dùng để validate input.
VALID_CONDITIONS = {
    "price_above",
    "price_below",
    "rsi_above",
    "rsi_below",
    "ema_cross_up",
    "ema_cross_down",
    "ai_signal_change",
    "news_new",
}


# ---------- CRUD API ----------

def create_alert(symbol: str, condition: str, threshold: float) -> Dict[str, Any]:
    """
    Tạo alert mới. Trả về rule đầy đủ kèm id.

    Raises:
        ValueError: nếu condition không hợp lệ hoặc symbol rỗng.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Mã cổ phiếu không được rỗng")
    if condition not in VALID_CONDITIONS:
        raise ValueError(
            f"Điều kiện '{condition}' không hợp lệ. "
            f"Hỗ trợ: {sorted(VALID_CONDITIONS)}"
        )

    # threshold cho ai_signal_change không có ý nghĩa thực — chấp nhận 0/None.
    try:
        threshold_val = float(threshold) if threshold is not None else 0.0
    except (TypeError, ValueError):
        raise ValueError("Threshold phải là số")

    rule = {
        "id": str(uuid.uuid4()),
        "symbol": symbol,
        "condition": condition,
        "threshold": threshold_val,
        "created_at": int(time.time()),
        "triggered_at": None,
        "active": True,
    }
    return storage.insert_alert_rule(rule)


def list_alerts(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Liệt kê alerts. Nếu truyền symbol → chỉ lọc symbol đó (case-insensitive).
    Sắp xếp theo created_at giảm dần (mới nhất lên đầu) cho UI dễ đọc.
    """
    return storage.list_alert_rules(symbol.strip().upper() if symbol else None)


def delete_alert(alert_id: str) -> bool:
    """Xóa rule theo id. Trả True nếu tồn tại và xóa thành công."""
    return storage.delete_alert_rule(alert_id)


def mark_triggered(alert_id: str) -> None:
    """
    Đánh dấu rule đã trigger: set triggered_at + active=False (one-shot semantics).
    Idempotent — gọi trên id không tồn tại không raise.
    """
    storage.mark_alert_rule_triggered(alert_id, int(time.time()))


# ---------- Helpers fetch dữ liệu per-symbol ----------

# Cache TTL ngắn để batch nhiều rule cùng symbol trong 1 lần check.
_data_cache = TTLCache()


def _fetch_symbol_snapshot(symbol: str) -> Dict[str, Any]:
    """
    Lấy snapshot cho symbol: giá realtime + chỉ báo phiên gần nhất.

    Trả về:
        {
            "symbol": str,
            "price": float | None,
            "rsi": float | None,
            "ema20": float | None,
            "ema50": float | None,
            "ema20_prev": float | None,   # phiên trước, để detect cross
            "ema50_prev": float | None,
            "error": str | None,
        }
    """
    cache_key = f"snapshot:{symbol}"
    cached = _data_cache.get(cache_key)
    if cached is not None:
        return cached

    snap: Dict[str, Any] = {
        "symbol": symbol,
        "price": None,
        "rsi": None,
        "ema20": None,
        "ema50": None,
        "ema20_prev": None,
        "ema50_prev": None,
        "error": None,
    }

    # 1) Giá realtime — ưu tiên vnstock intraday qua market_service
    if HAS_MARKET:
        try:
            rt = fetch_realtime_price(symbol)
            if rt and rt.get("price"):
                snap["price"] = float(rt["price"])
        except Exception as e:
            snap["error"] = f"realtime: {e}"

    # 2) Chỉ báo từ history — cần ít nhất 50 phiên cho EMA50
    if HAS_STOCK:
        try:
            df, _ = fetch_stock_data(symbol, period="3mo", interval="1d")
            if df is not None and not df.empty and len(df) >= 2:
                last = df.iloc[-1]
                prev = df.iloc[-2]
                # Nếu chưa có giá realtime → fallback giá đóng cửa phiên cuối
                if snap["price"] is None:
                    snap["price"] = float(last["Close"])
                snap["rsi"] = float(last["RSI"]) if "RSI" in df.columns else None
                snap["ema20"] = float(last["EMA20"]) if "EMA20" in df.columns else None
                snap["ema50"] = float(last["EMA50"]) if "EMA50" in df.columns else None
                snap["ema20_prev"] = float(prev["EMA20"]) if "EMA20" in df.columns else None
                snap["ema50_prev"] = float(prev["EMA50"]) if "EMA50" in df.columns else None
        except Exception as e:
            prev_err = snap.get("error")
            snap["error"] = f"{prev_err}; history: {e}" if prev_err else f"history: {e}"

    _data_cache.set(cache_key, snap, _SYMBOL_DATA_TTL)
    return snap


def _get_last_ai_signal(symbol: str) -> Optional[str]:
    """Đọc khuyến nghị AI lần check trước. None nếu chưa từng lưu."""
    return storage.get_ai_signals().get(symbol)


def _set_last_ai_signal(symbol: str, recommendation: str) -> None:
    """Lưu khuyến nghị AI mới nhất để lần check sau so sánh."""
    storage.set_ai_signal(symbol, recommendation)


def _fetch_current_ai_signal(symbol: str) -> Optional[str]:
    """
    Lấy khuyến nghị AI hiện tại. Trả None nếu không thể đánh giá
    (vd thiếu API key, lỗi mạng) — engine sẽ bỏ qua rule ai_signal_change
    thay vì giả thay đổi.

    Lưu ý: gọi AI tốn cost. Engine batch sẵn bằng cache TTL 10s ở
    _fetch_symbol_snapshot, nhưng AI call vẫn nên chạy ngoài hot-path.
    Ở MVP này: AI signal được lưu ở bảng ai_signal, cập nhật bởi route
    /analyze (caller bên ngoài). Engine chỉ so sánh.

    Trả về None ở đây để rule ai_signal_change chỉ trigger khi
    caller chủ động update qua update_ai_signal() bên dưới.
    """
    return None


def update_ai_signal(symbol: str, recommendation: str) -> Dict[str, Any]:
    """
    Endpoint để route /analyze gọi sau mỗi lần AI trả khuyến nghị mới.
    So sánh với signal cũ → nếu khác → đánh dấu các rule ai_signal_change
    của symbol này pending trigger ở lần check_alerts() kế tiếp.

    Trả về:
        { "changed": bool, "previous": str|None, "current": str }
    """
    symbol = (symbol or "").strip().upper()
    rec = (recommendation or "").strip().upper()
    if not symbol or not rec:
        return {"changed": False, "previous": None, "current": rec}

    previous = _get_last_ai_signal(symbol)
    changed = previous is not None and previous != rec
    _set_last_ai_signal(symbol, rec)
    if changed:
        # Ghi xuống DB thay vì giữ trong process: check_alerts chạy ở request khác.
        storage.mark_ai_signal_pending(symbol)
    return {"changed": changed, "previous": previous, "current": rec}


# ---------- Evaluators ----------
# Mỗi evaluator nhận (rule, snapshot, ctx) → bool (triggered or not).
# ctx chứa thông tin shared (vd ai_changed_symbols set) để evaluator dùng chung.

def _eval_price_above(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    p = snap.get("price")
    return p is not None and p > rule["threshold"]


def _eval_price_below(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    p = snap.get("price")
    return p is not None and p < rule["threshold"]


def _eval_rsi_above(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    r = snap.get("rsi")
    return r is not None and r > rule["threshold"]


def _eval_rsi_below(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    r = snap.get("rsi")
    return r is not None and r < rule["threshold"]


def _eval_ema_cross_up(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """EMA20 vừa cắt LÊN EMA50: phiên trước EMA20 <= EMA50, phiên hiện tại EMA20 > EMA50."""
    e20, e50 = snap.get("ema20"), snap.get("ema50")
    e20p, e50p = snap.get("ema20_prev"), snap.get("ema50_prev")
    if None in (e20, e50, e20p, e50p):
        return False
    return e20p <= e50p and e20 > e50


def _eval_ema_cross_down(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """EMA20 vừa cắt XUỐNG EMA50."""
    e20, e50 = snap.get("ema20"), snap.get("ema50")
    e20p, e50p = snap.get("ema20_prev"), snap.get("ema50_prev")
    if None in (e20, e50, e20p, e50p):
        return False
    return e20p >= e50p and e20 < e50


def _eval_ai_signal_change(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Trigger khi caller đã gọi update_ai_signal() với rec khác lần trước.
    Engine không tự gọi AI ở đây để tránh cost. ctx["ai_changed_symbols"]
    là set các symbol mới đổi tín hiệu trong batch check hiện tại.
    """
    return rule["symbol"] in ctx.get("ai_changed_symbols", set())


def _parse_published_at(value: Any) -> Optional[int]:
    """
    Đổi published_at ISO ('2026-08-26T17:10:05') sang epoch giây.

    Nguồn tin không kèm timezone. Coi như giờ Việt Nam vì đó là múi giờ của cả
    sàn lẫn của các trang tin trong nước — diễn giải nhầm sang UTC sẽ đẩy mọi tin
    lùi 7 tiếng và làm tin vừa ra trông như cũ.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return int(dt.timestamp())


def _fetch_latest_news(symbol: str) -> Optional[Dict[str, Any]]:
    """Tin mới nhất của một mã, kèm mốc thời gian đã đổi sang epoch."""
    if not HAS_NEWS:
        return None
    cache_key = f"news_latest:{symbol}"
    cached = _data_cache.get(cache_key)
    if cached is not None:
        return cached

    latest = None
    try:
        for item in get_recent_news(symbol, limit=5) or []:
            ts = _parse_published_at(item.get("published_at"))
            if ts is None:
                continue
            if latest is None or ts > latest["published_ts"]:
                latest = {
                    "published_ts": ts,
                    "title": item.get("title") or "",
                    "url": item.get("url"),
                    "source": item.get("source"),
                }
    except Exception as e:
        print(f"[alerts_service] Loi lay tin {symbol}: {e}")
        return None

    _data_cache.set(cache_key, latest, _SYMBOL_DATA_TTL)
    return latest


def _eval_news_new(rule: Dict[str, Any], snap: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Trigger khi có tin phát hành SAU thời điểm đặt cảnh báo.

    So với created_at chứ không phải "lần check trước": rule là one-shot, bắn xong
    là tắt. Người dùng bật lại thì created_at mới, nên tin cũ không bắn lại.
    """
    latest = (ctx.get("news") or {}).get(rule["symbol"])
    if not latest:
        return False
    return latest["published_ts"] > int(rule.get("created_at") or 0)


_EVALUATORS = {
    "price_above": _eval_price_above,
    "price_below": _eval_price_below,
    "rsi_above": _eval_rsi_above,
    "rsi_below": _eval_rsi_below,
    "ema_cross_up": _eval_ema_cross_up,
    "ema_cross_down": _eval_ema_cross_down,
    "ai_signal_change": _eval_ai_signal_change,
    "news_new": _eval_news_new,
}


# ---------- Engine chính ----------

def check_alerts(ai_changed_symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Đánh giá toàn bộ rule active. Group theo symbol để fetch giá/chỉ báo 1 lần per symbol.

    Args:
        ai_changed_symbols: list symbol mà caller đã xác định AI signal vừa đổi
                            (vd: sau khi route /analyze chạy xong). Engine không tự
                            gọi AI để tránh cost — caller chủ động truyền vào.

    Returns:
        Danh sách rule đã trigger lần này. Mỗi rule đã được mark_triggered
        (active=False, triggered_at=now) trước khi return.
    """
    active_rules = [r for r in storage.list_alert_rules() if r.get("active")]

    if not active_rules:
        return []

    # Gộp symbol caller truyền vào với symbol đã được /analyze đánh dấu từ trước.
    pending = storage.take_ai_signal_pending()
    ctx = {
        "ai_changed_symbols": {
            s.strip().upper() for s in list(ai_changed_symbols or []) + pending if s
        },
        "news": {},
    }

    # Chỉ lấy tin cho mã thật sự có rule news_new. Lấy cho mọi mã sẽ tốn thêm một
    # request vnstock mỗi mã mỗi lần check, trong khi hạn mức chỉ 20 request/phút.
    for sym in {r["symbol"] for r in active_rules if r["condition"] == "news_new"}:
        ctx["news"][sym] = _fetch_latest_news(sym)

    # Group theo symbol → fetch 1 lần
    symbols = sorted({r["symbol"] for r in active_rules})
    snapshots: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        try:
            snapshots[sym] = _fetch_symbol_snapshot(sym)
        except Exception as e:
            # Symbol fail → snapshot rỗng, rule không trigger
            print(f"[alerts_service] Lỗi fetch snapshot {sym}: {e}")
            snapshots[sym] = {"symbol": sym, "error": str(e)}

    triggered: List[Dict[str, Any]] = []
    for rule in active_rules:
        evaluator = _EVALUATORS.get(rule["condition"])
        if evaluator is None:
            continue
        snap = snapshots.get(rule["symbol"], {})
        try:
            fired = evaluator(rule, snap, ctx)
        except Exception as e:
            print(f"[alerts_service] Evaluator lỗi cho rule {rule['id']}: {e}")
            fired = False

        if fired:
            mark_triggered(rule["id"])
            # Kèm thêm context snapshot để UI hiển thị "giá khi trigger"
            triggered.append({
                **rule,
                "triggered_at": int(time.time()),
                "active": False,
                "context": {
                    "price": snap.get("price"),
                    "rsi": snap.get("rsi"),
                    "ema20": snap.get("ema20"),
                    "ema50": snap.get("ema50"),
                    # Cảnh báo tin mà không nói tin gì thì người dùng phải tự đi mò.
                    "news": (ctx.get("news") or {}).get(rule["symbol"])
                    if rule["condition"] == "news_new"
                    else None,
                },
            })

    return triggered
