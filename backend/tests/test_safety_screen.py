"""
Bộ lọc an toàn — quy tắc chặn mã nguy hiểm cho người mới.

Không có AI ở đây, toàn bộ là ngưỡng số. Test khoá lại đúng hành vi quan trọng
nhất: phân biệt "đạt", "cần cân nhắc" và "thiếu dữ liệu" — vì với người mới,
nhầm "thiếu dữ liệu" thành "an toàn" là nhầm lẫn tốn tiền.
"""
from __future__ import annotations

import pandas as pd
import pytest

from safety_screen import (
    MAX_DAILY_SWING_PCT,
    MAX_DEBT_TO_EQUITY,
    MIN_DAILY_VALUE_VND,
    MIN_PRICE_VND,
    screen_symbol,
)


def _frame(price=50_000, volume=1_000_000, swing_pct=2.0, bars=30):
    """Khung giá giả lập với thị giá, khối lượng và biên độ dao động cho trước."""
    half = price * swing_pct / 100 / 2
    index = pd.date_range(end="2026-09-10", periods=bars, freq="D")
    return pd.DataFrame(
        {
            "Open": [price] * bars,
            "High": [price + half] * bars,
            "Low": [price - half] * bars,
            "Close": [price] * bars,
            "Volume": [volume] * bars,
        },
        index=index,
    )


def _check(result, key):
    return next(c for c in result["checks"] if c["key"] == key)


class TestThanhKhoan:
    def test_thanh_khoan_cao_thi_dat(self):
        # 50.000đ x 1tr CP = 50 tỷ/phiên
        result = screen_symbol("FPT", df=_frame(price=50_000, volume=1_000_000))
        assert _check(result, "liquidity")["status"] == "pass"

    def test_thanh_khoan_thap_thi_canh_bao(self):
        # 50.000đ x 20.000 CP = 1 tỷ/phiên, dưới ngưỡng 5 tỷ
        result = screen_symbol("XYZ", df=_frame(price=50_000, volume=20_000))
        check = _check(result, "liquidity")
        assert check["status"] == "fail"
        assert "không có người mua" in check["explain"]

    def test_ngay_sat_nguong_van_dat(self):
        volume = MIN_DAILY_VALUE_VND / 50_000
        result = screen_symbol("XYZ", df=_frame(price=50_000, volume=volume))
        assert _check(result, "liquidity")["status"] == "pass"


class TestThiGia:
    def test_gia_tren_10k_thi_dat(self):
        result = screen_symbol("FPT", df=_frame(price=MIN_PRICE_VND))
        assert _check(result, "penny")["status"] == "pass"

    def test_penny_thi_canh_bao(self):
        result = screen_symbol("XYZ", df=_frame(price=3_600))
        check = _check(result, "penny")
        assert check["status"] == "fail"
        assert check["display"] == "3,600 đ"


class TestDonBay:
    def test_no_thap_thi_dat(self):
        result = screen_symbol("FPT", df=_frame(), fundamentals={"debt_to_equity": 0.46})
        assert _check(result, "leverage")["status"] == "pass"

    def test_no_cao_thi_canh_bao(self):
        result = screen_symbol("XYZ", df=_frame(), fundamentals={"debt_to_equity": 3.2})
        assert _check(result, "leverage")["status"] == "fail"

    def test_dung_nguong_van_dat(self):
        result = screen_symbol(
            "XYZ", df=_frame(), fundamentals={"debt_to_equity": MAX_DEBT_TO_EQUITY}
        )
        assert _check(result, "leverage")["status"] == "pass"


class TestSinhLoi:
    def test_roe_duong_thi_dat(self):
        result = screen_symbol("FPT", df=_frame(), fundamentals={"roe": 27.33})
        assert _check(result, "profitability")["status"] == "pass"

    def test_roe_am_thi_canh_bao(self):
        result = screen_symbol("XYZ", df=_frame(), fundamentals={"roe": -5.0})
        assert _check(result, "profitability")["status"] == "fail"

    def test_roe_bang_0_cung_canh_bao(self):
        # ROE = 0 nghĩa là không sinh lời đồng nào trên vốn chủ.
        result = screen_symbol("XYZ", df=_frame(), fundamentals={"roe": 0.0})
        assert _check(result, "profitability")["status"] == "fail"


