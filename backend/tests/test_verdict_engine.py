"""
Kết luận mua / chờ / không mua — quy tắc Python công khai.

Test khoá ba điều quan trọng nhất với người sẽ dựa vào kết luận này để bỏ tiền:
  1. Trượt an toàn hoặc xu hướng giảm thì KHÔNG BAO GIỜ ra "có thể cân nhắc mua".
  2. Thiếu dữ liệu không được đẩy kết luận về phía mua.
  3. Tỷ lệ quá khứ luôn đi kèm mốc "mọi phiên" để thấy quy tắc có thêm gì không.
Không test nào gọi mạng.
"""
from __future__ import annotations

import pandas as pd

import verdict_engine as ve

GOOD_F = {"pe": 12.0, "roe": 20.0, "earnings_growth": 15.0}
STATS = {"pe": {"median": 15.0, "sample": 10}, "roe": {"median": 15.0, "sample": 10}}
SAFETY_KEYS = ("liquidity", "penny", "leverage", "profitability", "volatility", "coverage")


def _df(n=300, close0=50_000.0, step=100.0, ema50_ratio=0.95, ema200_ratio=0.9, rsi=60.0):
    close = [close0 + step * i for i in range(n)]
    rsi_values = rsi if isinstance(rsi, list) else [rsi] * n
    return pd.DataFrame(
        {
            "Close": close,
            "EMA50": [c * ema50_ratio for c in close],
            "EMA200": [c * ema200_ratio for c in close],
            "RSI": rsi_values,
        }
    )


def _safety(*fails):
    return {
        "checks": [
            {"key": k, "label": "tiêu chí " + k, "status": "fail" if k in fails else "pass"}
            for k in SAFETY_KEYS
        ]
    }


def _check(result, key):
    return next(c for c in result["checks"] if c["key"] == key)


class TestKetLuan:
    def test_xu_huong_tang_nen_tang_tot_thi_co_the_can_nhac_mua(self):
        r = ve.build_verdict("fpt", _df(), GOOD_F, _safety(), "CNTT", STATS)
        assert r["symbol"] == "FPT"
        assert r["verdict"] == "buy_consider"
        assert r["label"] == "Có thể cân nhắc mua"

    def test_truot_an_toan_thi_khong_nen_mua_du_xu_huong_dep(self):
        r = ve.build_verdict("XYZ", _df(), GOOD_F, _safety("liquidity"), None, STATS)
        assert r["verdict"] == "avoid"
        assert "an toàn" in r["headline"]

    def test_bien_do_va_ngoai_vn100_chi_la_diem_tru(self):
        r = ve.build_verdict("XYZ", _df(), GOOD_F, _safety("volatility", "coverage"), None, STATS)
        assert r["verdict"] == "buy_consider"

    def test_xu_huong_giam_thi_khong_nen_mua(self):
        down = _df(step=-100.0, ema50_ratio=1.05, ema200_ratio=1.1)
        r = ve.build_verdict("XYZ", down, GOOD_F, _safety(), None, STATS)
        assert r["verdict"] == "avoid"
        assert "giảm" in r["headline"]

    def test_qua_nong_thi_cho_them(self):
        r = ve.build_verdict("XYZ", _df(rsi=78.0), GOOD_F, _safety(), None, STATS)
        assert r["verdict"] == "wait"
        assert "quá nóng" in r["headline"]

    def test_nen_tang_yeu_thi_cho_them(self):
        weak = {"pe": 30.0, "roe": 5.0, "earnings_growth": -10.0}
        r = ve.build_verdict("XYZ", _df(), weak, _safety(), None, STATS)
        assert r["verdict"] == "wait"
        assert "nền tảng" in r["headline"]

    def test_chua_kiem_tra_duoc_an_toan_thi_khong_bao_gio_khuyen_mua(self):
        r = ve.build_verdict("XYZ", _df(), GOOD_F, None, None, STATS)
        assert r["verdict"] == "wait"
        assert _check(r, "safety")["status"] == "unknown"

    def test_khong_co_du_lieu_gia_thi_cho_them(self):
        r = ve.build_verdict("XYZ", None, GOOD_F, _safety(), None, STATS)
        assert r["verdict"] == "wait"
        assert r["history"]["available"] is False

    def test_luon_kem_quy_tac_va_canh_bao(self):
        r = ve.build_verdict("FPT", _df(), GOOD_F, _safety(), None, STATS)
        assert "EMA200" in r["rule"]
        assert "không phải lời khuyên" in r["disclaimer"]
        for c in r["checks"]:
            assert c["threshold"], c["key"]


