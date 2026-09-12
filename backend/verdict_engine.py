"""
Kết luận cho một mã: "Có thể cân nhắc mua", "Chờ thêm" hoặc "Không nên mua".

Người dùng muốn một kết luận rõ ràng để dựa vào ra quyết định. Kết luận ở đây đến từ
quy tắc Python công khai, không phải từ AI:

- mỗi tiêu chí có ngưỡng ghi ngay đầu file và hiện ra giao diện kèm con số thật;
- kết luận nào cũng kèm tỷ lệ đúng trong quá khứ của chính mã đó, để biết nên tin
  tới đâu. Một mô hình ngôn ngữ nói "MUA MẠNH" thì không kiểm chứng được; một quy
  tắc thì đo được.

Không có quy tắc nào đoán đúng giá mọi lần. Đây là một đầu vào cho quyết định, không
phải lời khuyên của chuyên gia tư vấn đầu tư có giấy phép.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ---------- Ngưỡng, đặt ở đầu file để dễ soi và dễ chỉnh ----------

# RSI trên mức này nghĩa là giá vừa tăng rất nhanh; mua lúc này dễ mua đúng đỉnh ngắn hạn.
RSI_OVERHEATED = 70.0

# P/E cao hơn trung vị ngành quá mức này thì coi là đắt so với doanh nghiệp cùng ngành.
PE_PREMIUM_TOLERANCE = 1.10

# ROE tối thiểu khi không có trung vị ngành để so.
MIN_GOOD_ROE_PCT = 10.0

# Đo giá sau bao nhiêu phiên khi kiểm tra quá khứ — khoảng một tháng giao dịch.
FORWARD_SESSIONS = 20

# Ít hơn ngần này phiên tương tự thì không đưa tỷ lệ: con số từ vài phiên chỉ là nhiễu.
MIN_HISTORY_SAMPLES = 20

# Tỷ lệ đúng phải hơn / kém mốc "chọn bừa một phiên" ít nhất ngần này mới coi là khác biệt.
EDGE_MEANINGFUL = 0.05

# Trượt một trong các tiêu chí an toàn này là loại luôn: khó bán ra, dễ bị làm giá, đang
# lỗ, hoặc vay quá nhiều. Hai tiêu chí còn lại của bộ lọc (biên độ dao động, ngoài
# VN100) chỉ là điểm trừ, không đủ để loại.
HARD_SAFETY_KEYS = ("liquidity", "penny", "profitability", "leverage")

LABELS = {
    "buy_consider": "Có thể cân nhắc mua",
    "wait": "Chờ thêm",
    "avoid": "Không nên mua",
}

RULE_TEXT = (
    "Quy tắc: Không nên mua khi trượt một tiêu chí an toàn (thanh khoản, thị giá, ROE, "
    "nợ/vốn chủ), hoặc khi giá dưới EMA200 và EMA50 cũng dưới EMA200. Có thể cân nhắc "
    "mua khi qua an toàn, giá trên EMA200, EMA50 trên EMA200, RSI dưới "
    f"{RSI_OVERHEATED:.0f}, và đạt ít nhất 2/3 tiêu chí nền tảng. Còn lại: Chờ thêm."
)

DISCLAIMER = (
    "Kết luận tính từ quy tắc cố định, không phải lời khuyên của chuyên gia tư vấn đầu "
    "tư có giấy phép. Quy tắc có thể sai; tỷ lệ quá khứ cho biết nó từng đúng tới đâu "
    "với chính mã này, nhưng không bảo đảm cho lần tới."
)


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v else v  # loại NaN


def _vnd(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") + " đ"


def technical_state(
    close: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float],
    rsi: Optional[float],
) -> Dict[str, Optional[bool]]:
    """Ba câu hỏi có/không về giá. None nghĩa là thiếu dữ liệu để trả lời."""
    return {
        "above_ema200": None if close is None or ema200 is None else close > ema200,
        "ema50_above_ema200": None if ema50 is None or ema200 is None else ema50 > ema200,
        "not_overheated": None if rsi is None else rsi < RSI_OVERHEATED,
    }


def history_check(df, state: Dict[str, Optional[bool]]) -> Dict[str, Any]:
    """
    Những phiên trước có cùng trạng thái kỹ thuật như hôm nay: FORWARD_SESSIONS phiên
    sau đó, giá cao hơn ở bao nhiêu phần trăm số lần.

    Luôn trả kèm mốc so sánh là MỌI phiên. Nếu mã này lên giá 60% số lần bất kể trạng
    thái, thì một quy tắc "đúng 62%" gần như không thêm được gì — người dùng cần thấy
    điều đó. Chỉ so phần kỹ thuật, vì không có lịch sử chỉ số cơ bản theo từng phiên.
    """
    if df is None or any(v is None for v in state.values()):
        return {"available": False, "reason": "Chưa đủ dữ liệu chỉ báo để so với quá khứ."}
    try:
        close = df["Close"].astype(float)
        ema50 = df["EMA50"].astype(float)
        ema200 = df["EMA200"].astype(float)
        rsi = df["RSI"].astype(float)
    except (KeyError, TypeError, ValueError):
        return {"available": False, "reason": "Thiếu cột chỉ báo trong dữ liệu giá."}

    forward = close.shift(-FORWARD_SESSIONS) / close - 1.0
    valid = ema50.notna() & ema200.notna() & rsi.notna() & forward.notna()
    same = (
        valid
        & ((close > ema200) == state["above_ema200"])
        & ((ema50 > ema200) == state["ema50_above_ema200"])
        & ((rsi < RSI_OVERHEATED) == state["not_overheated"])
    )
    base = forward[valid]
    sample = forward[same]
    if len(sample) < MIN_HISTORY_SAMPLES:
        return {
            "available": False,
            "samples": int(len(sample)),
            "reason": (
                f"Chỉ có {len(sample)} phiên trước đây ở trạng thái giống hôm nay "
                f"(cần ít nhất {MIN_HISTORY_SAMPLES}) — chưa đủ để đo."
            ),
        }
    return {
        "available": True,
        "forward_sessions": FORWARD_SESSIONS,
        "samples": int(len(sample)),
        "up_ratio": round(float((sample > 0).mean()), 4),
        "median_return": round(float(sample.median()), 4),
        "baseline_samples": int(len(base)),
        "baseline_up_ratio": round(float((base > 0).mean()), 4),
        "baseline_median_return": round(float(base.median()), 4),
    }


def _judge_history(verdict: str, history: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gắn tỷ lệ quá khứ vào chính kết luận hôm nay, và viết sẵn câu tóm tắt.

    "Đúng" nghĩa là giá đi theo hướng kết luận ngụ ý: "có thể cân nhắc mua" đúng khi
    giá cao hơn sau FORWARD_SESSIONS phiên, "không nên mua" đúng khi giá thấp hơn.
    "Chờ thêm" không ngụ ý hướng nào nên chỉ mô tả.

    Luôn so với mốc chọn bừa một phiên bất kỳ. Nếu quy tắc kém hơn mốc đó với mã này,
    câu tóm tắt nói thẳng ra — người dùng dựa vào kết luận để bỏ tiền, không được để họ
    tự suy ra từ hai con số.
    """
    if not history.get("available"):
        return history
    up, base_up = history["up_ratio"], history["baseline_up_ratio"]
    lead = (
        f"{history['samples']} phiên trước đây ở trạng thái kỹ thuật giống hôm nay: "
        f"{history['forward_sessions']} phiên sau, "
    )
    if verdict == "wait":
        summary = lead + f"giá cao hơn ở {up:.0%} số lần (chọn bừa một phiên bất kỳ: {base_up:.0%})."
        return {**history, "hit_ratio": None, "baseline_hit_ratio": None, "edge": None, "summary": summary}

    if verdict == "buy_consider":
        hit, base_hit, meaning = up, base_up, "giá cao hơn"
    else:
        hit, base_hit, meaning = 1.0 - up, 1.0 - base_up, "giá thấp hơn"
    diff = hit - base_hit
    if diff >= EDGE_MEANINGFUL:
        edge, tail = "better", "tốt hơn mốc chung, trạng thái này từng có ý nghĩa với mã này."
    elif diff <= -EDGE_MEANINGFUL:
        edge, tail = "worse", (
            "kém hơn cả chọn bừa. Với mã này, quy tắc từng đoán hướng giá sai nhiều hơn "
            "mức ngẫu nhiên, nên tin kết luận này ít hơn."
        )
    else:
        edge, tail = "same", "gần như bằng mốc chung, trạng thái này không nói thêm được nhiều với mã này."
    summary = (
        lead + f"{meaning} ở {hit:.0%} số lần, so với {base_hit:.0%} nếu chọn bừa một phiên "
        f"bất kỳ: {tail}"
    )
    return {
        **history,
        "hit_ratio": round(hit, 4),
        "baseline_hit_ratio": round(base_hit, 4),
        "edge": edge,
        "summary": summary,
    }


