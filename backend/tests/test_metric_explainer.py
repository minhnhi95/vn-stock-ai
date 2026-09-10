"""
Giải thích chỉ số cơ bản bằng tiếng Việt + so sánh ngành.

Hai thứ test khoá chặt nhất:
  1. Câu chữ luôn khớp DẤU của con số — nói "tăng" khi số âm là sai nguy hiểm
     hơn là không nói gì.
  2. Không bao giờ so sánh với một trung vị dựng từ quá ít mã, và không bao giờ
     phát ra câu mang tính khuyến nghị mua/bán.
"""
from __future__ import annotations

import pytest

from metric_explainer import (
    INLINE_TOLERANCE,
    MIN_SECTOR_SAMPLE,
    _vn_number,
    explain_fundamentals,
)


def _f(**kwargs):
    return {"available": True, **kwargs}


def _item(items, key):
    return next(i for i in items if i["key"] == key)


class TestDinhDangSoVietNam:
    def test_dau_phay_la_thap_phan(self):
        assert _vn_number(15.53) == "15,53"

    def test_dau_cham_la_phan_cach_nghin(self):
        assert _vn_number(25141, 0) == "25.141"

    def test_so_lon_co_ca_hai(self):
        assert _vn_number(1234567.89) == "1.234.567,89"


class TestCauGiaiThich:
    def test_pe_noi_ro_bao_lau_hoan_von(self):
        item = _item(explain_fundamentals(_f(pe=15.53)), "pe")
        assert "15,53 đồng" in item["plain"]
        assert "15,5 năm" in item["plain"]

    def test_pe_am_khong_bia_ra_so_nam_hoan_von(self):
        # P/E âm mà vẫn in "cần -4,2 năm để hoàn vốn" là câu vô nghĩa.
        item = _item(explain_fundamentals(_f(pe=-4.2)), "pe")
        assert "lỗ" in item["plain"]
        assert "năm để hoàn vốn" not in item["plain"]
        assert "-4,2" not in item["plain"]

    def test_roe_duong_noi_lam_ra_bao_nhieu(self):
        item = _item(explain_fundamentals(_f(roe=27.33)), "roe")
        assert "27,3 đồng" in item["plain"]

    def test_roe_am_noi_la_lo(self):
        assert "lỗ" in _item(explain_fundamentals(_f(roe=-3.0)), "roe")["plain"]

    def test_tang_truong_am_noi_la_giam(self):
        item = _item(explain_fundamentals(_f(revenue_growth=-8.19)), "revenue_growth")
        assert "giảm 8,2%" in item["plain"]
        assert "tăng" not in item["plain"]

    def test_tang_truong_duong_noi_la_tang(self):
        item = _item(explain_fundamentals(_f(revenue_growth=8.19)), "revenue_growth")
        assert "tăng 8,2%" in item["plain"]

    def test_bien_lai_am_noi_la_lo(self):
        item = _item(explain_fundamentals(_f(net_margin=-12.5)), "net_margin")
        assert "lỗ 12,5 đồng" in item["plain"]

    def test_co_tuc_thap_hon_tiet_kiem_thi_noi_ro(self):
        item = _item(explain_fundamentals(_f(dividend_yield=2.0)), "dividend_yield")
        assert "Thấp hơn lãi gửi tiết kiệm" in item["plain"]

    def test_co_tuc_cao_hon_van_kem_canh_bao_gia_co_the_giam(self):
        item = _item(explain_fundamentals(_f(dividend_yield=8.0)), "dividend_yield")
        assert "Cao hơn lãi gửi tiết kiệm" in item["plain"]
        assert "giá cổ phiếu có thể giảm" in item["plain"]

    def test_khong_tra_co_tuc_khong_bi_goi_la_xau(self):
        item = _item(explain_fundamentals(_f(dividend_yield=0.0)), "dividend_yield")
        assert "Không hẳn là xấu" in item["plain"]

    def test_beta_cao_noi_bien_dong_manh_hon(self):
        assert "mạnh hơn" in _item(explain_fundamentals(_f(beta=1.4)), "beta")["plain"]

    def test_beta_thap_noi_bien_dong_nhe_hon(self):
        assert "nhẹ hơn" in _item(explain_fundamentals(_f(beta=0.6)), "beta")["plain"]


