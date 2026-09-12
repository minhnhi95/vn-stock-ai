"""
Kế hoạch vào lệnh — số cổ phiếu, cắt lỗ, tiền mất tối đa.

Test khoá những chỗ mà sai một con số là mất tiền thật:
  1. Mất khi chạm cắt lỗ không được vượt mức người dùng chấp nhận.
  2. Số lượng luôn là bội số của lô 100 và không vượt trần tỷ trọng một mã.
  3. Thiếu dữ liệu hoặc thiếu vốn thì nói rõ vì sao, không trả số bừa.
Không test nào gọi mạng.
"""
from __future__ import annotations

import pandas as pd
import pytest

import trade_plan as tp


def _df(n=60, close=50_000.0, span=1_000.0, low_floor=None):
    """Giá đi ngang quanh `close`, biên độ mỗi phiên `span`."""
    closes = [close] * n
    highs = [c + span / 2 for c in closes]
    lows = [c - span / 2 for c in closes]
    if low_floor is not None:
        lows[-5] = low_floor  # một phiên thủng sâu, nằm trong 20 phiên gần nhất
    return pd.DataFrame({"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": [1e6] * n})


class TestCatLo:
    def test_atr_tinh_ca_phan_nhay_gap(self):
        df = _df(n=30)
        assert tp.atr(df) == pytest.approx(1_000.0, rel=0.01)

    def test_thieu_du_lieu_thi_khong_co_atr(self):
        assert tp.atr(_df(n=5)) is None

    def test_lay_muc_thap_hon_giua_atr_va_day_20_phien(self):
        df = _df(close=50_000.0, span=1_000.0)  # ATR 1.000 -> cắt lỗ 48.000; đáy 20 phiên 49.500
        stop = tp.stop_price(df, 50_000.0)
        assert stop["price"] == 48_000.0
        assert "ATR" in stop["method"]

        deep = _df(close=50_000.0, span=1_000.0, low_floor=45_000.0)
        stop2 = tp.stop_price(deep, 50_000.0)
        assert stop2["price"] == 45_000.0
        assert "Đáy" in stop2["method"]
        assert stop2["distance_pct"] == 10.0


class TestSoLuong:
    def test_khong_bao_gio_mat_qua_muc_chap_nhan(self):
        # Vốn 100 triệu, rủi ro 1% = 1 triệu, cắt lỗ cách 2.000 đ -> công thức ra 500 cp,
        # nhưng 500 cp = 25 triệu = 25% vốn nên trần 20% kéo xuống 400 cp. Mất ít hơn mức
        # chấp nhận là đúng; mất NHIỀU hơn mới là sai.
        p = tp.build_plan("FPT", 50_000.0, _df(), capital=100_000_000, risk_pct=1.0)
        assert p["available"] is True
        assert p["shares"] == 400 and p["capped"] is True
        assert p["stop"]["price"] == 48_000.0
        assert p["loss_if_stopped"] <= 1_000_000
        assert p["loss_pct_of_capital"] <= 1.0

    def test_lo_sat_muc_chap_nhan_khi_tran_khong_chan(self):
        # Vốn 250 triệu, rủi ro 0,4% = 1 triệu; cắt lỗ cách 2.000 đ -> 500 cp = 25 triệu,
        # tức 10% vốn nên trần 20% không chặn.
        p = tp.build_plan("FPT", 50_000.0, _df(), capital=250_000_000, risk_pct=0.4)
        assert p["capped"] is False and p["shares"] == 500
        # Lỗ gồm cả phí mua và phí bán nên nhỉnh hơn 1 triệu một chút.
        assert 1_000_000 <= p["loss_if_stopped"] <= 1_120_000
        assert p["loss_pct_of_capital"] <= 0.45

    def test_lam_tron_xuong_lo_thi_mat_it_hon_chu_khong_nhieu_hon(self):
        # Cắt lỗ xa (ATR lớn): 1 triệu mua được 125 cp, làm tròn xuống 100.
        p = tp.build_plan("FPT", 50_000.0, _df(span=4_000.0), capital=100_000_000, risk_pct=1.0)
        assert p["shares"] == 100
        assert p["loss_if_stopped"] < p["risk_budget"]

    def test_luon_la_boi_so_lo_100(self):
        for risk in (0.3, 0.7, 1.0, 2.5):
            p = tp.build_plan("FPT", 50_000.0, _df(), capital=37_000_000, risk_pct=risk)
            if p["available"]:
                assert p["shares"] % tp.LOT_SIZE == 0

    def test_tran_ty_trong_mot_ma(self):
        # Cắt lỗ rất gần (biên độ nhỏ) khiến công thức cho phép mua quá nhiều.
        p = tp.build_plan("FPT", 50_000.0, _df(span=100.0), capital=100_000_000, risk_pct=2.0)
        assert p["capped"] is True
        assert p["capital_pct"] <= tp.MAX_POSITION_PCT
        assert any("20% vốn" in w for w in p["warnings"])

    def test_rui_ro_bi_gioi_han_trong_khoang_cho_phep(self):
        assert tp.build_plan("X", 50_000.0, _df(), 100_000_000, risk_pct=99)["risk_pct"] == tp.MAX_RISK_PCT
        assert tp.build_plan("X", 50_000.0, _df(), 100_000_000, risk_pct=0)["risk_pct"] == tp.MIN_RISK_PCT

    def test_muc_tieu_chot_loi_gap_doi_khoang_cat_lo(self):
        p = tp.build_plan("FPT", 50_000.0, _df(), capital=100_000_000, risk_pct=1.0)
        assert p["target"]["price"] == 54_000.0  # 50.000 + 2 x 2.000