class TestDoNong:
    def test_bien_do_thap_thi_dat(self):
        result = screen_symbol("FPT", df=_frame(swing_pct=2.0))
        assert _check(result, "volatility")["status"] == "pass"

    def test_bien_do_qua_lon_thi_canh_bao(self):
        result = screen_symbol("XYZ", df=_frame(swing_pct=MAX_DAILY_SWING_PCT + 3))
        assert _check(result, "volatility")["status"] == "fail"


class TestRoChiSo:
    def test_trong_vn100_thi_dat(self):
        result = screen_symbol("FPT", df=_frame(), vn100={"FPT", "HPG"})
        assert _check(result, "coverage")["status"] == "pass"

    def test_ngoai_vn100_thi_canh_bao(self):
        result = screen_symbol("XYZ", df=_frame(), vn100={"FPT", "HPG"})
        assert _check(result, "coverage")["status"] == "fail"

    def test_khong_biet_ro_thi_la_unknown(self):
        result = screen_symbol("XYZ", df=_frame(), vn100=None)
        assert _check(result, "coverage")["status"] == "unknown"


class TestThieuDuLieu:
    """Điểm quan trọng nhất: thiếu dữ liệu KHÁC với an toàn."""

    def test_khong_co_gia_thi_khong_ket_luan(self):
        result = screen_symbol("XYZ", df=None, fundamentals={"roe": 10.0})
        assert _check(result, "liquidity")["status"] == "unknown"
        assert _check(result, "penny")["status"] == "unknown"
        assert _check(result, "volatility")["status"] == "unknown"

    def test_khong_co_co_ban_thi_khong_ket_luan(self):
        result = screen_symbol("XYZ", df=_frame(), fundamentals=None)
        assert _check(result, "leverage")["status"] == "unknown"
        assert _check(result, "profitability")["status"] == "unknown"

    def test_thieu_du_lieu_khong_bi_tinh_la_dat(self):
        result = screen_symbol("XYZ", df=None, fundamentals=None, vn100=None)
        assert result["passed_count"] == 0
        assert result["verdict"] == "incomplete"


class TestKetLuanChung:
    def test_dat_het_thi_basic_ok(self):
        result = screen_symbol(
            "FPT",
            df=_frame(price=74_500, volume=1_000_000, swing_pct=1.9),
            fundamentals={"debt_to_equity": 0.46, "roe": 27.33},
            vn100={"FPT"},
        )
        assert result["verdict"] == "basic_ok"
        assert result["failed_count"] == 0

    def test_co_diem_hong_thi_caution(self):
        result = screen_symbol(
            "XYZ",
            df=_frame(price=3_600, volume=3_000, swing_pct=7.0),
            fundamentals={"debt_to_equity": 4.0, "roe": -2.0},
            vn100={"FPT"},
        )
        assert result["verdict"] == "caution"
        assert result["failed_count"] >= 5

    def test_caution_uu_tien_hon_incomplete(self):
        # Vừa có điểm hỏng vừa thiếu dữ liệu -> phải cảnh báo, không được im lặng.
        result = screen_symbol("XYZ", df=_frame(price=3_600), fundamentals=None, vn100={"FPT"})
        assert result["verdict"] == "caution"

    def test_luon_kem_canh_bao_khong_phai_khuyen_nghi(self):
        result = screen_symbol("FPT", df=_frame(), vn100={"FPT"})
        assert "KHÔNG có nghĩa là nên mua" in result["disclaimer"]

    def test_symbol_duoc_chuan_hoa(self):
        assert screen_symbol("  fpt ", df=_frame())["symbol"] == "FPT"

    def test_moi_tieu_chi_deu_co_nguong_va_giai_thich(self):
        result = screen_symbol("FPT", df=_frame(), vn100={"FPT"})
        for check in result["checks"]:
            assert check["threshold"], check["key"]
            assert check["explain"], check["key"]
