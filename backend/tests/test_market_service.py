"""Trạng thái phiên + chuẩn hoá chỉ số cơ bản (không chạm mạng)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from market_service import (
    VN_TZ,
    TTLCache,
    _latest_period_column,
    _parse_period,
    _row_value,
    format_fundamentals_for_prompt,
    market_status,
)


def _vn(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=VN_TZ)


class TestMarketStatus:
    @pytest.mark.parametrize(
        "when, expected",
        [
            (_vn(2026, 9, 7, 8, 59), "CLOSED"),   # thứ 2, trước giờ mở
            (_vn(2026, 9, 7, 9, 0), "OPEN"),      # mở cửa phiên sáng
            (_vn(2026, 9, 7, 11, 29), "OPEN"),
            (_vn(2026, 9, 7, 11, 30), "LUNCH"),   # nghỉ trưa
            (_vn(2026, 9, 7, 12, 59), "LUNCH"),
            (_vn(2026, 9, 7, 13, 0), "OPEN"),     # phiên chiều
            (_vn(2026, 9, 7, 14, 59), "OPEN"),
            (_vn(2026, 9, 7, 15, 0), "CLOSED"),   # đóng cửa
            (_vn(2026, 9, 12, 10, 0), "CLOSED"),  # thứ 7
            (_vn(2026, 9, 13, 10, 0), "CLOSED"),  # chủ nhật
        ],
    )
    def test_boundaries(self, when, expected):
        assert market_status(when)["status"] == expected

    def test_is_open_khop_voi_status(self):
        assert market_status(_vn(2026, 9, 7, 10, 0))["is_open"] is True
        assert market_status(_vn(2026, 9, 7, 12, 0))["is_open"] is False


class TestParsePeriod:
    @pytest.mark.parametrize(
        "label, expected",
        [
            ("2026-Q2", (2026, 2)),
            ("2018-Q4", (2018, 4)),
            ("2025", (2025, 4)),
            ("2025-Q4_1", (2025, 4)),  # vnstock thêm hậu tố khi trùng tên cột
            ("item_id", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse(self, label, expected):
        assert _parse_period(label) == expected

    def test_chon_ky_moi_nhat_khong_theo_thu_tu_cot(self):
        # KBS trả cột lộn xộn: Q2 mới nhất nhưng không nằm đầu.
        cols = ["item", "item_id", "2026-Q2", "2025-Q4", "2026-Q1", "2025-Q4_1"]
        assert _latest_period_column(cols) == "2026-Q2"

    def test_khong_co_cot_ky_tra_none(self):
        assert _latest_period_column(["item", "item_id"]) is None


class TestRowValue:
    @pytest.fixture()
    def ratios(self):
        # Cột trùng tên như dữ liệu thật của vnstock — _row_value phải chọn theo vị trí.
        return pd.DataFrame(
            [
                ["pe_ratio", 15.53, 20.96],
                ["roe", 5.89, 6.10],
                ["dividend_yield", 0.02, 0.02],
            ],
            columns=["item_id", "2026-Q2", "2026-Q2"],
        )

    def test_khop_chinh_xac_item_id(self, ratios):
        assert _row_value(ratios, ["pe_ratio"], "2026-Q2") == 15.53

    def test_item_id_khong_ton_tai_tra_none(self, ratios):
        assert _row_value(ratios, ["khong_co_that"], "2026-Q2") is None

    def test_candidate_rong_tra_none(self, ratios):
        assert _row_value(ratios, [], "2026-Q2") is None

    def test_candidate_ngan_khong_khop_substring(self, ratios):
        # "pe" < 4 ký tự nên không được phép khớp substring vào "pe_ratio":
        # nếu cho phép, "de" sẽ khớp nhầm hàng loạt chỉ số khác.
        assert _row_value(ratios, ["pe"], "2026-Q2") is None


class TestFormatFundamentalsForPrompt:
    def test_khong_kha_dung(self):
        out = format_fundamentals_for_prompt({"available": False, "reason": "rate limit"})
        assert "Không khả dụng" in out
        assert "rate limit" in out

    def test_co_du_lieu_ghi_ro_ky_va_nguon(self):
        out = format_fundamentals_for_prompt(
            {"available": True, "source": "KBS", "period": "2026-Q2", "pe": 15.53, "roe": 27.33}
        )
        assert "2026-Q2" in out and "KBS" in out
        assert "15.53" in out
        assert "N/A" in out  # các chỉ số thiếu phải là N/A, không được bịa

    def test_canh_bao_du_lieu_cu(self):
        out = format_fundamentals_for_prompt(
            {
                "available": True,
                "source": "VCI",
                "period": "2018-Q4",
                "pe": 11.6,
                "stale": True,
                "stale_note": "Nguồn VCI chỉ có số liệu đến 2018-Q4.",
            }
        )
        assert "2018-Q4" in out
        assert "LƯU Ý" in out


class TestTTLCache:
    def test_het_han_thi_mat_gia_tri(self):
        cache = TTLCache()
        cache.set("k", {"v": 1}, ttl_seconds=0)
        assert cache.get("k") is None

    def test_con_han_thi_giu_gia_tri(self):
        cache = TTLCache()
        cache.set("k", {"v": 1}, ttl_seconds=60)
        assert cache.get("k") == {"v": 1}

    def test_get_or_set_khong_cache_gia_tri_none(self):
        cache = TTLCache()
        calls = []

        def producer():
            calls.append(1)
            return None

        cache.get_or_set("k", 60, producer)
        cache.get_or_set("k", 60, producer)
        assert len(calls) == 2  # None không được cache, phải gọi lại
