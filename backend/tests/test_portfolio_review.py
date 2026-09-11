"""
Review danh mục thật — mô tả bằng số liệu, không chấm điểm, không ra hành động.

Bản cũ trả "điểm 35/100, rủi ro CAO, chốt lời 1 phần VCB". Trên tiền thật của một
người mới, đó là lệnh bán. Test khoá lại: phần tính bằng Python không bao giờ có
điểm hay hành động, và phần AI (nếu có) bị lọc dù mô hình tự ý thêm vào.
"""
from __future__ import annotations

import json

import portfolio_review_service as prs
from verdict_guard import contains_verdict

FORBIDDEN = {"overall_score", "risk_level", "recommendation", "rebalance_suggestions"}


def _holding(symbol, sector, weight, value):
    return {
        "symbol": symbol,
        "sector": sector,
        "shares": 1000,
        "avg_price": value / 1000 * 0.9,
        "price": value / 1000,
        "market_value": value,
        "weight_pct": weight,
        "pnl": value * 0.1,
        "pnl_pct": 11.1,
        "rsi": 60.0,
        "macd_hist": 0.1,
    }


def _metrics():
    return {
        "holdings": [
            _holding("VCB", "Ngân hàng", 50.0, 50_000_000.0),
            _holding("TCB", "Ngân hàng", 30.0, 30_000_000.0),
            _holding("FPT", "Công nghệ", 20.0, 20_000_000.0),
        ],
        "cash": 0.0,
        "initial_capital": 90_000_000.0,
        "total_nav": 100_000_000.0,
        "sector_breakdown": [
            {"sector": "Ngân hàng", "weight_pct": 80.0, "symbols": ["VCB", "TCB"]},
            {"sector": "Công nghệ", "weight_pct": 20.0, "symbols": ["FPT"]},
        ],
        "high_correlation_pairs": [{"a": "VCB", "b": "TCB", "correlation": 0.9}],
        "concentration_flag": "VCB chiếm 50.0% NAV (ngưỡng cảnh báo 30%)",
        "sector_flag": "Ngành 'Ngân hàng' chiếm 80.0% NAV (ngưỡng cảnh báo 40%)",
        "correlation_flag": None,
        "portfolio_return_6mo": 12.0,
        "vnindex_return_6mo": 8.0,
    }


class TestPhanTinhBangPython:
    def test_khong_co_diem_muc_rui_ro_hay_hanh_dong(self):
        assert not FORBIDDEN & set(prs._base_review(_metrics()))

    def test_quan_sat_co_so_lieu_that(self):
        obs = " ".join(prs._base_review(_metrics())["quan_sat"])
        assert "VCB với 50.0%" in obs
        assert "Ngân hàng 80%" in obs
        assert "VCB–TCB" in obs

    def test_cau_hoi_tinh_san_muc_anh_huong(self):
        # 50% danh mục x giảm 20% = cả danh mục giảm 10%
        first = prs._base_review(_metrics())["cau_hoi"][0]
        assert "Nếu VCB giảm 20%, cả danh mục giảm khoảng 10.0%" in first

    def test_khong_cau_nao_la_phan_quyet(self):
        review = prs._base_review(_metrics())
        texts = review["quan_sat"] + review["cau_hoi"]
        texts += [v for k, v in review.items() if k.endswith("_warning") and v]
        for text in texts:
            assert not contains_verdict(text), text


class TestReviewPortfolio:
    def _setup(self, monkeypatch):
        monkeypatch.setattr(
            prs,
            "_real_portfolio_as_holdings",
            lambda: {"holdings": [{"symbol": "VCB", "shares": 1000}], "cash": 0.0, "initial_capital": 1.0},
        )
        monkeypatch.setattr(prs, "_compute_metrics", lambda portfolio: _metrics())
        monkeypatch.setattr(prs, "_cache", type(prs._cache)())

    def test_khong_co_key_van_tra_du_phan_python(self, monkeypatch):
        self._setup(monkeypatch)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        review = prs.review_portfolio(api_key="")
        assert review["source"] == "python"
        assert review["quan_sat"] and review["cau_hoi"]
        assert not FORBIDDEN & set(review)

    def test_ai_tu_them_diem_va_hanh_dong_thi_bi_bo(self, monkeypatch):
        self._setup(monkeypatch)
        payload = {
            "overall_score": 90,
            "risk_level": "HIGH",
            "recommendation": "Bán bớt VCB.",
            "rebalance_suggestions": ["Giảm VCB"],
            "dien_giai": "Danh mục dồn vào ngân hàng. Bạn nên bán bớt VCB.",
            "rui_ro_chinh": ["Ngân hàng chiếm 80% danh mục.", "Nên chốt lời VCB."],
        }

        class _Response:
            text = json.dumps(payload, ensure_ascii=False)

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

        monkeypatch.setattr(prs, "genai", _Genai, raising=False)
        monkeypatch.setattr(prs, "HAS_GENAI", True)
        review = prs.review_portfolio(api_key="fake")
        assert not FORBIDDEN & set(review)
        assert review["dien_giai"] == "Danh mục dồn vào ngân hàng."
        assert review["rui_ro_chinh"] == ["Ngân hàng chiếm 80% danh mục."]
        assert review["da_loc"] == 2


class TestTenNganh:
    """Tên ngành phải là tiếng Việt và cùng nguồn với các panel khác."""

    def _clear(self, monkeypatch):
        monkeypatch.setattr(prs, "_cache", type(prs._cache)())

    def test_uu_tien_ten_nganh_icb_tieng_viet(self, monkeypatch):
        import sector_service

        self._clear(monkeypatch)
        monkeypatch.setattr(
            sector_service,
            "get_industries",
            lambda: [{"name": "Thực phẩm và đồ uống", "symbols": ["VNM"]}],
        )
        monkeypatch.setattr(prs, "_lookup_sector_vnstock", lambda symbol: "Food & Beverage")
        assert prs.get_sector("VNM") == "Thực phẩm và đồ uống"

    def test_khong_co_icb_thi_dung_bang_du_phong_tieng_viet(self, monkeypatch):
        import sector_service

        self._clear(monkeypatch)
        monkeypatch.setattr(sector_service, "get_industries", lambda: [])
        monkeypatch.setattr(prs, "_lookup_sector_vnstock", lambda symbol: "Food & Beverage")
        assert prs.get_sector("VNM") == "Tiêu dùng"