class TestTieuChiNenTang:
    def test_dinh_gia_so_voi_trung_vi_nganh(self):
        def status(pe, stats=STATS):
            r = ve.build_verdict("X", _df(), {"pe": pe, "roe": 20, "earnings_growth": 5}, _safety(), None, stats)
            return _check(r, "valuation")["status"]

        assert status(16.0) == "pass"   # 16 <= 15 x 1,1
        assert status(17.0) == "fail"
        assert status(-5.0) == "unknown"  # đang lỗ: không có đắt/rẻ để so
        assert status(12.0, stats={}) == "unknown"  # không có trung vị ngành

    def test_roe_khong_co_trung_vi_thi_dung_nguong_10(self):
        def status(roe):
            r = ve.build_verdict("X", _df(), {"roe": roe}, _safety(), None, None)
            return _check(r, "quality")["status"]

        assert status(12.0) == "pass"
        assert status(8.0) == "fail"


class TestLichSu:
    def test_gia_tang_deu_thi_ty_le_tang_100(self):
        h = ve.build_verdict("X", _df(n=300), GOOD_F, _safety(), None, STATS)["history"]
        assert h["available"] is True
        assert h["samples"] == 300 - ve.FORWARD_SESSIONS
        assert h["up_ratio"] == 1.0
        assert h["baseline_up_ratio"] == 1.0

    def test_chi_dem_phien_cung_trang_thai_va_luon_kem_moc_moi_phien(self):
        # RSI xen kẽ 80 / 60: hôm nay (dòng cuối, RSI 60) chỉ khớp các phiên RSI 60.
        rsi = [80.0 if i % 2 == 0 else 60.0 for i in range(300)]
        h = ve.build_verdict("X", _df(n=300, rsi=rsi), GOOD_F, _safety(), None, STATS)["history"]
        assert h["available"] is True
        assert ve.MIN_HISTORY_SAMPLES <= h["samples"] < h["baseline_samples"]

    def test_it_mau_thi_khong_dua_ty_le(self):
        h = ve.build_verdict("X", _df(n=30), GOOD_F, _safety(), None, STATS)["history"]
        assert h["available"] is False
        assert "cần ít nhất" in h["reason"]

    def test_thieu_chi_bao_thi_khong_do(self):
        assert ve.history_check(_df(), {"above_ema200": None, "ema50_above_ema200": True, "not_overheated": True})["available"] is False


class TestDanhGiaLichSu:
    """Tỷ lệ quá khứ phải được đọc theo hướng của chính kết luận, không để người dùng tự suy."""

    H = {"available": True, "forward_sessions": 20, "samples": 300, "baseline_samples": 480}

    def test_co_the_mua_dung_khi_gia_tang_va_tot_hon_moc(self):
        r = ve._judge_history("buy_consider", {**self.H, "up_ratio": 0.7, "baseline_up_ratio": 0.5})
        assert r["hit_ratio"] == 0.7
        assert r["edge"] == "better"
        assert "giá cao hơn ở 70%" in r["summary"]

    def test_khong_nen_mua_dung_khi_gia_giam_va_noi_thang_neu_kem_hon_chon_bua(self):
        # Số thật của FPT ngày 2026-09-11: xu hướng giảm nhưng giá lại hay tăng hơn bình thường.
        r = ve._judge_history("avoid", {**self.H, "up_ratio": 0.4803, "baseline_up_ratio": 0.4109})
        assert r["hit_ratio"] == 0.5197
        assert r["baseline_hit_ratio"] == 0.5891
        assert r["edge"] == "worse"
        assert "giá thấp hơn ở 52%" in r["summary"]
        assert "tin kết luận này ít hơn" in r["summary"]

    def test_chenh_lech_nho_la_ngang_moc(self):
        r = ve._judge_history("buy_consider", {**self.H, "up_ratio": 0.53, "baseline_up_ratio": 0.5})
        assert r["edge"] == "same"

    def test_cho_them_chi_mo_ta(self):
        r = ve._judge_history("wait", {**self.H, "up_ratio": 0.6, "baseline_up_ratio": 0.5})
        assert r["edge"] is None and r["hit_ratio"] is None
        assert "60%" in r["summary"]

    def test_khong_do_duoc_thi_giu_nguyen(self):
        h = {"available": False, "reason": "thiếu"}
        assert ve._judge_history("avoid", h) == h

    def test_ket_luan_that_luon_co_cau_tom_tat(self):
        h = ve.build_verdict("X", _df(), GOOD_F, _safety(), None, STATS)["history"]
        assert h["available"] and h["summary"]
