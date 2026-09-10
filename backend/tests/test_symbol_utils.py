"""
Nhận dạng mã chứng khoán VN.

Bài học đứng sau file này: 4 module từng tự viết `len(s)==3 and s.isalpha()`,
loại nhầm 160/1.881 mã có chứa chữ số. Nặng nhất là lúc nhập sao kê THẬT —
các dòng đó bị bỏ im lặng, sổ lệnh thiếu, giá vốn sai.
"""
from __future__ import annotations

import pytest

from symbol_utils import clean_and_validate, is_vn_symbol, normalize_symbol


class TestIsVnSymbol:
    @pytest.mark.parametrize("symbol", ["FPT", "HPG", "VCB", "SSI"])
    def test_ma_toan_chu(self, symbol):
        assert is_vn_symbol(symbol) is True

    @pytest.mark.parametrize("symbol", ["HT1", "NT2", "PC1", "TV2", "CC1", "C4G", "S99", "A32"])
    def test_ma_co_chua_so_van_hop_le(self, symbol):
        # Hà Tiên 1, Nhơn Trạch 2, PC1, TV2... đều là mã niêm yết thật.
        assert is_vn_symbol(symbol) is True

    @pytest.mark.parametrize("symbol", ["1PC", "2NT", "999"])
    def test_khong_duoc_bat_dau_bang_so(self, symbol):
        # Kiểm tra trên danh sách niêm yết thật: không mã nào bắt đầu bằng số.
        assert is_vn_symbol(symbol) is False

    @pytest.mark.parametrize(
        "symbol",
        ["FP", "FPTX", "fpt", "Fpt", "", "FP T", "FP-", "FUEVFVND", "CVNM2314", None],
    )
    def test_khong_hop_le(self, symbol):
        assert is_vn_symbol(symbol) is False


class TestNormalize:
    def test_bo_khoang_trang_va_viet_hoa(self):
        assert normalize_symbol("  ht1 ") == "HT1"

    def test_input_rong(self):
        assert normalize_symbol(None) == ""


class TestCleanAndValidate:
    def test_chuan_hoa_roi_kiem_tra(self):
        assert clean_and_validate(" ht1 ") == "HT1"

    def test_khong_hop_le_tra_none(self):
        assert clean_and_validate("khong-phai-ma") is None


class TestKhongConLoaiNhamODaugCua:
    """Các cửa ngõ từng chặn nhầm mã có chữ số."""

    def test_stock_service_cho_qua(self):
        from stock_service import is_vn_stock

        assert is_vn_stock("HT1") is True
        assert is_vn_stock("AAPL") is False

    def test_nhap_sao_ke_khong_bo_dong_co_ma_chua_so(self):
        from broker_import_service import parse_broker_csv

        csv = "Ngày,Mã CK,Lệnh,Số lượng,Giá\n2026-03-05,HT1,Mua,1000,12000\n"
        result = parse_broker_csv(csv.encode("utf-8"), "x.csv")
        assert [r["symbol"] for r in result["records"]] == ["HT1"]
        assert result["skipped"] == []

    def test_nhap_tay_ma_chua_so(self):
        from broker_import_service import build_manual_record

        assert build_manual_record("2026-03-05", "pc1", "BUY", 100, 20000)["symbol"] == "PC1"