class TestKhongTinhDuoc:
    def test_khong_co_von_thi_noi_ro(self):
        p = tp.build_plan("FPT", 50_000.0, _df(), capital=0)
        assert p["available"] is False and "vốn" in p["reason"]

    def test_khong_co_gia(self):
        assert tp.build_plan("FPT", None, _df(), capital=1e8)["available"] is False

    def test_thieu_du_lieu_gia_thi_khong_dat_duoc_cat_lo(self):
        p = tp.build_plan("FPT", 50_000.0, _df(n=5), capital=1e8)
        assert p["available"] is False and "cắt lỗ" in p["reason"]

    def test_von_nho_hon_mot_lo_thi_giai_thich(self):
        p = tp.build_plan("VCB", 100_000.0, _df(close=100_000.0, span=2_000.0), capital=3_000_000, risk_pct=1.0)
        assert p["available"] is False
        assert "một lô" in p["reason"] and "10.000.000 đ" in p["reason"]


class TestCanhBao:
    def test_ma_dao_dong_manh(self):
        p = tp.build_plan("HOT", 50_000.0, _df(span=6_000.0), capital=1e9, risk_pct=1.0)
        assert any("dao động mạnh" in w for w in p["warnings"])

    def test_ket_luan_khong_phai_co_the_mua(self):
        verdict = {"verdict": "avoid", "label": "Không nên mua"}
        p = tp.build_plan("FPT", 50_000.0, _df(), 1e8, 1.0, verdict=verdict)
        assert any("Không nên mua" in w for w in p["warnings"])

    def test_luon_kem_quy_tac_va_canh_bao_chung(self):
        p = tp.build_plan("FPT", 50_000.0, _df(), 1e8, 1.0)
        assert "lô 100" in p["rule"]
        assert "không phải lời khuyên" in p["disclaimer"] and "nhảy qua mức đó" in p["disclaimer"]


class TestKetLuanTuLuotQuet:
    """Thẻ kế hoạch lấy kết luận từ lượt quét đã lưu, không tính lại (mất ~9 giây/mã)."""

    def test_lay_dung_ma_trong_luot_quet(self, temp_storage):
        import importlib

        module = importlib.reload(tp)
        temp_storage.save_verdict_scan(
            "2026-09-12",
            {
                "date": "2026-09-12",
                "results": [
                    {"symbol": "FPT", "verdict": "avoid", "label": "Không nên mua"},
                    {"symbol": "DHC", "verdict": "buy_consider", "label": "Có thể cân nhắc mua"},
                ],
            },
        )
        assert module.verdict_from_scan("dhc") == {
            "verdict": "buy_consider",
            "label": "Có thể cân nhắc mua",
            "scan_date": "2026-09-12",
        }
        assert module.verdict_from_scan("FPT")["verdict"] == "avoid"
        assert module.verdict_from_scan("XYZ") is None

    def test_chua_co_luot_quet_thi_khong_can_tro(self, temp_storage):
        import importlib

        assert importlib.reload(tp).verdict_from_scan("FPT") is None


class TestBuocGia:
    """Giá phải đặt lệnh được: HOSE bước 10 đ dưới 10.000, 50 đ tới 50.000, 100 đ trở lên."""

    def test_buoc_gia_theo_vung(self):
        assert tp.tick_size(9_900) == 10
        assert tp.tick_size(10_000) == 50
        assert tp.tick_size(49_950) == 50
        assert tp.tick_size(50_000) == 100

    def test_cat_lo_lam_tron_xuong_muc_tieu_lam_tron_len(self):
        assert tp.round_to_tick(33_907, "down") == 33_900
        assert tp.round_to_tick(33_907, "up") == 33_950
        assert tp.round_to_tick(72_777, "down") == 72_700
        assert tp.round_to_tick(9_996, "down") == 9_990

    def test_gia_dung_buoc_thi_giu_nguyen(self):
        assert tp.round_to_tick(48_000, "down") == 48_000
        assert tp.round_to_tick(48_000, "up") == 48_000

    def test_ke_hoach_tra_gia_dat_duoc_lenh(self):
        import pandas as pd

        closes = [33_950.0] * 60
        df = pd.DataFrame({
            "Open": closes,
            "High": [c + 700 for c in closes],
            "Low": [c - 700 for c in closes],
            "Close": closes,
            "Volume": [1e6] * 60,
        })
        p = tp.build_plan("DHC", 35_750.0, df, capital=100_000_000, risk_pct=1.0)
        for value in (p["stop"]["price"], p["target"]["price"]):
            assert value % tp.tick_size(value) == 0