class TestSoSanhNganh:
    SECTOR = "Công nghệ Thông tin"

    def _stats(self, median, sample=10, metric="pe"):
        return {metric: {"median": median, "sample": sample}}

    def test_pe_thap_hon_nganh_la_re_hon(self):
        items = explain_fundamentals(_f(pe=15.0), self.SECTOR, self._stats(20.0))
        item = _item(items, "pe")
        assert item["comparison"] == "below"
        assert item["comparison_text"].startswith("Rẻ hơn")

    def test_pe_cao_hon_nganh_la_dat_hon(self):
        items = explain_fundamentals(_f(pe=30.0), self.SECTOR, self._stats(20.0))
        assert _item(items, "pe")["comparison_text"].startswith("Đắt hơn")

    def test_roe_cao_hon_nganh_la_cao_hon_khong_phai_re_hon(self):
        # Cùng hướng "lớn hơn" nhưng cách đọc khác hẳn P/E: ROE lớn không liên
        # quan gì tới giá đắt hay rẻ.
        items = explain_fundamentals(
            _f(roe=27.0), self.SECTOR, self._stats(15.0, metric="roe")
        )
        assert _item(items, "roe")["comparison_text"].startswith("Cao hơn")

    def test_no_cao_hon_nganh_doc_la_vay_nhieu_hon(self):
        items = explain_fundamentals(
            _f(debt_to_equity=1.5), self.SECTOR, self._stats(0.5, metric="debt_to_equity")
        )
        assert _item(items, "debt_to_equity")["comparison_text"].startswith("Vay nhiều hơn")

    def test_chenh_nho_thi_coi_la_ngang_nganh(self):
        # Trong khoảng dung sai -> không nên bắt người đọc suy diễn từ nhiễu.
        items = explain_fundamentals(
            _f(pe=20.0 * (1 + INLINE_TOLERANCE / 2)), self.SECTOR, self._stats(20.0)
        )
        assert _item(items, "pe")["comparison"] == "inline"

    def test_it_mau_thi_khong_so_sanh(self):
        items = explain_fundamentals(
            _f(pe=15.0), self.SECTOR, self._stats(20.0, sample=MIN_SECTOR_SAMPLE - 1)
        )
        item = _item(items, "pe")
        assert item["sector"] is None
        assert item["comparison_text"] is None

    def test_khong_co_bang_nganh_thi_van_co_giai_thich(self):
        item = _item(explain_fundamentals(_f(pe=15.0)), "pe")
        assert item["plain"]
        assert item["comparison_text"] is None

    def test_eps_khong_bao_gio_so_voi_nganh(self):
        # EPS phụ thuộc số cổ phiếu lưu hành nên so ngang là vô nghĩa.
        items = explain_fundamentals(
            _f(eps=5988.0), self.SECTOR, self._stats(3000.0, metric="eps")
        )
        item = _item(items, "eps")
        assert item["comparison"] is None
        assert item["comparison_text"] is None

    def test_trung_vi_bang_0_khong_lam_chia_cho_0(self):
        items = explain_fundamentals(
            _f(revenue_growth=5.0), self.SECTOR, self._stats(0.0, metric="revenue_growth")
        )
        assert _item(items, "revenue_growth")["comparison"] is None


