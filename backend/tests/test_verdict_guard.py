"""
Lớp lọc phán quyết — thứ giữ lời hứa "app không khuyên mua/bán" khi AI không nghe prompt.

Hai kiểu sai đều tốn kém: lọt câu "nên mua" là phá lời hứa với người mới; lọc nhầm
câu mô tả ("khối ngoại chốt lời") là giấu mất thông tin thật của thị trường.
"""
from __future__ import annotations

import pytest

from verdict_guard import FILTER_NOTE, clean_fields, contains_verdict, strip_verdicts


class TestPhatHienPhanQuyet:
    @pytest.mark.parametrize(
        "text",
        [
            "Bạn nên mua FPT ở vùng 70.000đ.",
            "Nhà đầu tư nên cân nhắc chốt lời một phần.",
            "Khuyến nghị bán khi giá vượt 80.000.",
            "Giá mục tiêu 95.000đ trong 6 tháng.",
            "Độ tin cậy của nhận định này là 80%.",
            "Đặt stop-loss ở 65.000.",
            "Không nên mua đuổi lúc này.",  # khuyên TRÁNH mua cũng là phán quyết
            "Hãy gom dần khi giá điều chỉnh.",
            "Điểm mua hợp lý quanh 70.000.",
            "Tín hiệu STRONG_BUY đã xuất hiện.",
        ],
    )
    def test_cau_chi_dan_bi_bat(self, text):
        assert contains_verdict(text), text

    @pytest.mark.parametrize(
        "text",
        [
            "Khối ngoại chốt lời mạnh trong phiên hôm qua.",
            "Nhà đầu tư cá nhân bán ra 2 triệu cổ phiếu.",
            "Doanh nghiệp đặt mục tiêu tăng trưởng doanh thu 15%.",
            "Đây không phải khuyến nghị mua bán.",
            "Tôi không đưa khuyến nghị mua hay bán cổ phiếu.",
            "RSI trên 70 thường được gọi là vùng quá mua.",
        ],
    )
    def test_cau_mo_ta_va_tu_choi_khong_bi_bat(self, text):
        assert not contains_verdict(text), text

    def test_ghi_chu_loc_khong_tu_loc_chinh_no(self):
        assert not contains_verdict(FILTER_NOTE)


class TestLocTheoCau:
    def test_chi_bo_cau_chi_dan_giu_phan_con_lai(self):
        clean, removed = strip_verdicts("RSI đang ở 72. Bạn nên bán bớt. MACD vẫn dương.")
        assert clean == "RSI đang ở 72. MACD vẫn dương."
        assert removed == 1

    def test_so_co_dau_cham_khong_bi_cat_nham(self):
        text = "Giá đóng cửa 74.500đ, cao hơn EMA20 là 72.100đ."
        assert strip_verdicts(text) == (text, 0)

    def test_giu_nguyen_xuong_dong(self):
        clean, removed = strip_verdicts("- Ý một.\n- Nên mua ngay.\n- Ý ba.")
        assert clean == "- Ý một.\n- Ý ba."
        assert removed == 1

    def test_van_ban_rong(self):
        assert strip_verdicts("") == ("", 0)
        assert strip_verdicts(None) == ("", 0)


class TestLocTruong:
    def test_bo_truong_la_giu_truong_cho_phep(self):
        out, removed = clean_fields(
            {"tong_quan": "Giá tăng 3%.", "recommendation": "BUY", "confidence": 85},
            ("tong_quan",),
        )
        assert out == {"tong_quan": "Giá tăng 3%."}
        assert removed == 0

    def test_loc_tung_y_trong_danh_sach(self):
        out, removed = clean_fields(
            {"rui_ro": ["Nợ vay cao.", "Nên cắt lỗ nếu thủng 60.000.", "", None]},
            (),
            ("rui_ro",),
        )
        assert out == {"rui_ro": ["Nợ vay cao."]}
        assert removed == 1

    def test_truong_bi_loc_sach_thi_bo_han(self):
        out, removed = clean_fields({"tong_quan": "Nên mua ngay."}, ("tong_quan",))
        assert out == {}
        assert removed == 1
