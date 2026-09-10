"""
Parser cho lịch sự kiện, heatmap ngành và khối ngoại.

Đây đều là chỗ code phải bám vào schema vnstock — thứ đã đổi giữa các version và
từng làm ba panel hiển thị rỗng suốt. Test khoá lại schema thật đang dùng.
"""
from __future__ import annotations

import pandas as pd
import pytest

from calendar_service import _classify_event
from foreign_service import _flatten_price_board
from sector_service import _is_stock_ticker


class TestClassifyEvent:
    @pytest.mark.parametrize(
        "category, expected",
        [
            ("DIVIDEND", "dividend"),
            ("SHAREHOLDER_MEETING", "agm"),
            ("MAJOR_SHAREHOLDER_TRADING", "insider"),
            ("BUSINESS_RESULT", "earnings"),
        ],
    )
    def test_category_duoc_uu_tien(self, category, expected):
        # Tên sự kiện cố tình gây nhiễu để chứng minh category thắng.
        assert _classify_event("Đại hội Đồng Cổ đông", "", category) == expected

    def test_khong_co_category_thi_doc_ten(self):
        assert _classify_event("Trả cổ tức bằng tiền mặt") == "dividend"
        assert _classify_event("Đại hội Đồng Cổ đông") == "agm"
        assert _classify_event("Báo cáo tài chính quý 2") == "earnings"

    def test_category_la_khong_biet_thi_lui_ve_ten(self):
        assert _classify_event("Trả cổ tức bằng tiền mặt", "", "OTHER") == "dividend"

    def test_su_kien_khong_phan_loai_duoc(self):
        assert _classify_event("Niêm yết bổ sung cổ phiếu", "", "OTHER") == "other"


class TestIsStockTicker:
    # HT1/PC1 la ma that co chua so — khong duoc loai.
    @pytest.mark.parametrize("symbol", ["FPT", "HPG", "VCB", "HT1", "PC1"])
    def test_ma_co_phieu_hop_le(self, symbol):
        assert _is_stock_ticker(symbol) is True

    @pytest.mark.parametrize(
        "symbol",
        ["A+ Fund", "FUEVFVND", "CVNM2314", "AB", "ABCD", "fpt", "1AB", ""],
    )
    def test_loai_quy_chung_quyen_va_ma_sai_dinh_dang(self, symbol):
        # Listing trả cả chứng chỉ quỹ/chứng quyền; heatmap chỉ nên tính cổ phiếu.
        assert _is_stock_ticker(symbol) is False


class TestFlattenPriceBoard:
    def test_multiindex_duoc_ep_ve_ten_cap_cuoi(self):
        df = pd.DataFrame(
            [[1, 2, 3]],
            columns=pd.MultiIndex.from_tuples(
                [("listing", "symbol"), ("match", "foreign_buy_volume"), ("match", "match_price")]
            ),
        )
        flat = _flatten_price_board(df)
        assert flat["symbol"] == ("listing", "symbol")
        assert flat["foreign_buy_volume"] == ("match", "foreign_buy_volume")
        assert flat["match_price"] == ("match", "match_price")

    def test_ten_cap_cuoi_trung_thi_giu_cot_dau_tien(self):
        # price_board có 'bid_count' ở cả nhóm bid_ask lẫn match.
        df = pd.DataFrame(
            [[1, 2]],
            columns=pd.MultiIndex.from_tuples([("bid_ask", "bid_count"), ("match", "bid_count")]),
        )
        assert _flatten_price_board(df)["bid_count"] == ("bid_ask", "bid_count")

    def test_cot_phang_van_hoat_dong(self):
        df = pd.DataFrame([[1, 2]], columns=["symbol", "foreign_buy_volume"])
        flat = _flatten_price_board(df)
        assert flat["symbol"] == "symbol"
        assert flat["foreign_buy_volume"] == "foreign_buy_volume"
