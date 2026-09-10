"""
Parse giao dịch nội bộ từ Company.events().

Toàn bộ thông tin nằm trong chuỗi `event_title_vi` nên regex là điểm dễ vỡ nhất
của module — test bám sát các biến thể chuỗi thật đã gặp.
"""
from __future__ import annotations

import pytest

from insider_service import (
    _is_insider_event,
    _normalize_insider_row,
    _parse_shares,
    summarize_deals,
)


class TestIsInsiderEvent:
    def test_category_giao_dich_co_dong_lon(self):
        assert _is_insider_event({"category": "MAJOR_SHAREHOLDER_TRADING"}) is True

    @pytest.mark.parametrize("category", ["DIVIDEND", "SHAREHOLDER_MEETING", "OTHER"])
    def test_category_khac_khong_phai_insider(self, category):
        assert _is_insider_event({"category": category}) is False

    def test_khong_co_category_thi_doc_ten_su_kien(self):
        assert _is_insider_event({"event_name_vi": "Giao dịch nội bộ: Giao dịch cá nhân"}) is True
        assert _is_insider_event({"event_name_vi": "Trả cổ tức bằng tiền mặt"}) is False

    def test_row_rong_khong_phai_insider(self):
        assert _is_insider_event({}) is False


class TestParseShares:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("428,368", 428368),
            ("1.000.000", 1000000),
            ("50000", 50000),
            ("", None),
            ("N/A", None),
        ],
    )
    def test_parse(self, raw, expected):
        assert _parse_shares(raw) == expected


def _row(title, name="Giao dịch nội bộ: Giao dịch cá nhân", **extra):
    base = {
        "event_title_vi": title,
        "event_name_vi": name,
        "category": "MAJOR_SHAREHOLDER_TRADING",
        "start_date": "2026-06-24T00:00:00",
        "end_date": "2026-06-29T00:00:00",
        "public_date": "2026-06-29T00:00:00",
    }
    base.update(extra)
    return base


class TestNormalizeInsiderRow:
    def test_dang_ky_mua(self):
        deal = _normalize_insider_row("FPT", _row("Nguyễn Văn Khoa - Đăng kí Mua 428,368 FPT"))
        assert deal["person"] == "Nguyễn Văn Khoa"
        assert deal["type"] == "BUY"
        assert deal["shares"] == 428368
        assert deal["registered"] is True
        assert deal["date"] == "2026-06-24"

    def test_dang_ky_ban(self):
        deal = _normalize_insider_row("HPG", _row("Nguyễn Ngọc Quang - Đăng kí Bán 6,600,000 HPG"))
        assert deal["type"] == "SELL"
        assert deal["shares"] == 6600000

    def test_da_thuc_hien_khong_phai_dang_ky(self):
        deal = _normalize_insider_row("HPG", _row("Trần Vũ Minh - Đã bán 1.000.000 HPG"))
        assert deal["type"] == "SELL"
        assert deal["registered"] is False

    def test_ten_to_chuc_co_dau_gach_ngang_van_parse_duoc(self):
        deal = _normalize_insider_row("HPG", _row("CTCP Đầu tư ABC - Đăng ký Mua 50,000 HPG"))
        assert deal["type"] == "BUY"
        assert deal["shares"] == 50000

    def test_tieu_de_khong_khop_van_giu_dong(self):
        # Thà hiện "có hoạt động nội bộ nhưng thiếu số liệu" còn hơn im lặng bỏ.
        deal = _normalize_insider_row("FPT", _row("Thông báo giao dịch bất thường"))
        assert deal is not None
        assert deal["type"] == "UNKNOWN"
        assert deal["shares"] is None

    def test_tieu_de_rong_thi_bo(self):
        assert _normalize_insider_row("FPT", _row("")) is None

    def test_gia_tri_chua_duoc_uoc_luong_o_buoc_nay(self):
        deal = _normalize_insider_row("FPT", _row("A B - Đăng kí Mua 100 FPT"))
        assert deal["value"] is None
        assert deal["value_estimated"] is False


class TestSummarizeDeals:
    @pytest.fixture()
    def deals(self):
        return [
            {"type": "BUY", "shares": 100, "value": 7_000_000.0, "value_estimated": True},
            {"type": "BUY", "shares": 50, "value": 3_500_000.0, "value_estimated": True},
            {"type": "SELL", "shares": 30, "value": 2_100_000.0, "value_estimated": True},
        ]

    def test_tong_mua_ban_va_net(self, deals):
        summary = summarize_deals(deals)
        assert summary["buy_value"] == 10_500_000.0
        assert summary["sell_value"] == 2_100_000.0
        assert summary["net"] == 8_400_000.0

    def test_tong_theo_so_luong(self, deals):
        summary = summarize_deals(deals)
        assert summary["buy_shares"] == 150
        assert summary["sell_shares"] == 30
        assert summary["net_shares"] == 120
        assert summary["count"] == 3

    def test_danh_dau_gia_tri_uoc_luong(self, deals):
        assert summarize_deals(deals)["value_estimated"] is True
        assert summarize_deals([{"type": "BUY", "shares": 1, "value": 1.0}])["value_estimated"] is False

    def test_danh_sach_rong(self):
        summary = summarize_deals([])
        assert summary["net"] == 0
        assert summary["count"] == 0

    def test_deal_thieu_gia_tri_khong_lam_vo_tong(self):
        summary = summarize_deals([{"type": "BUY", "shares": None, "value": None}])
        assert summary["buy_value"] == 0
        assert summary["buy_shares"] == 0