class TestKhongPhaiKhuyenNghi:
    BANNED = ["nên mua", "nên bán", "khuyến nghị", "mục tiêu giá", "chốt lời", "cắt lỗ"]

    def test_khong_cau_nao_ra_lenh_mua_ban(self):
        items = explain_fundamentals(
            _f(
                pe=8.0,
                pb=0.9,
                roe=30.0,
                roa=15.0,
                net_margin=25.0,
                gross_margin=40.0,
                debt_to_equity=0.2,
                dividend_yield=9.0,
                revenue_growth=40.0,
                earnings_growth=50.0,
                eps=6000.0,
                bvps=25000.0,
                beta=0.8,
            ),
            "Công nghệ Thông tin",
            {m: {"median": 20.0, "sample": 12} for m in ("pe", "pb", "roe")},
        )
        blob = " ".join(i["plain"] + i["caveat"] + (i["comparison_text"] or "") for i in items)
        for phrase in self.BANNED:
            assert phrase not in blob.lower(), phrase

    def test_moi_chi_so_deu_co_caveat(self):
        items = explain_fundamentals(_f(pe=15.0, roe=20.0, beta=1.0))
        assert items
        for item in items:
            assert item["caveat"], item["key"]


class TestDauVaoHong:
    def test_khong_co_du_lieu_thi_tra_rong(self):
        assert explain_fundamentals(None) == []
        assert explain_fundamentals({"available": False, "reason": "x"}) == []

    def test_chi_so_thieu_thi_bo_qua_khong_bia(self):
        items = explain_fundamentals(_f(pe=15.0, roe=None))
        assert [i["key"] for i in items] == ["pe"]

    def test_nan_bi_bo_qua(self):
        assert explain_fundamentals(_f(pe=float("nan"))) == []

    def test_gia_tri_khong_phai_so_bi_bo_qua(self):
        assert explain_fundamentals(_f(pe="N/A")) == []

    @pytest.mark.parametrize("value", [0.0, -1.0, 1e6])
    def test_gia_tri_bien_khong_lam_vo(self, value):
        items = explain_fundamentals(_f(pe=value, roe=value, debt_to_equity=abs(value)))
        for item in items:
            assert isinstance(item["plain"], str) and item["plain"]


