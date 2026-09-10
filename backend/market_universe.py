"""
Rổ chỉ số VN — danh sách tĩnh dùng làm fallback khi vnstock không phản hồi.

Trước đây nằm trong backtest_service. Tách ra vì đây là dữ liệu tham chiếu của
thị trường, không liên quan gì tới việc mô phỏng giao dịch — và backtest đã bị
gỡ khỏi dự án.

Nguồn động (ưu tiên): sector_service.get_vn30_symbols() / get_vn100_symbols()
đọc từ vnstock Listing. Danh sách dưới đây chỉ dùng khi nguồn đó lỗi.
"""
from __future__ import annotations

from typing import List

# VN30 — cập nhật theo kỳ review quý. Rổ đổi 1-2 mã mỗi kỳ nên danh sách tĩnh
# có thể lệch nhẹ; đó là lý do nguồn động luôn được thử trước.
VN30_SYMBOLS: List[str] = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

# 70 mã mid-cap thường xuyên có mặt trong VN100 ngoài VN30.
VN100_EXTRA_SYMBOLS: List[str] = [
    "AAA", "ANV", "APH", "BFC", "BMP", "BSI", "BWE", "CII", "CMG", "CTD",
    "CTR", "CTS", "DBC", "DCM", "DGC", "DGW", "DIG", "DPM", "DXG", "DXS",
    "EIB", "EVF", "FRT", "FTS", "GEX", "GMD", "HAG", "HCM", "HDC", "HDG",
    "HHV", "HSG", "HT1", "IJC", "IMP", "KBC", "KDC", "KDH", "KOS", "LPB",
    "NKG", "NLG", "NT2", "NVL", "OCB", "ORS", "PAN", "PC1", "PDR", "PHR",
    "PNJ", "PPC", "PTB", "PVD", "PVS", "PVT", "REE", "SBT", "SCS", "SIP",
    "SJS", "SZC", "TCH", "TLG", "TV2", "VCG", "VCI", "VGC", "VHC", "VIX",
]


def vn100_fallback() -> List[str]:
    """VN30 + mid-cap, khử trùng lặp, giữ thứ tự."""
    seen = set()
    out: List[str] = []
    for symbol in VN30_SYMBOLS + VN100_EXTRA_SYMBOLS:
        if symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out
