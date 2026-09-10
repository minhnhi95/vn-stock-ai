"""Rổ chỉ số VN30/VN100 dùng làm fallback khi vnstock không phản hồi."""
from __future__ import annotations

from market_universe import VN30_SYMBOLS, vn100_fallback


class TestMarketUniverse:
    def test_vn30_du_30_ma_khong_trung(self):
        assert len(VN30_SYMBOLS) == 30
        assert len(set(VN30_SYMBOLS)) == 30

    def test_vn100_fallback_khong_trung_va_bao_gom_vn30(self):
        fallback = vn100_fallback()
        assert len(fallback) == len(set(fallback))
        assert set(VN30_SYMBOLS) <= set(fallback)

    def test_moi_ma_deu_dung_dinh_dang(self):
        # Ma VN co the chua so (HT1, NT2, PC1, TV2 deu nam trong VN100).
        from symbol_utils import is_vn_symbol

        assert all(is_vn_symbol(s) for s in vn100_fallback())
