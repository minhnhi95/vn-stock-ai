"""
AI giải thích một mã — không được trả nhãn mua/bán dù mô hình tự ý thêm vào.

Không test nào gọi Gemini thật: mô hình được thay bằng bản giả trả đúng thứ ta
muốn thử, kể cả những thứ prompt đã cấm.
"""
from __future__ import annotations

import json

import ai_service

FORBIDDEN = {"recommendation", "confidence", "target_price", "stop_loss", "action_plan"}


def _fake_genai(payload_text):
    class _Response:
        text = payload_text

    class _Model:
        def __init__(self, name):
            pass

        def generate_content(self, prompt, generation_config=None):
            return _Response()

    class _Genai:
        @staticmethod
        def configure(api_key):
            pass

        GenerativeModel = _Model

    return _Genai


def _analyze(monkeypatch, payload):
    monkeypatch.setattr(ai_service, "genai", _fake_genai(json.dumps(payload, ensure_ascii=False)))
    return ai_service.get_ai_analysis(
        symbol="FPT",
        current_price=74500,
        indicators={"rsi": 72.0},
        history_summary="",
        intraday_summary="",
        api_key="fake",
    )


class TestPrompt:
    def test_prompt_cam_phan_quyet_va_khong_xin_truong_cam(self):
        prompt = ai_service._build_analysis_prompt("FPT", 74500, {"rsi": 72.0}, "", "")
        assert "TUYỆT ĐỐI KHÔNG" in prompt
        for key in FORBIDDEN:
            assert key not in prompt, key


class TestKetQuaPhanTich:
    def test_truong_phan_quyet_bi_bo_du_mo_hinh_tu_them(self, monkeypatch):
        result = _analyze(
            monkeypatch,
            {
                "recommendation": "STRONG_BUY",
                "confidence": 85,
                "target_price": 90000,
                "stop_loss": 65000,
                "tong_quan": "Giá đang nằm trên EMA20.",
            },
        )
        assert not FORBIDDEN & set(result)
        assert result["tong_quan"] == "Giá đang nằm trên EMA20."

    def test_cau_chi_dan_bi_loc_va_bao_ro(self, monkeypatch):
        result = _analyze(
            monkeypatch,
            {
                "ky_thuat": "RSI 72 là vùng quá mua. Bạn nên chốt lời.",
                "rui_ro": ["Nợ vay tăng.", "Nên cắt lỗ dưới 60.000."],
            },
        )
        assert result["ky_thuat"] == "RSI 72 là vùng quá mua."
        assert result["rui_ro"] == ["Nợ vay tăng."]
        assert result["da_loc"] == 2
        assert result["ghi_chu_loc"] == ai_service.FILTER_NOTE

    def test_thieu_key_khong_tra_truong_phan_quyet(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = ai_service.get_ai_analysis("FPT", 74500, {}, "", "", api_key="")
        assert result["error"] == "missing_api_key"
        assert not FORBIDDEN & set(result)

    def test_mo_hinh_tra_rac_khong_lam_vo(self, monkeypatch):
        monkeypatch.setattr(ai_service, "genai", _fake_genai("khong phai json"))
        result = ai_service.get_ai_analysis("FPT", 74500, {}, "", "", api_key="fake")
        assert result["error"] == "api_error"
        assert not FORBIDDEN & set(result)


class TestChat:
    def test_cau_tra_loi_chat_bi_loc_phan_quyet(self, monkeypatch):
        monkeypatch.setattr(ai_service, "genai", _fake_genai("P/E của FPT là 15,5. Bạn nên mua ngay."))
        answer = ai_service.chat_about_stock("FPT", "Có nên mua không?", "tóm tắt", api_key="fake")
        assert "nên mua" not in answer
        assert "P/E của FPT là 15,5." in answer
        assert ai_service.FILTER_NOTE in answer

    def test_loi_tu_choi_khuyen_nghi_duoc_giu_nguyen(self, monkeypatch):
        text = "Tôi không đưa khuyến nghị mua hay bán. P/E hiện là 15,5."
        monkeypatch.setattr(ai_service, "genai", _fake_genai(text))
        assert ai_service.chat_about_stock("FPT", "Có nên mua?", "tóm tắt", api_key="fake") == text
