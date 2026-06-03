import google.generativeai as genai
import json
import os

# Model có thể override qua env var để dễ thử nghiệm/giảm chi phí.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _build_analysis_prompt(symbol, current_price, indicators, history_summary, intraday_summary, fundamentals_summary="", news_summary=""):
    def fmt(key, prec):
        v = indicators.get(key)
        return f"{v:.{prec}f}" if isinstance(v, (int, float)) else "N/A"

    fundamentals_block = fundamentals_summary or "Dữ liệu cơ bản: Không khả dụng."
    news_block = news_summary or "Tin tức: Không có tin nổi bật."

    return f"""
    Bạn là Chuyên gia phân tích kỹ thuật + cơ bản + bối cảnh tin tức (technical + fundamental + sentiment) cấp cao tại thị trường chứng khoán Việt Nam.
    Hãy kết hợp CẢ BA khía cạnh để đánh giá cổ phiếu {symbol}.

    [1] DỮ LIỆU KỸ THUẬT
    - Giá đóng cửa hiện tại: {current_price}
    - RSI (14): {fmt('rsi', 2)}
    - MACD Line: {fmt('macd', 4)}
    - MACD Signal: {fmt('signal', 4)}
    - MACD Histogram: {fmt('hist', 4)}
    - EMA20: {fmt('ema20', 2)}
    - EMA50: {fmt('ema50', 2)}
    - EMA200: {fmt('ema200', 2)}

    Biến động nến gần đây:
    {history_summary}

    Khớp lệnh dòng tiền nội ngày (0-delay):
    {intraday_summary}

    [2] DỮ LIỆU CƠ BẢN
    {fundamentals_block}

    [3] TIN TỨC & BỐI CẢNH
    {news_block}

    HƯỚNG DẪN:
    - Kỹ thuật xác định ĐIỂM VÀO/RA ngắn hạn.
    - Cơ bản xác định CHẤT LƯỢNG doanh nghiệp & định giá. P/E < trung bình ngành + ROE > 15% + tăng trưởng LNST dương = nền tảng vững.
    - Tin tức xác định CATALYST/RỦI RO ngắn hạn. Tin tích cực mạnh + xu hướng kỹ thuật tốt → tăng confidence. Tin tiêu cực (điều tra, thoái vốn, kết quả kém) → cẩn trọng cho dù chỉ báo kỹ thuật đẹp.
    - Nếu 3 khía cạnh XUNG ĐỘT: giảm confidence, nêu rõ mâu thuẫn trong summary.
    - target_price và stop_loss phải hợp lý so với biến động lịch sử (không đặt mục tiêu cách giá hiện tại > 30%).
    - Tuyệt đối KHÔNG bịa số liệu — nếu khía cạnh nào thiếu dữ liệu, ghi "Không có dữ liệu".

    Xuất ra duy nhất một JSON theo cấu trúc dưới, KHÔNG kèm markdown:
    {{
        "recommendation": "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL",
        "confidence": 0-100,
        "target_price": number,
        "stop_loss": number,
        "summary": "Tổng hợp ngắn gọn 3 khía cạnh + dòng tiền (2-3 câu)",
        "technical_analysis": "Phân tích RSI, MACD, EMA (3-4 câu)",
        "trend_analysis": "Xu hướng ngắn và trung hạn (2-3 câu)",
        "fundamental_analysis": "Nhận xét P/E, P/B, ROE, tăng trưởng (2-3 câu)",
        "news_sentiment": "Tổng hợp tâm lý từ tin tức gần đây và tác động tiềm năng (2-3 câu)",
        "action_plan": "Hành động cụ thể cho nhà đầu tư cá nhân (2-3 câu)"
    }}

    LƯU Ý: Phản hồi PHẢI là chuỗi JSON hợp lệ parse được bằng json.loads().
    """


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```json"):
        t = t[7:]
    if t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def get_ai_analysis(symbol: str, current_price: float, indicators: dict, history_summary: str, intraday_summary: str, api_key: str, fundamentals_summary: str = "", news_summary: str = "", foreign_summary: str = "", mtf_summary: str = ""):
    """
    Gọi Gemini API phân tích chỉ báo kỹ thuật + dòng tiền nội ngày.
    Trả về JSON gồm khuyến nghị, độ tin cậy, giá mục tiêu, stop-loss, và các giải thích.
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY")

    if not active_key:
        return {
            "recommendation": "HOLD",
            "confidence": 0,
            "target_price": current_price,
            "stop_loss": current_price * 0.95,
            "summary": "Thiếu API Key cho AI.",
            "technical_analysis": "Vui lòng nhập Gemini API Key ở góc trên màn hình để sử dụng tính năng phân tích AI.",
            "trend_analysis": "Chưa thể phân tích xu hướng.",
            "fundamental_analysis": "Chưa thể phân tích cơ bản.",
            "action_plan": "Nhập API Key hợp lệ để bắt đầu nhận tín hiệu mua/bán.",
            "error": "missing_api_key",
        }

    prompt = _build_analysis_prompt(symbol, current_price, indicators, history_summary, intraday_summary, fundamentals_summary, news_summary)
    # Append Phase 2 context blocks if provided (foreign flow + multi-timeframe)
    extra_blocks = []
    if foreign_summary:
        extra_blocks.append("LUỒNG TIỀN KHỐI NGOẠI (Foreign trade):\n" + foreign_summary)
    if mtf_summary:
        extra_blocks.append("PHÂN TÍCH ĐA KHUNG THỜI GIAN (Multi-timeframe):\n" + mtf_summary)
    if extra_blocks:
        prompt = prompt + "\n\n" + "\n\n".join(extra_blocks)

    structured_error = None
    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text.strip())
    except Exception as e:
        structured_error = str(e)
        print(f"Error invoking Gemini API (structured mode): {structured_error}")

    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return json.loads(_strip_json_fence(response.text))
    except Exception as err:
        err_msg = str(err)
        # Phân loại lỗi để UI hiển thị cảnh báo chính xác
        if "API key" in err_msg or "API_KEY" in err_msg or "invalid" in err_msg.lower() and "key" in err_msg.lower():
            err_code = "invalid_api_key"
        elif "quota" in err_msg.lower() or "rate" in err_msg.lower() or "429" in err_msg:
            err_code = "quota_exceeded"
        elif "network" in err_msg.lower() or "connection" in err_msg.lower() or "timeout" in err_msg.lower():
            err_code = "network_error"
        else:
            err_code = "api_error"
        return {
            "recommendation": "HOLD",
            "confidence": 0,
            "target_price": current_price,
            "stop_loss": current_price * 0.93,
            "summary": "Không thể hoàn tất phân tích AI tại thời điểm này.",
            "technical_analysis": f"Lỗi từ Gemini API: {err_msg[:200]}",
            "trend_analysis": "Dữ liệu xu hướng tạm thời bị gián đoạn.",
            "fundamental_analysis": "Không có dữ liệu cơ bản.",
            "action_plan": "Vui lòng thử lại sau vài giây hoặc kiểm tra tính hợp lệ của API Key.",
            "error": err_code,
            "error_detail": err_msg[:500],
        }


def chat_about_stock(symbol: str, message: str, chart_data_summary: str, api_key: str):
    active_key = api_key or os.getenv("GEMINI_API_KEY")
    if not active_key:
        return "Vui lòng nhập Gemini API Key để chat với AI."

    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)

        prompt = f"""
        Bạn là Cố vấn đầu tư chứng khoán Việt Nam thông thái. Người dùng đang xem biểu đồ cổ phiếu {symbol}.

        Tóm tắt dữ liệu kỹ thuật hiện tại của {symbol}:
        {chart_data_summary}

        Câu hỏi của người dùng: "{message}"

        Trả lời rõ ràng, ngắn gọn, dễ hiểu và mang tính tư vấn chuyên môn cao. Trả lời bằng tiếng Việt.
        """

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Lỗi khi gửi câu hỏi đến AI: {str(e)}"