class TestBangTrungViNganh:
    """Bảng trung vị nằm trên đĩa và do job nền sinh ra — nó có thể thiếu hoặc hỏng."""

    def test_thieu_file_thi_van_giai_thich_duoc(self, tmp_path, monkeypatch):
        import metric_explainer as me

        monkeypatch.setattr(me, "_BENCHMARK_PATH", str(tmp_path / "khong-co.json"))
        monkeypatch.setattr(me, "_benchmarks_cache", None)
        result = me.explain_for_symbol("FPT", _f(pe=15.0))
        assert result["sector"] is None
        assert result["items"][0]["plain"]

    def test_file_hong_khong_lam_sap_endpoint(self, tmp_path, monkeypatch):
        import metric_explainer as me

        bad = tmp_path / "hong.json"
        bad.write_text("{ day khong phai json", encoding="utf-8")
        monkeypatch.setattr(me, "_BENCHMARK_PATH", str(bad))
        monkeypatch.setattr(me, "_benchmarks_cache", None)
        result = me.explain_for_symbol("FPT", _f(pe=15.0))
        assert result["sector"] is None
        assert len(result["items"]) == 1

    def test_ghep_dung_nganh_cua_ma(self, tmp_path, monkeypatch):
        import json

        import metric_explainer as me

        table = tmp_path / "bench.json"
        table.write_text(
            json.dumps(
                {
                    "generated_at": "2026-09-10",
                    "sectors": {"Ngân hàng": {"metrics": {"pe": {"median": 8.0, "sample": 18}}}},
                    "symbol_sector": {"VCB": "Ngân hàng"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(me, "_BENCHMARK_PATH", str(table))
        monkeypatch.setattr(me, "_benchmarks_cache", None)

        result = me.explain_for_symbol("vcb", _f(pe=12.38))
        assert result["sector"] == "Ngân hàng"
        assert result["benchmark_date"] == "2026-09-10"
        assert _item(result["items"], "pe")["comparison"] == "above"

        # Mã ngoài bảng thì không mượn trung vị của ngành khác.
        assert me.explain_for_symbol("ZZZ", _f(pe=12.38))["sector"] is None


class TestDienDatKhoangCach:
    """
    Cách nói "hơn ngành bao nhiêu" phải giữ được ý nghĩa khi trung vị ngành gần 0.

    Đây là chỗ dễ sinh ra câu vô nghĩa nhất: ROE 27,33% so với trung vị ngành
    4,93% ra "cao hơn 454%", còn biên lãi ròng ra "cao hơn 1.188%" — đúng số học
    nhưng người đọc sẽ hiểu thành "lãi gấp 12 lần ngành".
    """

    SECTOR = "Công nghệ Thông tin"

    def _run(self, sector_median, metric, value):
        items = explain_fundamentals(
            _f(**{metric: value}), self.SECTOR, {metric: {"median": sector_median, "sample": 10}}
        )
        return _item(items, metric)["comparison_text"]

    def test_chi_so_phan_tram_so_bang_diem_phan_tram(self):
        text = self._run(4.93, "roe", 27.33)
        assert "22,4 điểm %" in text
        assert "454" not in text

    def test_bien_lai_cung_dung_diem_phan_tram(self):
        assert "15,6 điểm %" in self._run(1.31, "net_margin", 16.87)

    def test_tang_truong_cung_dung_diem_phan_tram(self):
        assert "điểm %" in self._run(25.83, "revenue_growth", 8.19)

    def test_chi_so_ty_le_lech_vua_thi_dung_phan_tram(self):
        # P/E 12,38 so với 8,12 -> 52%, con số này vẫn dễ hình dung.
        assert "52%" in self._run(8.12, "pe", 12.38)

    def test_chi_so_ty_le_lech_qua_lon_thi_noi_gap_may_lan(self):
        # P/B 3,70 so với 0,94 -> "294%" khó hình dung hơn "gấp 3,9 lần".
        text = self._run(0.94, "pb", 3.70)
        assert "gấp 3,9 lần" in text
        assert "%" not in text.split("(")[0]

    def test_khong_bao_gio_in_phan_tram_bon_chu_so(self):
        import re

        for metric, median, value in [
            ("net_margin", 1.31, 16.87),
            ("roa", 1.58, 11.54),
            ("earnings_growth", 2.10, 16.56),
            ("pb", 0.05, 3.70),
        ]:
            text = self._run(median, metric, value)
            assert not re.search(r"\d\.\d{3}%", text), (metric, text)


class TestMocLaiTietKiem:
    """
    Lãi tiết kiệm là con số duy nhất trong module không đến từ báo cáo tài chính,
    nên cũng là con số duy nhất sẽ cũ đi. Nó phải đổi được mà không sửa code, và
    một giá trị rác trong env không được làm sai câu chữ.
    """

    def _rate(self, monkeypatch, value):
        import importlib

        import metric_explainer as me

        if value is None:
            monkeypatch.delenv("SAVINGS_RATE_PCT", raising=False)
        else:
            monkeypatch.setenv("SAVINGS_RATE_PCT", value)
        return importlib.reload(me)

    def test_mac_dinh_la_5_phan_tram(self, monkeypatch):
        assert self._rate(monkeypatch, None).SAVINGS_RATE_PCT == 5.0

    def test_doi_duoc_qua_bien_moi_truong(self, monkeypatch):
        me = self._rate(monkeypatch, "7.5")
        assert me.SAVINGS_RATE_PCT == 7.5
        item = next(
            i
            for i in me.explain_fundamentals({"available": True, "dividend_yield": 6.0})
            if i["key"] == "dividend_yield"
        )
        # 6% cổ tức giờ THẤP hơn mốc 7,5% — câu chữ phải đổi theo.
        assert "Thấp hơn lãi gửi tiết kiệm" in item["plain"]
        assert "8%/năm" in item["plain"]

    @pytest.mark.parametrize("bad", ["", "abc", "-3", "0", "500"])
    def test_gia_tri_vo_ly_quay_ve_mac_dinh(self, monkeypatch, bad):
        assert self._rate(monkeypatch, bad).SAVINGS_RATE_PCT == 5.0

    def test_tra_module_ve_mac_dinh_sau_khi_test(self, monkeypatch):
        # Các test khác trong file dựa vào mốc 5% — đảm bảo reload cuối trả về đúng.
        assert self._rate(monkeypatch, None).SAVINGS_RATE_PCT == 5.0
