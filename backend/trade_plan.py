"""
Kế hoạch vào lệnh: mua bao nhiêu cổ phiếu, cắt lỗ ở đâu, mất tối đa bao nhiêu tiền.

Vì sao phần này quan trọng hơn việc chọn mã: tỷ lệ đúng của quy tắc chọn mã, đo trên
chính dữ liệu của từng mã trong app này, hầu hết chỉ ngang mức chọn bừa một phiên. Còn
số tiền mất mỗi lệnh thì quyết định được TRƯỚC khi mua và không phụ thuộc vào việc đoán
đúng hay sai. Đó là thứ duy nhất trong đầu tư mà người mới kiểm soát được hoàn toàn.

Quy tắc: mỗi lệnh chỉ được phép mất `risk_pct` phần trăm vốn nếu giá chạm cắt lỗ. Từ đó
suy ngược ra số cổ phiếu:

    số cổ phiếu = (vốn x % rủi ro) / (giá mua - giá cắt lỗ)

rồi làm tròn xuống bội số 100 (lô chẵn của HOSE). Giá cắt lỗ lấy mức thấp hơn giữa
"giá trừ 2 lần biên độ dao động ngày (ATR14)" và "đáy 20 phiên gần nhất", để không bị
văng khỏi lệnh chỉ vì một phiên rung lắc bình thường.

Đây là số học, không phải dự đoán. App không đặt lệnh và không phải cố vấn đầu tư.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Mỗi lệnh chỉ mất ngần này phần trăm vốn khi chạm cắt lỗ. 1% nghĩa là sai 10 lệnh liên
# tiếp vẫn chỉ mất 10% vốn — còn nguyên cơ hội làm lại. Đây là mức thường dùng cho
# người mới; chỉnh được ở giao diện.
DEFAULT_RISK_PCT = 1.0
MIN_RISK_PCT = 0.1
MAX_RISK_PCT = 5.0

# Một mã không được chiếm quá ngần này phần trăm vốn, kể cả khi cắt lỗ rất gần khiến
# công thức trên cho phép mua nhiều. Cắt lỗ gần không bảo vệ được khi giá nhảy gap.
MAX_POSITION_PCT = 20.0

# Lô chẵn HOSE.
LOT_SIZE = 100

# Bước giá cổ phiếu trên HOSE. Cắt lỗ 33.907 đ là con số không đặt lệnh được, nên mọi
# mức giá đưa ra đều phải rơi đúng bước giá của sàn.
TICKS = ((10_000.0, 10.0), (50_000.0, 50.0), (float("inf"), 100.0))

ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
SWING_LOOKBACK = 20

# Cắt lỗ xa hơn ngần này thì mã đang dao động quá mạnh với người mới: giữ nguyên phép
# tính nhưng cảnh báo.
WIDE_STOP_PCT = 15.0

# Phí giao dịch phổ biến ở công ty chứng khoán Việt Nam, và thuế bán 0,1% trên giá trị
# bán. Chỉnh ở đây nếu công ty của bạn thu khác.
FEE_PCT = 0.15
SELL_TAX_PCT = 0.1

# Mục tiêu chốt lời mặc định: lãi gấp đôi khoảng cách cắt lỗ.
TAKE_PROFIT_R = 2.0

RULE_TEXT = (
    f"Quy tắc: mỗi lệnh chỉ chấp nhận mất {DEFAULT_RISK_PCT:.0f}% vốn (chỉnh được). Cắt lỗ đặt "
    f"dưới mức thấp hơn giữa 'giá trừ {ATR_MULTIPLIER:.0f} lần ATR{ATR_PERIOD}' và 'đáy "
    f"{SWING_LOOKBACK} phiên'. Số cổ phiếu = tiền chấp nhận mất chia khoảng cách cắt lỗ, làm "
    f"tròn xuống lô {LOT_SIZE}. Một mã không quá {MAX_POSITION_PCT:.0f}% vốn."
)

DISCLAIMER = (
    "Đây là phép tính từ quy tắc cố định, không phải lời khuyên của chuyên gia tư vấn đầu tư "
    "có giấy phép. App không đặt lệnh. Cắt lỗ không bảo đảm: giá có thể nhảy qua mức đó khi "
    "mở cửa, và khoản lỗ thực tế lớn hơn con số ở đây."
)


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def tick_size(price: float) -> float:
    for limit, tick in TICKS:
        if price < limit:
            return tick
    return TICKS[-1][1]


def round_to_tick(price: float, mode: str = "down") -> float:
    """
    Kéo giá về đúng bước giá của sàn. Cắt lỗ làm tròn XUỐNG (xa hơn một chút, không bị
    sát hơn dự tính), mục tiêu chốt lời làm tròn LÊN.
    """
    tick = tick_size(price)
    n = price / tick
    return (int(n) + 1) * tick if mode == "up" and n != int(n) else int(n) * tick


def atr(df, period: int = ATR_PERIOD) -> Optional[float]:
    """
    Biên độ dao động thật trung bình (ATR): trung bình của max(cao-thấp, |cao-đóng hôm
    trước|, |thấp-đóng hôm trước|). Dùng giá đóng hôm trước nên phần nhảy gap qua đêm
    cũng được tính, khác với việc chỉ lấy cao trừ thấp trong phiên.
    """
    if df is None or len(df) < period + 1:
        return None
    try:
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        prev_close = df["Close"].astype(float).shift(1)
    except (KeyError, TypeError, ValueError):
        return None
    tr = (high - low).combine((high - prev_close).abs(), max).combine((low - prev_close).abs(), max)
    value = float(tr.tail(period).mean())
    return value if value == value and value > 0 else None


def stop_price(df, price: float) -> Optional[Dict[str, Any]]:
    """Giá cắt lỗ: thấp hơn giữa 'giá - 2 ATR' và 'đáy 20 phiên'."""
    atr_value = atr(df)
    candidates: List[Dict[str, Any]] = []
    if atr_value:
        candidates.append(
            {
                "price": price - ATR_MULTIPLIER * atr_value,
                "method": f"Giá trừ {ATR_MULTIPLIER:.0f} lần ATR{ATR_PERIOD}",
            }
        )
    # Chỉ dùng đáy khi thật sự có đủ SWING_LOOKBACK phiên: đáy của 5 phiên không phải
    # "đáy 20 phiên", và đặt cắt lỗ theo nó là đặt theo một con số không có thật.
    try:
        if df is not None and len(df) >= SWING_LOOKBACK:
            swing = float(df["Low"].astype(float).tail(SWING_LOOKBACK).min())
            if swing == swing and swing > 0:
                candidates.append({"price": swing, "method": f"Đáy {SWING_LOOKBACK} phiên gần nhất"})
    except (KeyError, TypeError, ValueError, AttributeError):
        pass

    candidates = [c for c in candidates if c["price"] > 0]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda c: c["price"])
    if chosen["price"] >= price:
        return None
    stop_value = round_to_tick(chosen["price"], "down")
    if stop_value <= 0 or stop_value >= price:
        return None
    return {
        "price": stop_value,
        "method": chosen["method"],
        "distance_pct": round((price - stop_value) / price * 100.0, 2),
        "atr": round(atr_value, 0) if atr_value else None,
        "atr_pct": round(atr_value / price * 100.0, 2) if atr_value else None,
    }


def build_plan(
    symbol: str,
    price: Optional[float],
    df,
    capital: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    verdict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Kế hoạch cho một lệnh mua. Không gọi mạng — xem plan_for.

    Luôn trả về cả khi không mua nổi một lô: người dùng cần biết vì sao, chứ không phải
    một ô trống.
    """
    symbol = (symbol or "").strip().upper()
    warnings: List[str] = []
    price = _num(price)
    capital = _num(capital) or 0.0
    # 0 là số hợp lệ nên không dùng "or": nó phải bị kẹp về mức tối thiểu, không âm thầm
    # nhảy về mặc định 1% — người dùng gõ 0 là đang muốn rủi ro nhỏ nhất có thể.
    risk_value = _num(risk_pct)
    risk_pct = min(max(DEFAULT_RISK_PCT if risk_value is None else risk_value, MIN_RISK_PCT), MAX_RISK_PCT)

    base: Dict[str, Any] = {
        "symbol": symbol,
        "price": price,
        "capital": capital,
        "risk_pct": risk_pct,
        "risk_budget": round(capital * risk_pct / 100.0, 0),
        "lot_size": LOT_SIZE,
        "max_position_pct": MAX_POSITION_PCT,
        "rule": RULE_TEXT,
        "disclaimer": DISCLAIMER,
    }

    if not price or price <= 0:
        return {**base, "available": False, "reason": "Chưa có giá để tính.", "warnings": warnings}
    if capital <= 0:
        return {
            **base,
            "available": False,
            "reason": "Nhập số vốn bạn dành cho cổ phiếu để tính số lượng nên mua.",
            "warnings": warnings,
        }

    stop = stop_price(df, price)
    if not stop:
        return {
            **base,
            "available": False,
            "reason": "Chưa đủ dữ liệu giá để đặt mức cắt lỗ.",
            "warnings": warnings,
        }

    risk_budget = capital * risk_pct / 100.0
    per_share_risk = price - stop["price"]
    raw_shares = risk_budget / per_share_risk
    shares = int(raw_shares // LOT_SIZE) * LOT_SIZE

    # Trần theo tỷ trọng: cắt lỗ gần khiến công thức cho phép mua rất nhiều, nhưng giá
    # nhảy gap qua đêm thì mức cắt lỗ đó không giữ được.
    max_value = capital * MAX_POSITION_PCT / 100.0
    capped = False
    if shares * price > max_value:
        shares = int((max_value / price) // LOT_SIZE) * LOT_SIZE
        capped = True
        warnings.append(
            f"Đã giảm số lượng để một mã không vượt {MAX_POSITION_PCT:.0f}% vốn."
        )

    if stop["distance_pct"] > WIDE_STOP_PCT:
        warnings.append(
            f"Cắt lỗ cách giá {stop['distance_pct']:.1f}%, tức mã này đang dao động mạnh. "
            f"Mua ít hơn hoặc chọn mã khác."
        )

    if shares < LOT_SIZE:
        return {
            **base,
            "available": False,
            "stop": stop,
            "reason": (
                f"Với {risk_pct:.1f}% vốn và cắt lỗ cách {stop['distance_pct']:.1f}%, số vốn này "
                f"chưa mua nổi một lô {LOT_SIZE} cổ phiếu ({price * LOT_SIZE:,.0f} đ). Cần thêm vốn, "
                f"chọn mã giá thấp hơn, hoặc chấp nhận mức rủi ro cao hơn."
            ).replace(",", "."),
            "warnings": warnings,
        }

    order_value = shares * price
    buy_fee = order_value * FEE_PCT / 100.0
    stop_value = shares * stop["price"]
    sell_fee = stop_value * (FEE_PCT + SELL_TAX_PCT) / 100.0
    loss_if_stopped = order_value - stop_value + buy_fee + sell_fee
    target = round_to_tick(price + per_share_risk * TAKE_PROFIT_R, "up")
    gain_if_target = shares * (target - price) - buy_fee - shares * target * (FEE_PCT + SELL_TAX_PCT) / 100.0

    if verdict and verdict.get("verdict") != "buy_consider":
        warnings.append(
            f"Kết luận hiện tại của mã này là \"{verdict.get('label')}\", không phải "
            f"\"Có thể cân nhắc mua\"."
        )

    return {
        **base,
        "available": True,
        "shares": shares,
        "stop": stop,
        "target": {
            "price": target,
            "r_multiple": TAKE_PROFIT_R,
            "gain": round(gain_if_target, 0),
            "gain_pct_of_capital": round(gain_if_target / capital * 100.0, 2),
        },
        "order_value": round(order_value, 0),
        "capital_pct": round(order_value / capital * 100.0, 2),
        "capped": capped,
        "fees": {"buy": round(buy_fee, 0), "sell_if_stopped": round(sell_fee, 0), "fee_pct": FEE_PCT, "tax_pct": SELL_TAX_PCT},
        "loss_if_stopped": round(loss_if_stopped, 0),
        "loss_pct_of_capital": round(loss_if_stopped / capital * 100.0, 2),
        "warnings": warnings,
    }


def verdict_from_scan(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Kết luận của mã, lấy từ lượt quét gần nhất đã lưu.

    Không gọi verdict_engine ở đây: tính lại một mã mất khoảng 9 giây vì phải tải 2 năm
    giá và chỉ số cơ bản, trong khi lượt quét đã có sẵn câu trả lời. Đọc từ lượt quét
    còn bảo đảm thẻ này và danh sách "Tìm mã" không nói hai điều khác nhau.
    """
    try:
        from storage_service import get_verdict_scan

        scan = get_verdict_scan() or {}
    except Exception:
        return None
    symbol = (symbol or "").strip().upper()
    row = next((r for r in scan.get("results") or [] if r.get("symbol") == symbol), None)
    if not row:
        return None
    return {
        "verdict": row.get("verdict"),
        "label": row.get("label"),
        "scan_date": scan.get("scan_date") or scan.get("date"),
    }


def plan_for(symbol: str, capital: float, risk_pct: float = DEFAULT_RISK_PCT) -> Dict[str, Any]:
    """Lấy giá thật rồi lập kế hoạch. Tách khỏi build_plan để test không gọi mạng."""
    from stock_service import fetch_stock_data

    symbol = (symbol or "").strip().upper()
    df, _ = fetch_stock_data(symbol, period="6mo", interval="1d")
    if df is None or df.empty:
        raise RuntimeError(f"Không lấy được dữ liệu giá của {symbol}.")

    price = _num(df["Close"].iloc[-1])
    verdict = verdict_from_scan(symbol)
    plan = build_plan(symbol, price, df, capital, risk_pct, verdict)
    if verdict:
        plan["verdict"] = verdict
    return plan
