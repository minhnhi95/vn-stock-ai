import google.generativeai as genai
import json
import os

from verdict_guard import FILTER_NOTE, clean_fields, strip_verdicts

# Model có thể override qua env var để dễ thử nghiệm/giảm chi phí.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Các trường AI được phép trả về. Cố ý KHÔNG có recommendation, confidence,
# target_price hay stop_loss: người mới thấy "MUA MẠNH — độ tin cậy 85%" sẽ làm
# theo, trong khi một mô hình đọc vài chỉ báo không có căn cứ nào đủ chắc để đưa
# ra nhãn đó. Trường nào ngoài danh sách này đều bị bỏ trước khi tới giao diện,
# kể cả khi mô hình tự thêm vào.
TEXT_FIELDS = ("tong_quan", "ky_thuat", "xu_huong", "co_ban", "tin_tuc", "mau_thuan")
LIST_FIELDS = ("rui_ro", "cau_hoi_tu_hoi")


def _build_analysis_prompt(symbol, current_price, indicators, history_summary, intraday_summary, fundamentals_summary="", news_summary="", extra_context=""):
    def fmt(key, prec):
        v = indicators.get(key)
        return f"{v:.{prec}f}" if isinstance(v, (int, float)) else "N/A"

    fundamentals_block = fundamentals_summary or "Dữ liệu cơ bản: Không khả dụng."
    news_block = news_summary or "Tin tức: Không có tin nổi bật."
    extra_block = extra_context or "Không có dữ liệu bổ sung."

    return f"""
    Bạn đang giải thích cổ phiếu {symbol} cho một người MỚI tìm hiểu chứng khoán Việt Nam.
    Việc của bạn là đọc giúp các con số dưới đây bằng tiếng Việt đời thường — không phải
    quyết định giúp họ.

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

    [4] BỐI CẢNH BỔ SUNG
    {extra_block}

    QUY TẮC BẮT BUỘC:
    1. TUYỆT ĐỐI KHÔNG khuyên mua, bán hay nắm giữ. Không chấm điểm, không nêu mức chắc
       chắn của nhận định, không đưa giá mục tiêu, vùng mua, mức cắt lỗ hay chốt lời.
    2. Chỉ dùng số liệu có trong dữ liệu trên. Không bịa số. Khía cạnh nào thiếu dữ liệu
       thì ghi "Không có dữ liệu".
    3. Thuật ngữ nào dùng lần đầu (RSI, MACD, EMA, P/E...) thì giải thích bằng một câu ngắn.
    4. Nếu các nguồn dữ liệu nói ngược nhau, nói rõ ở mục mau_thuan — với người mới, đó
       là thông tin quan trọng nhất.
    5. cau_hoi_tu_hoi là câu hỏi người đọc nên TỰ trả lời trước khi quyết định, ví dụ
       "Nếu giá giảm thêm 15% thì bạn sẽ làm gì?" — không phải lời khuyên trá hình.

    Xuất ra duy nhất một JSON theo cấu trúc dưới, KHÔNG kèm markdown:
    {{
        "tong_quan": "2-3 câu: bức tranh chung mà dữ liệu cho thấy",
        "ky_thuat": "RSI, MACD, EMA đang cho thấy gì, giải thích dễ hiểu (3-4 câu)",
        "xu_huong": "Xu hướng giá ngắn và trung hạn dựa trên EMA (2-3 câu)",
        "co_ban": "Các chỉ số cơ bản nói gì về doanh nghiệp (2-3 câu)",
        "tin_tuc": "Tin gần đây có gì đáng chú ý và vì sao (2-3 câu)",
        "mau_thuan": "Chỗ các nguồn dữ liệu nói ngược nhau, hoặc 'Không có'",
        "rui_ro": ["2-4 rủi ro cụ thể, mỗi ý một câu"],
        "cau_hoi_tu_hoi": ["2-3 câu hỏi người đọc nên tự trả lời"]
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


def _error_result(code: str, message: str, detail: str = "") -> dict:
    result = {"tong_quan": message, "error": code}
    if detail:
        result["error_detail"] = detail[:500]
    return result


def sanitize_analysis(raw) -> dict:
    """
    Chỉ giữ các trường cho phép và lọc câu mang tính chỉ dẫn mua/bán.

    Mô hình vẫn có thể trả thêm "recommendation" dù prompt đã cấm — trường lạ bị bỏ
    ở đây và không bao giờ tới giao diện. Nếu có câu bị lọc, kết quả nói rõ điều đó
    thay vì âm thầm cắt.
    """
    if not isinstance(raw, dict):
        return _error_result("api_error", "AI trả về dữ liệu không đọc được.")
    clean, removed = clean_fields(raw, TEXT_FIELDS, LIST_FIELDS)
    if removed:
        clean["da_loc"] = removed
        clean["ghi_chu_loc"] = FILTER_NOTE
    return clean


def get_ai_analysis(symbol: str, current_price: float, indicators: dict, history_summary: str, intraday_summary: str, api_key: str, fundamentals_summary: str = "", news_summary: str = "", foreign_summary: str = "", mtf_summary: str = ""):
    """
    Nhờ Gemini diễn giải chỉ báo kỹ thuật, chỉ số cơ bản và tin tức của một mã.

    Trả về các đoạn giải thích + rủi ro + câu hỏi tự kiểm tra. Không có khuyến
    nghị, độ tin cậy, giá mục tiêu hay mức cắt lỗ — xem sanitize_analysis.
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY")

    if not active_key:
        return _error_result(
            "missing_api_key",
            "Chưa có Gemini API Key — nhập key ở góc trên màn hình để AI giải thích mã này.",
        )

    extra_blocks = []
    if foreign_summary:
        extra_blocks.append("LUỒNG TIỀN KHỐI NGOẠI (Foreign trade):\n" + foreign_summary)
    if mtf_summary:
        extra_blocks.append("PHÂN TÍCH ĐA KHUNG THỜI GIAN (Multi-timeframe):\n" + mtf_summary)

    prompt = _build_analysis_prompt(
        symbol,
        current_price,
        indicators,
        history_summary,
        intraday_summary,
        fundamentals_summary,
        news_summary,
        extra_context="\n\n".join(extra_blocks),
    )

    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return sanitize_analysis(json.loads(response.text.strip()))
    except Exception as e:
        print(f"Error invoking Gemini API (structured mode): {e}")

    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return sanitize_analysis(json.loads(_strip_json_fence(response.text)))
    except Exception as err:
        err_msg = str(err)
        lowered = err_msg.lower()
        # Phân loại lỗi để UI hiển thị cảnh báo chính xác
        if "API key" in err_msg or "API_KEY" in err_msg or ("invalid" in lowered and "key" in lowered):
            err_code = "invalid_api_key"
        elif "quota" in lowered or "rate" in lowered or "429" in err_msg:
            err_code = "quota_exceeded"
        elif "network" in lowered or "connection" in lowered or "timeout" in lowered:
            err_code = "network_error"
        else:
            err_code = "api_error"
        return _error_result(err_code, "Không thể hoàn tất phần giải thích của AI lúc này.", err_msg)


