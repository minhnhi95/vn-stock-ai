"""
Nhận dạng mã chứng khoán Việt Nam — một nguồn sự thật duy nhất.

Vì sao cần module riêng: trước đây 4 file tự viết lại phép kiểm tra
`len(s) == 3 and s.isalpha()`, và cả 4 đều SAI. Mã niêm yết VN được phép chứa
CHỮ SỐ: HT1 (Hà Tiên 1), NT2 (Nhơn Trạch 2), PC1, TV2, CC1, C4G, S99...
Kiểm tra bằng dữ liệu niêm yết thật: 160 trên 1.881 mã 3 ký tự có chứa số,
tức khoảng 8,5% thị trường bị loại nhầm.

Hậu quả của lỗi đó, theo mức nghiêm trọng giảm dần:
1. Nhập sao kê giao dịch THẬT: các dòng HT1/PC1... bị bỏ im lặng -> sổ lệnh
   thiếu, giá vốn và lãi/lỗ sai.
2. /api/stocks/historical trả 400 -> không xem được biểu đồ những mã này.
3. Bị loại khỏi index tìm kiếm và khỏi heatmap ngành.

Quy tắc rút ra từ danh sách niêm yết thực tế (kiểm tra 2026-09):
- Đúng 3 ký tự.
- Chỉ gồm chữ in hoa A-Z và chữ số 0-9.
- Ký tự đầu luôn là CHỮ (không có mã nào bắt đầu bằng số).
"""
from __future__ import annotations

import re

# ^[A-Z] : ký tự đầu phải là chữ
# [A-Z0-9]{2}$ : hai ký tự sau là chữ hoặc số
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")


def is_vn_symbol(symbol: str) -> bool:
    """True nếu là mã cổ phiếu niêm yết VN hợp lệ (đã ở dạng in hoa)."""
    return bool(_TICKER_RE.match(symbol or ""))


def normalize_symbol(symbol: str) -> str:
    """Chuẩn hoá về dạng so sánh được: bỏ khoảng trắng, viết hoa."""
    return (symbol or "").strip().upper()


def clean_and_validate(symbol: str) -> str | None:
    """Chuẩn hoá rồi kiểm tra. Trả None nếu không hợp lệ."""
    normalized = normalize_symbol(symbol)
    return normalized if is_vn_symbol(normalized) else None
