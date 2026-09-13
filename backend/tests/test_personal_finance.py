"""
Tài chính cá nhân — tổng tài sản, phân bổ, kiểm tra an toàn.

Test khoá những chỗ mà sai là khiến người dùng yên tâm nhầm:
  1. Thiếu dữ liệu thì nói "chưa biết", không được hiện "đạt".
  2. Tỷ lệ tính trên TỔNG tài sản, không phải trên riêng phần cổ phiếu.
  3. Bỏ trống khác với nhập 0.
Không test nào gọi mạng.
"""
from __future__ import annotations

from datetime import date

import pytest

import personal_finance_service as pf

# Danh mục giống của chủ dự án ngày 13/09/2026: một mã FPT, đang lỗ.
PORTFOLIO = {
    "summary": {
        "total_cost": 424_974_098.0,
        "market_value": 336_237_500.0,
        "unrealized_pnl": -89_577_192.0,
        "unrealized_pct": -21.08,
        "realized_pnl": 0,
        "first_txn": "2025-07-31",
    },
    "positions": [{"symbol": "FPT", "market_value": 336_237_500.0, "cost_basis": 424_974_098.0}],
}
TODAY = date(2026, 9, 13)


def _check(result, key):
    return next(c for c in result["checks"] if c["key"] == key)


class TestNhapLieu:
    def test_bo_trong_la_none_khong_phai_0(self):
        cleaned = pf.validate_inputs({"cash": "", "savings": None})
        assert cleaned["cash"] is None and cleaned["savings"] is None

    def test_doc_duoc_so_kieu_viet_nam(self):
        cleaned = pf.validate_inputs({"cash": "50.000.000", "savings": "1,200,000", "savings_rate_pct": "5,5"})
        assert cleaned["cash"] == 50_000_000
        assert cleaned["savings"] == 1_200_000
        assert cleaned["savings_rate_pct"] == 5.5

    def test_so_am_bi_tu_choi(self):
        with pytest.raises(pf.FinanceInputError, match="không được âm"):
            pf.validate_inputs({"debts": -1})

    def test_chu_bi_tu_choi(self):
        with pytest.raises(pf.FinanceInputError, match="không phải là số"):
            pf.validate_inputs({"cash": "một trăm"})

    def test_lai_suat_bat_thuong_bi_tu_choi(self):
        with pytest.raises(pf.FinanceInputError, match="bất thường"):
            pf.validate_inputs({"savings_rate_pct": 45})


class TestThieuDuLieu:
    def test_chua_nhap_gi_thi_khong_hien_dat(self):
        r = pf.compute({}, PORTFOLIO, TODAY)
        assert r["needs_setup"] is True
        assert {c["status"] for c in r["checks"]} == {"unknown"}
        assert "Nhập tiền mặt" in r["headline"]

    def test_chua_co_tien_mat_thi_ty_le_co_phieu_la_chua_biet_chu_khong_phai_100(self):
        r = pf.compute({"monthly_expenses": 10_000_000}, PORTFOLIO, TODAY)
        assert _check(r, "stock_share")["status"] == "unknown"
        assert _check(r, "single_stock")["status"] == "unknown"

    def test_khong_co_danh_muc_van_tinh_duoc_quy_du_phong(self):
        r = pf.compute({"cash": 60_000_000, "monthly_expenses": 10_000_000}, None, TODAY)
        assert _check(r, "emergency")["status"] == "pass"
        assert r["total_assets"] == 60_000_000


