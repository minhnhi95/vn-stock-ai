"""
Bộ lọc an toàn cho nhà đầu tư mới.

Module này KHÔNG tìm cổ phiếu tốt. Nó chặn cổ phiếu nguy hiểm — một việc khiêm
tốn hơn nhưng làm được thật, và đó mới là thứ giữ tiền cho người mới. Phần lớn
tiền mất của nhà đầu tư F0 không đến từ việc bỏ lỡ mã tăng, mà từ việc mua phải
mã không thoát được hàng, mã penny bị làm giá, hoặc doanh nghiệp đang lỗ.

Mọi tiêu chí đều là NGƯỠNG SỐ CỤ THỂ, công khai trong code, và kết quả luôn kèm
con số thực tế để người dùng tự đối chiếu. Cố ý không dùng AI và không chấm điểm
tổng: một con số "78/100" không nói cho người mới biết họ đang chịu rủi ro gì.

Ngưỡng chọn theo đặc thù thị trường VN, không phải copy từ thị trường Mỹ.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# --- Ngưỡng, đặt ở đầu file để dễ soi và dễ chỉnh ---

# Giá trị khớp lệnh trung bình mỗi phiên. Dưới mức này, lệnh vài chục triệu đã
# đủ làm lệch giá, và lúc cần bán gấp thì không có người mua.
MIN_DAILY_VALUE_VND = 5_000_000_000  # 5 tỷ/phiên

# Cổ phiếu dưới 10.000đ ở VN phần lớn là doanh nghiệp nhỏ, biến động rất mạnh và
# là nhóm hay bị làm giá nhất.
MIN_PRICE_VND = 10_000

# Nợ vay / vốn chủ sở hữu. Trên 2 lần là đòn bẩy cao — lãi suất tăng hoặc doanh
# thu hụt là áp lực dồn ngay vào lợi nhuận.
MAX_DEBT_TO_EQUITY = 2.0

# ROE âm = đang lỗ trên vốn chủ.
MIN_ROE_PCT = 0.0

# Biên độ dao động ngày trung bình (high-low)/close. Trên 5% là quá nóng với
# người mới — dễ bị "quét" stop-loss chỉ trong một phiên.
MAX_DAILY_SWING_PCT = 5.0


def _pct_change_series(df) -> Optional[float]:
    """Biên độ dao động ngày trung bình 20 phiên gần nhất, tính theo %."""
    try:
        recent = df.tail(20)
        swing = (recent["High"] - recent["Low"]) / recent["Close"] * 100
        value = float(swing.mean())
        return value if value == value else None  # loại NaN
    except Exception:
        return None


def _avg_daily_value(df) -> Optional[float]:
    """Giá trị khớp lệnh trung bình mỗi phiên (VND), 20 phiên gần nhất."""
    try:
        recent = df.tail(20)
        value = float((recent["Close"] * recent["Volume"]).mean())
        return value if value == value else None
    except Exception:
        return None


def _check(
    key: str,
    label: str,
    passed: Optional[bool],
    value: Optional[float],
    threshold: str,
    explain_fail: str,
    display: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Một tiêu chí.

    `passed=None` nghĩa là KHÔNG ĐỦ DỮ LIỆU để kết luận — khác hẳn với "đạt".
    Người mới cần phân biệt "an toàn" với "chưa biết".
    """
    return {
        "key": key,
        "label": label,
        "status": "unknown" if passed is None else ("pass" if passed else "fail"),
        "value": value,
        "display": display,
        "threshold": threshold,
        "explain": explain_fail,
    }


