"""
Tìm kiếm mã trên toàn sàn.

Index thật lấy từ vnstock nên test bơm index giả để không chạm mạng và để cố định
được thứ tự xếp hạng.
"""
from __future__ import annotations

import pytest

import search_service
from search_service import _fold, _is_stock_ticker, search_symbols


class TestFold:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Hòa Phát", "hoa phat"),
            ("Sữa Việt Nam", "sua viet nam"),
            ("Đức Giang", "duc giang"),
            ("VINAMILK", "vinamilk"),
        ],
    )
    def test_bo_dau_ha_chu_thuong(self, raw, expected):
        assert _fold(raw) == expected


class TestIsStockTicker:
    @pytest.mark.parametrize("symbol", ["FPT", "HPG", "VCB"])
    def test_hop_le(self, symbol):
        assert _is_stock_ticker(symbol) is True

    @pytest.mark.parametrize("symbol", ["A+ Fund", "FUEVFVND", "AB", "ABCD", "fpt", ""])
    def test_khong_hop_le(self, symbol):
        assert _is_stock_ticker(symbol) is False


def _entry(symbol, name, sector, alias=""):
    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "_name": _fold(f"{name} {alias}"),
        "_sector": _fold(sector),
    }


@pytest.fixture()
def index(monkeypatch):
    entries = [
        _entry("HPG", "Công ty Cổ phần Tập đoàn Hòa Phát", "Tài nguyên Cơ bản", "Hoà Phát"),
        _entry("HPA", "Công ty Cổ phần Phát triển Nông nghiệp Hoà Phát", "Thực phẩm và đồ uống"),
        _entry("VNM", "Công ty Cổ phần Sữa Việt Nam", "Thực phẩm và đồ uống", "Vinamilk"),
        _entry("VND", "Công ty Cổ phần Chứng khoán VNDirect", "Dịch vụ tài chính", "VNDirect"),
        _entry("ACB", "Ngân hàng Thương mại Cổ phần Á Châu", "Ngân hàng", "ACB Á Châu"),
    ]
    monkeypatch.setattr(search_service, "get_index", lambda: entries)
    # VN30 quyết định thứ tự phụ; cố định để test không phụ thuộc mạng.
    monkeypatch.setattr(
        search_service, "_liquidity_rank", lambda symbol: 0 if symbol in {"HPG", "VNM", "ACB"} else 2
    )
    return entries


class TestSearchSymbols:
    def test_tim_theo_ma(self, index):
        assert search_symbols("HPG")[0]["symbol"] == "HPG"

    def test_tim_khong_dau_ra_ten_co_dau(self, index):
        assert "HPG" in [r["symbol"] for r in search_symbols("hoa phat")]

    def test_ma_thanh_khoan_cao_len_truoc_khi_cung_muc_khop(self, index):
        # HPG (VN30) phải trên HPA (công ty con) dù cả hai đều khớp "hoà phát".
        results = [r["symbol"] for r in search_symbols("hoa phat")]
        assert results.index("HPG") < results.index("HPA")

    def test_ten_thuong_hieu_tim_duoc(self, index):
        # "Vinamilk" không nằm trong tên pháp nhân — phải qua bảng alias.
        assert [r["symbol"] for r in search_symbols("vinamilk")] == ["VNM"]

    def test_tim_theo_nganh(self, index):
        assert "ACB" in [r["symbol"] for r in search_symbols("ngan hang")]

    def test_khop_ten_xep_tren_khop_nganh(self, index):
        # "Á Châu" ở tên ACB; các mã khác chỉ có thể khớp qua ngành.
        assert search_symbols("a chau")[0]["symbol"] == "ACB"

    def test_khong_phan_biet_hoa_thuong(self, index):
        assert search_symbols("hpg")[0]["symbol"] == "HPG"

    def test_khong_khop_gi_tra_rong(self, index):
        # Quan trọng: có index thật thì KHÔNG được bịa ra mã 3 chữ cái.
        assert search_symbols("ZZZ") == []

    def test_ton_trong_limit(self, index):
        assert len(search_symbols("cong ty", limit=2)) <= 2

    def test_query_rong_tra_ma_pho_bien(self, index):
        results = [r["symbol"] for r in search_symbols("")]
        assert results
        assert set(results) <= {e["symbol"] for e in index}

    def test_khong_lo_field_noi_bo(self, index):
        results = search_symbols("hoa phat")
        assert results
        assert all(not key.startswith("_") for r in results for key in r)


class TestFallbackKhiIndexRong:
    def test_van_tim_duoc_trong_danh_sach_tinh(self, monkeypatch):
        monkeypatch.setattr(search_service, "get_index", lambda: [])
        monkeypatch.setattr(search_service, "_liquidity_rank", lambda symbol: 2)
        assert [r["symbol"] for r in search_symbols("FPT")] == ["FPT"]

    def test_alias_van_hoat_dong_o_fallback(self, monkeypatch):
        monkeypatch.setattr(search_service, "get_index", lambda: [])
        monkeypatch.setattr(search_service, "_liquidity_rank", lambda symbol: 2)
        assert [r["symbol"] for r in search_symbols("vinamilk")] == ["VNM"]