def _check(key, label, passed, display, threshold, group, details=None) -> Dict[str, Any]:
    row = {
        "key": key,
        "label": label,
        "group": group,
        "status": "unknown" if passed is None else ("pass" if passed else "fail"),
        "display": display,
        "threshold": threshold,
    }
    if details:
        row["details"] = details
    return row


def build_verdict(
    symbol: str,
    df,
    fundamentals: Optional[Dict[str, Any]] = None,
    safety: Optional[Dict[str, Any]] = None,
    sector_name: Optional[str] = None,
    sector_stats: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Tính kết luận từ dữ liệu đã có sẵn. Không gọi mạng — xem verdict_for.

    `safety` là kết quả của safety_screen.screen_symbol; None nghĩa là chưa kiểm tra
    được, và khi đó không bao giờ ra "Có thể cân nhắc mua".
    """
    symbol = (symbol or "").strip().upper()
    f = fundamentals or {}
    stats = sector_stats or {}
    checks: List[Dict[str, Any]] = []

    # --- 1. An toàn ---
    safety_rows = {c.get("key"): c for c in (safety or {}).get("checks", [])}
    hard_fail = [
        safety_rows[k] for k in HARD_SAFETY_KEYS if safety_rows.get(k, {}).get("status") == "fail"
    ]
    if safety is None:
        safety_passed, safety_display = None, "Chưa kiểm tra được"
    else:
        safety_passed = not hard_fail
        safety_display = (
            "Đạt" if not hard_fail
            else "Trượt: " + ", ".join(c.get("label") or c.get("key") for c in hard_fail)
        )
    # Kèm từng tiêu chí an toàn với con số của nó: thẻ kết luận là chỗ duy nhất người
    # dùng xem trước khi mua, không nên bắt họ mở thêm một bảng khác để biết vì sao đạt.
    safety_details = [
        {
            "key": c.get("key"),
            "label": c.get("label"),
            "status": c.get("status"),
            "display": c.get("display"),
            "threshold": c.get("threshold"),
            "hard": c.get("key") in HARD_SAFETY_KEYS,
        }
        for c in (safety or {}).get("checks", [])
    ]
    checks.append(_check(
        "safety", "Bộ lọc an toàn", safety_passed, safety_display,
        "Không trượt: thanh khoản, thị giá, ROE, nợ/vốn chủ", "an_toan",
        details=safety_details,
    ))

    # --- 2. Xu hướng giá ---
    last = df.iloc[-1] if df is not None and len(df) else None
    close = _num(last.get("Close")) if last is not None else None
    ema50 = _num(last.get("EMA50")) if last is not None else None
    ema200 = _num(last.get("EMA200")) if last is not None else None
    rsi = _num(last.get("RSI")) if last is not None else None
    state = technical_state(close, ema50, ema200, rsi)

    checks.append(_check(
        "trend_long", "Giá trên đường EMA200 (xu hướng dài hạn)", state["above_ema200"],
        f"{_vnd(close)} so với {_vnd(ema200)}" if close is not None and ema200 is not None else None,
        "Giá > EMA200", "xu_huong",
    ))
    checks.append(_check(
        "trend_mid", "EMA50 trên EMA200 (xu hướng trung hạn)", state["ema50_above_ema200"],
        f"{_vnd(ema50)} so với {_vnd(ema200)}" if ema50 is not None and ema200 is not None else None,
        "EMA50 > EMA200", "xu_huong",
    ))
    checks.append(_check(
        "not_hot", "RSI chưa quá nóng", state["not_overheated"],
        f"RSI {rsi:.0f}" if rsi is not None else None,
        f"RSI < {RSI_OVERHEATED:.0f}", "xu_huong",
    ))

    # --- 3. Nền tảng doanh nghiệp ---
    pe = _num(f.get("pe"))
    pe_med = _num((stats.get("pe") or {}).get("median"))
    # P/E âm = đang lỗ: không có "rẻ" hay "đắt" để so, nên để thiếu dữ liệu.
    pe_pass = None if pe is None or pe <= 0 or pe_med is None else pe <= pe_med * PE_PREMIUM_TOLERANCE
    pe_display = None
    if pe is not None:
        pe_display = f"P/E {pe:.1f}" + (f" — ngành {pe_med:.1f}" if pe_med is not None else "")
    checks.append(_check(
        "valuation", "Định giá không đắt hơn ngành", pe_pass, pe_display,
        f"P/E ≤ trung vị ngành +{(PE_PREMIUM_TOLERANCE - 1) * 100:.0f}%", "nen_tang",
    ))

    roe = _num(f.get("roe"))
    roe_med = _num((stats.get("roe") or {}).get("median"))
    roe_bar = roe_med if roe_med is not None else MIN_GOOD_ROE_PCT
    checks.append(_check(
        "quality", "Sinh lời trên vốn (ROE) tốt", None if roe is None else roe >= roe_bar,
        None if roe is None else f"ROE {roe:.1f}%",
        f"ROE ≥ {roe_bar:.1f}%" + (" (trung vị ngành)" if roe_med is not None else ""),
        "nen_tang",
    ))

    growth = _num(f.get("earnings_growth"))
    checks.append(_check(
        "growth", "Lợi nhuận đang tăng", None if growth is None else growth > 0,
        None if growth is None else f"{growth:+.1f}% so với cùng kỳ",
        "> 0%", "nen_tang",
    ))

    # --- 4. Kết luận ---
    fundamentals_passed = sum(
        1 for c in checks if c["group"] == "nen_tang" and c["status"] == "pass"
    )
    uptrend = state["above_ema200"] is True and state["ema50_above_ema200"] is True
    downtrend = state["above_ema200"] is False and state["ema50_above_ema200"] is False

    if hard_fail:
        verdict = "avoid"
        headline = "Trượt tiêu chí an toàn: " + ", ".join(
            c.get("label") or c.get("key") for c in hard_fail
        ) + "."
    elif downtrend:
        verdict = "avoid"
        headline = "Giá đang trong xu hướng giảm cả trung hạn lẫn dài hạn."
    elif safety_passed and uptrend and state["not_overheated"] is True and fundamentals_passed >= 2:
        verdict = "buy_consider"
        headline = "Xu hướng tăng, chưa quá nóng, nền tảng khá so với ngành."
    else:
        verdict = "wait"
        reasons = []
        if safety_passed is None:
            reasons.append("chưa kiểm tra được an toàn")
        if not uptrend:
            reasons.append("xu hướng chưa rõ")
        if state["not_overheated"] is False:
            reasons.append(f"đang tăng quá nóng (RSI {rsi:.0f})")
        if fundamentals_passed < 2:
            reasons.append("nền tảng chưa đủ tốt so với ngành")
        headline = ("Chưa đủ điều kiện: " + ", ".join(reasons) + ".") if reasons else "Chưa đủ điều kiện."

    return {
        "symbol": symbol,
        "price": close,
        "verdict": verdict,
        "label": LABELS[verdict],
        "headline": headline,
        "checks": checks,
        "history": _judge_history(verdict, history_check(df, state)),
        "sector": sector_name,
        "rule": RULE_TEXT,
        "disclaimer": DISCLAIMER,
    }


def resolve_sector(
    symbol: str, bench: Dict[str, Any], sector_of: Optional[Dict[str, str]] = None
) -> Tuple[Optional[str], Optional[Dict[str, Dict[str, Any]]]]:
    """
    Ngành để so trung vị: trước hết theo bảng trung vị, rồi theo ngành ICB của mã.

    Bảng trung vị chỉ liệt kê mã đã dùng để tính (top thanh khoản mỗi ngành + VN100).
    Một mã nhỏ ngoài danh sách đó vẫn thuộc một ngành có trung vị — không so với ngành
    thì tiêu chí định giá luôn "thiếu dữ liệu", và mã đó gần như không bao giờ đủ 2/3
    tiêu chí nền tảng dù doanh nghiệp tốt.
    """
    sectors = bench.get("sectors") or {}
    sector = (bench.get("symbol_sector") or {}).get(symbol)
    if sector:
        return sector, (sectors.get(sector) or {}).get("metrics")
    icb = (sector_of or {}).get(symbol)
    if icb and icb in sectors:
        return icb, sectors[icb].get("metrics")
    return icb, None


def _icb_sector_map() -> Dict[str, str]:
    try:
        from sector_service import get_industries

        return {s: i["name"] for i in get_industries() for s in (i.get("symbols") or [])}
    except Exception:
        return {}


def verdict_for(
    symbol: str,
    vn100: Optional[set] = None,
    sector_of: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Lấy dữ liệu thật rồi tính kết luận. Tách khỏi build_verdict để test không gọi mạng.

    `vn100` và `sector_of` (mã -> ngành ICB) truyền sẵn khi quét nhiều mã
    (jobs/verdict_scan.py) để khỏi lấy lại mỗi mã.
    """
    from market_service import fetch_fundamentals
    from metric_explainer import load_benchmarks
    from safety_screen import screen_symbol
    from stock_service import fetch_stock_data

    symbol = (symbol or "").strip().upper()
    # 2 năm: đủ dài để đo tỷ lệ quá khứ; EMA200 đã được "mồi" sẵn trong stock_service.
    df, _ = fetch_stock_data(symbol, period="2y", interval="1d")
    if df is None or df.empty:
        # Không có giá thì không có kết luận. Trả "Chờ thêm" lúc này sẽ trông như một
        # kết luận thật, trong khi thực ra là lỗi mạng hoặc dính hạn mức vnstock.
        raise RuntimeError(f"Không lấy được dữ liệu giá của {symbol}.")

    fundamentals = fetch_fundamentals(symbol)
    if not fundamentals.get("available"):
        fundamentals = None

    if vn100 is None:
        try:
            from sector_service import get_vn100_symbols

            vn100 = set(get_vn100_symbols())
        except Exception:
            from market_universe import vn100_fallback

            vn100 = set(vn100_fallback())

    safety = screen_symbol(symbol, df=df, fundamentals=fundamentals, vn100=vn100)

    bench = load_benchmarks()
    if sector_of is None and symbol not in (bench.get("symbol_sector") or {}):
        sector_of = _icb_sector_map()
    sector, stats = resolve_sector(symbol, bench, sector_of)
    result = build_verdict(symbol, df, fundamentals, safety, sector, stats)
    # Thiếu chỉ số cơ bản thì kết luận không bao giờ lên "có thể mua" (cần 2/3 tiêu chí
    # nền tảng), nhưng người dùng cần biết đó là do thiếu dữ liệu chứ không phải do
    # doanh nghiệp yếu.
    result["data_gaps"] = [] if fundamentals else [
        "Không lấy được chỉ số cơ bản, phần nền tảng doanh nghiệp để trống."
    ]
    return result