def screen_symbol(
    symbol: str,
    df=None,
    fundamentals: Optional[Dict[str, Any]] = None,
    vn100: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Chấm một mã theo toàn bộ tiêu chí an toàn.

    Nhận sẵn `df` và `fundamentals` để caller quét nhiều mã mà không fetch lại —
    vnstock chỉ cho 20 request/phút.
    """
    symbol = (symbol or "").strip().upper()
    checks: List[Dict[str, Any]] = []

    # --- Thanh khoản ---
    avg_value = _avg_daily_value(df) if df is not None else None
    checks.append(
        _check(
            "liquidity",
            "Thanh khoản",
            None if avg_value is None else avg_value >= MIN_DAILY_VALUE_VND,
            avg_value,
            f"≥ {MIN_DAILY_VALUE_VND / 1e9:.0f} tỷ/phiên",
            "Giao dịch quá ít. Lúc bạn muốn bán có thể không có người mua, hoặc phải "
            "bán rẻ hơn nhiều so với giá trên bảng.",
            display=f"{avg_value / 1e9:.2f} tỷ/phiên" if avg_value else None,
        )
    )

    # --- Giá penny ---
    price = None
    if df is not None and not df.empty:
        try:
            price = float(df["Close"].iloc[-1])
        except Exception:
            price = None
    checks.append(
        _check(
            "penny",
            "Thị giá",
            None if price is None else price >= MIN_PRICE_VND,
            price,
            f"≥ {MIN_PRICE_VND:,} đ",
            "Cổ phiếu thị giá thấp biến động rất mạnh và là nhóm hay bị làm giá nhất. "
            "Người mới rất khó phân biệt tăng thật với tăng do bị đẩy.",
            display=f"{price:,.0f} đ" if price else None,
        )
    )

    # --- Đòn bẩy ---
    debt = (fundamentals or {}).get("debt_to_equity")
    checks.append(
        _check(
            "leverage",
            "Nợ vay / Vốn chủ",
            None if debt is None else debt <= MAX_DEBT_TO_EQUITY,
            debt,
            f"≤ {MAX_DEBT_TO_EQUITY:.1f} lần",
            "Doanh nghiệp vay nhiều so với vốn tự có. Khi lãi suất tăng hoặc doanh thu "
            "hụt, áp lực trả nợ dồn thẳng vào lợi nhuận.",
            display=f"{debt:.2f} lần" if debt is not None else None,
        )
    )

    # --- Sinh lời ---
    roe = (fundamentals or {}).get("roe")
    checks.append(
        _check(
            "profitability",
            "ROE (sinh lời trên vốn)",
            None if roe is None else roe > MIN_ROE_PCT,
            roe,
            "> 0%",
            "Doanh nghiệp đang lỗ trên vốn chủ sở hữu. Giá có thể vẫn tăng vì kỳ vọng, "
            "nhưng đó là đặt cược vào tương lai chứ không phải mua một thứ đang sinh lời.",
            display=f"{roe:.2f}%" if roe is not None else None,
        )
    )

    # --- Độ nóng ---
    swing = _pct_change_series(df) if df is not None else None
    checks.append(
        _check(
            "volatility",
            "Biên độ dao động ngày",
            None if swing is None else swing <= MAX_DAILY_SWING_PCT,
            swing,
            f"≤ {MAX_DAILY_SWING_PCT:.0f}%/phiên",
            "Giá dao động rất mạnh trong ngày. Người mới dễ hoảng bán đúng đáy phiên "
            "rồi nhìn giá hồi lại ngay sau đó.",
            display=f"{swing:.2f}%/phiên" if swing is not None else None,
        )
    )

    # --- Mức độ được theo dõi ---
    in_vn100 = None if vn100 is None else (symbol in vn100)
    checks.append(
        _check(
            "coverage",
            "Thuộc rổ VN100",
            in_vn100,
            None,
            "nằm trong VN100",
            "Ngoài rổ VN100 nên ít công ty chứng khoán phân tích, thông tin công bố "
            "thưa hơn. Không có nghĩa là xấu, nhưng bạn sẽ khó tìm dữ liệu để tự kiểm chứng.",
            display="Có" if in_vn100 else ("Không" if in_vn100 is False else None),
        )
    )

    failed = [c for c in checks if c["status"] == "fail"]
    unknown = [c for c in checks if c["status"] == "unknown"]

    if failed:
        verdict = "caution"
        headline = f"{len(failed)} điểm cần cân nhắc trước khi mua"
    elif unknown:
        verdict = "incomplete"
        headline = f"Đạt các tiêu chí kiểm tra được, còn {len(unknown)} mục thiếu dữ liệu"
    else:
        verdict = "basic_ok"
        headline = "Qua toàn bộ tiêu chí an toàn cơ bản"

    return {
        "symbol": symbol,
        "verdict": verdict,
        "headline": headline,
        "checks": checks,
        "failed_count": len(failed),
        "unknown_count": len(unknown),
        "passed_count": len(checks) - len(failed) - len(unknown),
        # Nói rõ giới hạn ngay trong payload để UI không quên hiển thị.
        "disclaimer": (
            "Qua bộ lọc KHÔNG có nghĩa là nên mua — chỉ có nghĩa là không dính các "
            "rủi ro cơ bản mà bộ lọc này kiểm tra được."
        ),
    }


def screen_many(symbols: List[str], max_symbols: int = 12) -> Dict[str, Any]:
    """
    Quét nhiều mã. Giới hạn số lượng vì mỗi mã tốn 2 request vnstock
    (giá + chỉ số cơ bản) trên hạn mức 20 request/phút.
    """
    from market_service import fetch_fundamentals
    from stock_service import fetch_stock_data

    try:
        from sector_service import get_vn100_symbols

        vn100 = set(get_vn100_symbols())
    except Exception:
        from market_universe import vn100_fallback

        vn100 = set(vn100_fallback())

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for symbol in symbols[:max_symbols]:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            continue
        df = None
        fundamentals = None
        try:
            df, _ = fetch_stock_data(symbol, period="3mo", interval="1d")
        except Exception as e:
            errors.append({"symbol": symbol, "error": f"giá: {str(e)[:80]}"})
        try:
            fundamentals = fetch_fundamentals(symbol)
            if not fundamentals.get("available"):
                fundamentals = None
        except Exception as e:
            errors.append({"symbol": symbol, "error": f"cơ bản: {str(e)[:80]}"})

        results.append(screen_symbol(symbol, df=df, fundamentals=fundamentals, vn100=vn100))

    # Mã có nhiều điểm cần cân nhắc lên đầu — đó là thứ người dùng cần thấy trước.
    results.sort(key=lambda r: (-r["failed_count"], r["symbol"]))
    return {
        "results": results,
        "errors": errors,
        "thresholds": {
            "min_daily_value_vnd": MIN_DAILY_VALUE_VND,
            "min_price_vnd": MIN_PRICE_VND,
            "max_debt_to_equity": MAX_DEBT_TO_EQUITY,
            "min_roe_pct": MIN_ROE_PCT,
            "max_daily_swing_pct": MAX_DAILY_SWING_PCT,
        },
    }
