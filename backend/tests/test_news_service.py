"""
Tìm tin theo từ khoá — nhánh chạy khi người dùng chưa có Gemini API key.

Không đụng mạng: bơm thẳng vào index tin rồi tìm.
"""
from __future__ import annotations

import pytest

import news_service
from news_service import _keyword_score, _normalize_vn, search_news_keyword


class TestNormalizeVn:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Kết quả kinh doanh", "ket qua kinh doanh"),
            ("Đầu tư", "dau tu"),
            ("CỔ PHIẾU", "co phieu"),
            ("Niêm yết bổ sung", "niem yet bo sung"),
            ("", ""),
        ],
    )
    def test_bo_dau_va_ha_chu_thuong(self, raw, expected):
        assert _normalize_vn(raw) == expected

    def test_chu_d_gach_ngang_thanh_d(self):
        # đ không phải dấu tổ hợp nên NFD không tách được — phải thay riêng.
        assert "d" in _normalize_vn("đầu tư") and "đ" not in _normalize_vn("đầu tư")


class TestKeywordScore:
    def test_khop_tieu_de_diem_cao_hon_tom_tat(self):
        in_title = _keyword_score(["cotuc"], {"title": "chia cotuc", "summary": ""})
        in_summary = _keyword_score(["cotuc"], {"title": "", "summary": "chia cotuc"})
        assert in_title > in_summary

    def test_khop_het_token_duoc_diem_toi_da(self):
        assert _keyword_score(["ket", "qua"], {"title": "ket qua kinh doanh", "summary": ""}) == 1.0

    def test_khong_khop_thi_0(self):
        assert _keyword_score(["cotuc"], {"title": "niem yet", "summary": ""}) == 0.0

    def test_query_rong_thi_0(self):
        assert _keyword_score([], {"title": "bất kỳ", "summary": ""}) == 0.0


@pytest.fixture()
def seeded_index(monkeypatch):
    """Index tin giả lập, cô lập khỏi state toàn cục của module."""
    index = {
        "a": {
            "symbol": "FPT",
            "title": "FPT: Nghị quyết HĐQT về phát hành cổ phiếu tăng vốn",
            "summary": "",
            "url": "https://example.com/a",
        },
        "b": {
            "symbol": "FPT",
            "title": "FPT: Thông báo thay đổi đăng ký niêm yết",
            "summary": "Niêm yết bổ sung cổ phiếu",
            "url": "https://example.com/b",
        },
        "c": {
            "symbol": "HPG",
            "title": "HPG: Kết quả kinh doanh quý 2",
            "summary": "",
            "url": "https://example.com/c",
            "_embedding": [0.1, 0.2],
        },
    }
    monkeypatch.setattr(news_service, "_news_index", index)
    return index


class TestSearchNewsKeyword:
    def test_tim_khong_dau_van_khop_tin_co_dau(self, seeded_index):
        result = search_news_keyword("co phieu", top_k=5)
        assert result["ok"] is True
        assert result["mode"] == "keyword"
        assert len(result["results"]) >= 1

    def test_loc_theo_symbol(self, seeded_index):
        result = search_news_keyword("ket qua kinh doanh", top_k=5, symbol_filter=["HPG"])
        assert [r["symbol"] for r in result["results"]] == ["HPG"]

    def test_sap_xep_theo_diem_giam_dan(self, seeded_index):
        scores = [r["score"] for r in search_news_keyword("niem yet co phieu", top_k=5)["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_ton_trong_top_k(self, seeded_index):
        assert len(search_news_keyword("co phieu", top_k=1)["results"]) <= 1

    def test_khong_khop_gi_tra_danh_sach_rong(self, seeded_index):
        assert search_news_keyword("bitcoin ethereum", top_k=5)["results"] == []

    def test_khong_lo_field_noi_bo(self, seeded_index):
        # `_embedding` là vector nội bộ, không được trả ra API.
        results = search_news_keyword("ket qua", top_k=5, symbol_filter=["HPG"])["results"]
        assert results
        assert all(not key.startswith("_") for r in results for key in r)

    def test_index_rong_tra_note_huong_dan(self, monkeypatch):
        monkeypatch.setattr(news_service, "_news_index", {})
        result = search_news_keyword("co phieu", top_k=5)
        assert result["ok"] is True
        assert result["results"] == []
        assert "Index trống" in result["note"]


class TestSemanticFallback:
    def test_thieu_api_key_thi_lui_ve_tim_tu_khoa(self, seeded_index, monkeypatch):
        # Điểm chính: người dùng chưa cấu hình key vẫn tìm được, thay vì nhận lỗi trắng.
        monkeypatch.setattr(news_service, "_embed_text", lambda text, api_key=None: None)
        result = news_service.search_news_semantic("co phieu", top_k=3, api_key=None)
        assert result["ok"] is True
        assert result["mode"] == "keyword"
        assert result["results"]