class TestKiemTra:
    def test_quy_du_phong_theo_so_thang(self):
        def status(cash):
            return _check(pf.compute({"cash": cash, "monthly_expenses": 10_000_000}, None, TODAY), "emergency")["status"]

        assert status(60_000_000) == "pass"   # 6 tháng
        assert status(40_000_000) == "warn"   # 4 tháng
        assert status(20_000_000) == "fail"   # 2 tháng

    def test_ty_le_tinh_tren_tong_tai_san(self):
        # 336 tr cổ phiếu + 100 tr tiết kiệm + 14 tr tiền mặt = 450 tr -> cổ phiếu ~74,7%.
        r = pf.compute({"cash": 14_000_000, "savings": 100_000_000, "monthly_expenses": 15_000_000}, PORTFOLIO, TODAY)
        assert r["total_assets"] == 450_237_500
        share = _check(r, "stock_share")
        assert share["status"] == "fail" and share["display"] == "74.7%"
        single = _check(r, "single_stock")
        assert single["status"] == "fail" and "FPT" in single["label"]
        # 114 tr / 15 tr = 7,6 tháng
        assert _check(r, "emergency")["status"] == "pass"

    def test_tai_san_rong_tru_no(self):
        r = pf.compute({"cash": 100_000_000, "debts": 40_000_000}, None, TODAY)
        assert r["net_worth"] == 60_000_000
        assert _check(r, "debt")["status"] == "warn"  # 40%

    def test_khong_no_thi_khong_co_muc_no(self):
        r = pf.compute({"cash": 100_000_000}, None, TODAY)
        assert all(c["key"] != "debt" for c in r["checks"])

    def test_phan_bo_cong_du_100(self):
        r = pf.compute({"cash": 14_000_000, "savings": 100_000_000}, PORTFOLIO, TODAY)
        assert sum(a["pct"] for a in r["allocation"]) == pytest.approx(100.0, abs=0.05)
        assert [a["key"] for a in r["allocation"]] == ["cash", "savings", "stocks"]


class TestSoVoiTietKiem:
    def test_tinh_lai_tiet_kiem_don_gian_tu_ngay_mua_dau(self):
        r = pf.compute({"cash": 1, "savings_rate_pct": 5}, PORTFOLIO, TODAY)
        c = r["savings_comparison"]
        assert c["days"] == 409
        assert c["savings_gain"] == pytest.approx(424_974_098 * 0.05 * 409 / 365, abs=1)
        assert c["stock_pnl"] == -89_577_192
        assert c["difference"] < 0
        assert "lỗ" in c["text"]

    def test_chua_nhap_lai_suat_thi_dung_5_phan_tram(self):
        c = pf.compute({"cash": 1}, PORTFOLIO, TODAY)["savings_comparison"]
        assert c["rate_pct"] == pf.DEFAULT_SAVINGS_RATE_PCT

    def test_khong_co_gia_thi_khong_so(self):
        unpriced = {"summary": {**PORTFOLIO["summary"], "market_value": 0}, "positions": PORTFOLIO["positions"]}
        assert pf.compute({"cash": 1}, unpriced, TODAY)["savings_comparison"] is None


class TestLuuTru:
    def test_luu_va_doc_lai(self, temp_storage):
        assert temp_storage.get_personal_finance() is None
        temp_storage.save_personal_finance({"inputs": {"cash": 1_000_000.0}})
        temp_storage.save_personal_finance({"inputs": {"cash": 2_000_000.0}})
        saved = temp_storage.get_personal_finance()
        assert saved["inputs"]["cash"] == 2_000_000.0
        assert saved["updated_at"]


class TestTheoTungLo:
    def test_lai_tiet_kiem_tinh_theo_ngay_mua_tung_lo(self):
        portfolio = {
            "summary": PORTFOLIO["summary"],
            "positions": [
                {
                    "symbol": "FPT",
                    "market_value": 336_237_500.0,
                    "cost_basis": 424_974_098.0,
                    "lots": [
                        {"date": "2025-07-31", "quantity": 4125, "price": 93_482.46},
                        {"date": "2026-03-10", "quantity": 500, "price": 78_600.0},
                    ],
                }
            ],
        }
        c = pf.compute({"cash": 1, "savings_rate_pct": 5}, portfolio, TODAY)["savings_comparison"]
        assert c["by_lot"] is True
        expected = 4125 * 93_482.46 * 0.05 * 409 / 365 + 500 * 78_600 * 0.05 * 187 / 365
        assert c["savings_gain"] == pytest.approx(expected, abs=2)
        # Ít hơn cách tính chung từ ngày đầu, vì lô tháng 3 không có lãi từ tháng 7 năm trước.
        flat = pf.compute({"cash": 1, "savings_rate_pct": 5}, PORTFOLIO, TODAY)["savings_comparison"]
        assert c["savings_gain"] < flat["savings_gain"]
        assert "từng lô" in c["text"]