def guard_chat_answer(text: str) -> str:
    """Bỏ câu mang tính chỉ dẫn mua/bán khỏi câu trả lời chat, và nói rõ là đã bỏ."""
    clean, removed = strip_verdicts(text)
    if not removed:
        return text
    return f"{clean}\n\n({FILTER_NOTE})" if clean else FILTER_NOTE


def chat_about_stock(symbol: str, message: str, chart_data_summary: str, api_key: str):
    active_key = api_key or os.getenv("GEMINI_API_KEY")
    if not active_key:
        return "Vui lòng nhập Gemini API Key để hỏi AI."

    try:
        genai.configure(api_key=active_key)
        model = genai.GenerativeModel(GEMINI_MODEL)

        prompt = f"""
        Bạn đang giúp một người MỚI tìm hiểu chứng khoán hiểu về cổ phiếu {symbol}.

        Dữ liệu hiện tại của {symbol}:
        {chart_data_summary}

        Câu hỏi của người dùng: "{message}"

        Quy tắc:
        - Trả lời bằng tiếng Việt, ngắn gọn, dễ hiểu; giải thích thuật ngữ khi dùng.
        - TUYỆT ĐỐI KHÔNG khuyên mua, bán hay nắm giữ; không đưa giá mục tiêu, vùng mua hay
          mức cắt lỗ. Nếu được hỏi có nên mua hoặc bán không, hãy nói rõ bạn không đưa
          khuyến nghị, rồi chỉ ra những yếu tố người hỏi cần tự cân nhắc và số liệu nào ở
          trên liên quan.
        - Chỉ dùng số liệu có trong dữ liệu trên; không bịa.
        """

        response = model.generate_content(prompt)
        return guard_chat_answer(response.text.strip())
    except Exception as e:
        return f"Lỗi khi gửi câu hỏi đến AI: {str(e)}"
