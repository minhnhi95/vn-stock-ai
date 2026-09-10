"""
Phép đo "thị trường đã biết tin này chưa".

Đây là phần có giá trị nhất của bản tin và là phần DUY NHẤT trong pipeline
không dựa vào AI — nên nó phải đúng và phải kiểm chứng được. AI chỉ diễn đạt
lại kết luận của hàm này; nếu hàm sai thì bản tin sai theo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jobs.price_reaction import analyze_reaction, format_reaction_for_prompt


def _frame(closes, volumes=None):
    index = pd.date_range(end="2026-09-10", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "Close": closes,
            "Volume": volumes if volumes is not None else [1_000_000] * len(closes),
        },
        index=index,
    )


class TestDuLieuThieu:
    def test_khung_rong(self):
        assert analyze_reaction(pd.DataFrame()) == {
            "available": False,
            "reason": "Không đủ dữ liệu giá để đánh giá.",
        }

    def test_qua_it_phien(self):
        assert analyze_reaction(_frame([10, 11, 12]))["available"] is False

    def test_none(self):
        assert analyze_reaction(None)["available"] is False


class TestPhanLoai:
    def test_gia_chay_manh_kem_khoi_luong_lon_thi_da_phan_anh(self):
        # Dữ liệu dài như thực tế (6 tháng ~ 120 phiên): 30 phiên đi ngang làm
        # mốc, rồi 6 phiên cuối tăng mạnh kèm khối lượng gấp đôi.
        closes = [100.0] * 30 + [102, 104, 106, 108, 110, 112]
        volumes = [1_000_000] * 30 + [2_500_000] * 6
        result = analyze_reaction(_frame(closes, volumes))
        assert result["verdict"] == "likely_priced_in"
        assert result["volume_ratio"] >= 1.5
        assert "đã biết và phản ánh" in result["summary"]

    def test_moc_khoi_luong_khong_bi_chinh_dot_bien_lam_loang(self):
        """
        Lỗi từng mắc: lấy trung bình 20 phiên GẦN NHẤT làm mốc thì mấy phiên đột
        biến tự kéo mốc lên, một cú tăng gấp 2,5 lần chỉ hiện ra thành ~1,1 lần.
        Mốc phải là các phiên TRƯỚC cửa sổ đo.
        """
        closes = [100.0] * 30 + [102, 104, 106, 108, 110, 112]
        volumes = [1_000_000] * 30 + [2_500_000] * 6
        result = analyze_reaction(_frame(closes, volumes))
        # Cửa sổ đo có khối lượng 2,5tr trên nền 1tr -> phải ra ~2,5 lần.
        assert result["volume_ratio"] == pytest.approx(2.5, abs=0.15)

    def test_chuoi_qua_ngan_thi_khong_ket_luan_ve_khoi_luong(self):
        # Không đủ lịch sử để lập mốc -> trả None thay vì bịa ra một tỷ lệ.
        result = analyze_reaction(_frame([100, 101, 102, 104, 106, 108, 110, 112]))
        assert result["volume_ratio"] is None
        assert result["heavy_volume"] is False

    def test_gia_gan_nhu_dung_yen_thi_chua_phan_ung(self):
        closes = [100.0] * 30 + [100.1, 100.2, 100.1, 100.3, 100.2, 100.3]
        result = analyze_reaction(_frame(closes))
        assert result["verdict"] == "little_reaction"

    def test_gia_chay_vua_phai_thi_phan_anh_mot_phan(self):
        closes = [100.0] * 30 + [100.5, 101, 101.5, 102, 102.5, 103]
        result = analyze_reaction(_frame(closes))
        assert result["verdict"] == "partly_priced_in"

    def test_khoi_luong_thap_khong_du_de_ket_luan_da_phan_anh(self):
        # Giá chạy mạnh nhưng khối lượng thấp -> chỉ là "một phần", vì không có
        # bằng chứng dòng tiền lớn tham gia.
        closes = [100.0] * 30 + [102, 104, 106, 108, 110, 112]
        volumes = [2_000_000] * 30 + [500_000] * 6
        result = analyze_reaction(_frame(closes, volumes))
        assert result["verdict"] == "partly_priced_in"


class TestSoLieuTraVe:
    @pytest.fixture()
    def result(self):
        closes = [100.0] * 30 + [104, 106, 108, 110, 112, 114]
        return analyze_reaction(_frame(closes))

    def test_co_du_truong_can_thiet(self, result):
        for key in ("verdict", "summary", "latest_price", "run_up_pct", "volume_ratio"):
            assert key in result

    def test_gia_moi_nhat_dung(self, result):
        assert result["latest_price"] == 114

    def test_run_up_tinh_tren_5_phien_truoc_moc(self, result):
        # Mốc mặc định là phiên cuối (114); 5 phiên trước đó là 104.
        assert result["run_up_pct"] == pytest.approx((114 - 104) / 104 * 100, abs=0.01)


class TestMocNgayTin:
    def test_moc_theo_ngay_tin_chu_khong_phai_phien_cuoi(self):
        closes = list(np.linspace(100, 120, 20))
        df = _frame(closes)
        anchor = str(df.index[10].date())
        result = analyze_reaction(df, news_date=anchor)
        assert result["anchor_date"] == anchor
        # Có giá chạy sau tin vì còn 9 phiên nữa sau mốc.
        assert result["since_news_pct"] > 0

    def test_ngay_tin_khong_doc_duoc_thi_lui_ve_phien_cuoi(self):
        df = _frame(list(np.linspace(100, 120, 20)))
        result = analyze_reaction(df, news_date="khong-phai-ngay")
        assert result["anchor_date"] == str(df.index[-1].date())

    def test_ngay_tin_trong_tuong_lai_thi_lui_ve_phien_cuoi(self):
        df = _frame(list(np.linspace(100, 120, 20)))
        result = analyze_reaction(df, news_date="2099-01-01")
        assert result["anchor_date"] == str(df.index[-1].date())

    def test_ho_tro_dinh_dang_ngay_co_gio(self):
        df = _frame(list(np.linspace(100, 120, 20)))
        anchor = str(df.index[10].date())
        result = analyze_reaction(df, news_date=f"{anchor}T09:31:22")
        assert result["anchor_date"] == anchor


class TestFormatChoPrompt:
    def test_co_day_du_so_de_ai_khong_phai_tu_tinh(self):
        result = analyze_reaction(_frame([100.0] * 30 + [104, 106, 108, 110, 112, 114]))
        text = format_reaction_for_prompt("FPT", result)
        assert "FPT" in text
        # Nhấn mạnh "KHÔNG được thay đổi" để AI không bịa số khác.
        assert "KHÔNG được thay đổi" in text
        assert "Kết luận máy tính" in text

    def test_khong_do_duoc_thi_noi_ro(self):
        text = format_reaction_for_prompt("FPT", {"available": False, "reason": "thiếu dữ liệu"})
        assert "chưa đo được" in text
