"""
Dịch chỉ số cơ bản sang tiếng Việt đời thường, kèm so sánh trung bình ngành.

Vì sao cần module này: một người mới nhìn "P/E 15,53" không rút ra được gì. Con
số chỉ có nghĩa khi trả lời được hai câu hỏi — "nó nói gì về tiền của tôi?" và
"so với các doanh nghiệp cùng ngành thì sao?". Cả hai đều tính được bằng số học
thuần, không cần AI.

Nguyên tắc giữ xuyên suốt dự án: Python tính mọi con số, AI chỉ diễn đạt lại.
Ở đây không có AI — mọi câu chữ đều sinh từ template + số thật, nên câu giải
thích không bao giờ mâu thuẫn với con số bên cạnh nó.

Và: KHÔNG có câu nào kết luận nên mua hay nên bán. "Rẻ hơn ngành" là một quan
sát về giá; nó không phải lời khuyên, nên mỗi chỉ số đều kèm `caveat` nói rõ
trường hợp con số này đánh lừa.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

# Chênh dưới mức này so với ngành thì coi như ngang nhau. Dữ liệu cơ bản của VN
# lệch nhau giữa các nguồn vài phần trăm là bình thường, đọc kỹ hơn thế là đọc nhiễu.
INLINE_TOLERANCE = 0.10

# Ngành có ít hơn ngần này mã lấy được số liệu thì trung vị không đại diện cho gì cả.
MIN_SECTOR_SAMPLE = 5

def _savings_rate() -> float:
    """
    Lãi gửi tiết kiệm 12 tháng, dùng làm mốc so với lợi suất cổ tức.

    Đặt qua biến môi trường `SAVINGS_RATE_PCT` để đổi khi mặt bằng lãi suất đổi
    mà không phải sửa code — đây là con số duy nhất trong module này đến từ ngoài
    báo cáo tài chính, nên cũng là con số duy nhất sẽ cũ đi theo thời gian.
    Mặc định 5,0%/năm: mức của nhóm ngân hàng lớn, cập nhật 2026.
    """
    try:
        value = float(os.getenv("SAVINGS_RATE_PCT", "") or 5.0)
    except ValueError:
        return 5.0
    # Giá trị vô lý (âm, hoặc 500%) thì thà dùng mặc định còn hơn in ra câu sai.
    return value if 0.0 < value < 100.0 else 5.0


SAVINGS_RATE_PCT = _savings_rate()

_BENCHMARK_PATH = os.path.join(os.path.dirname(__file__), "data", "sector_benchmarks.json")


# --- Định dạng số kiểu Việt Nam: 1.234,56 ---

def _vn_number(value: float, prec: int = 2) -> str:
    text = f"{value:,.{prec}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _vnd(value: float) -> str:
    return f"{_vn_number(value, 0)} đ"


def _times(value: float) -> str:
    return f"{_vn_number(value, 2)} lần"


def _pct(value: float) -> str:
    return f"{_vn_number(value, 2)}%"


# --- Mô tả từng chỉ số ---
#
# direction quyết định CÁCH ĐỌC chênh lệch với ngành, không phải "tốt/xấu":
#   lower_cheaper   — thấp hơn nghĩa là trả giá rẻ hơn cho cùng một thứ (P/E, P/B)
#   higher_stronger — cao hơn nghĩa là con số đó lớn hơn (ROE, biên lãi, tăng trưởng)
#   lower_safer     — thấp hơn nghĩa là ít đòn bẩy hơn (nợ / vốn chủ)
#   standalone      — không so sánh được giữa các doanh nghiệp (EPS, BVPS, beta)

_COMPARISON_WORDS = {
    "lower_cheaper": ("Rẻ hơn", "Đắt hơn"),
    "higher_stronger": ("Thấp hơn", "Cao hơn"),
    "lower_safer": ("Vay ít hơn", "Vay nhiều hơn"),
}


def _plain_pe(v: float) -> str:
    if v <= 0:
        return (
            "P/E âm nghĩa là doanh nghiệp đang lỗ. Không tính được bao lâu thì hoàn "
            "vốn, vì hiện chưa có lợi nhuận để hoàn."
        )
    return (
        f"Bạn trả {_vn_number(v)} đồng để mua 1 đồng lợi nhuận mỗi năm. Nếu lợi nhuận "
        f"giữ nguyên như hiện tại, cần khoảng {_vn_number(v, 1)} năm để hoàn vốn."
    )


def _plain_pb(v: float) -> str:
    if v <= 0:
        return "P/B âm — vốn chủ sở hữu đang âm, doanh nghiệp nợ nhiều hơn tài sản."
    return (
        f"Bạn trả {_vn_number(v)} đồng cho 1 đồng tài sản ròng (tài sản đã trừ hết nợ) "
        f"của doanh nghiệp."
    )


def _plain_roe(v: float) -> str:
    if v <= 0:
        return (
            "Doanh nghiệp đang lỗ trên vốn chủ sở hữu — 100 đồng vốn không sinh ra "
            "đồng lãi nào."
        )
    return (
        f"Cứ 100 đồng vốn chủ sở hữu, doanh nghiệp làm ra {_vn_number(v, 1)} đồng lợi "
        f"nhuận một năm."
    )


def _plain_roa(v: float) -> str:
    return (
        f"Cứ 100 đồng tài sản (gồm cả phần mua bằng tiền đi vay), doanh nghiệp làm ra "
        f"{_vn_number(v, 1)} đồng lợi nhuận một năm."
    )


def _plain_eps(v: float) -> str:
    return (
        f"Mỗi cổ phiếu tương ứng {_vnd(v)} lợi nhuận trong một năm. Đây là phần lợi "
        f"nhuận tính trên đầu cổ phiếu, không phải tiền mặt bạn nhận về."
    )


def _plain_bvps(v: float) -> str:
    return (
        f"Giá trị sổ sách {_vnd(v)}/cổ phiếu — nếu bán hết tài sản theo sổ sách và trả "
        f"hết nợ, mỗi cổ phiếu còn lại chừng đó."
    )


def _plain_debt(v: float) -> str:
    return (
        f"Doanh nghiệp vay {_vn_number(v)} đồng cho mỗi 1 đồng vốn tự có. Nợ càng cao "
        f"thì lãi vay ăn vào lợi nhuận càng nhiều khi lãi suất tăng."
    )


def _plain_dividend(v: float) -> str:
    if v <= 0:
        return (
            "Không trả cổ tức tiền mặt. Không hẳn là xấu — nhiều doanh nghiệp giữ lại "
            "lợi nhuận để mở rộng kinh doanh."
        )
    line = f"Với giá hiện tại, cổ tức tiền mặt tương đương {_pct(v)}/năm."
    anchor = _vn_number(SAVINGS_RATE_PCT, 0)
    if v < SAVINGS_RATE_PCT:
        return line + f" Thấp hơn lãi gửi tiết kiệm 12 tháng (quanh {anchor}%/năm)."
    return line + (
        f" Cao hơn lãi gửi tiết kiệm 12 tháng (quanh {anchor}%/năm), nhưng giá cổ phiếu "
        f"có thể giảm còn tiền gửi thì không."
    )


def _plain_net_margin(v: float) -> str:
    if v < 0:
        return (
            f"Cứ 100 đồng doanh thu, doanh nghiệp lỗ {_vn_number(abs(v), 1)} đồng sau thuế."
        )
    return (
        f"Cứ 100 đồng doanh thu, doanh nghiệp giữ lại {_vn_number(v, 1)} đồng lợi nhuận "
        f"sau thuế."
    )


def _plain_gross_margin(v: float) -> str:
    return (
        f"Cứ 100 đồng doanh thu, còn {_vn_number(v, 1)} đồng sau khi trừ giá vốn — phần "
        f"này còn phải gánh chi phí bán hàng, quản lý, lãi vay và thuế."
    )


def _plain_revenue_growth(v: float) -> str:
    if v < 0:
        return (
            f"Doanh thu giảm {_vn_number(abs(v), 1)}% so với cùng kỳ năm trước — bán được "
            f"ít hàng hơn."
        )
    return f"Doanh thu tăng {_vn_number(v, 1)}% so với cùng kỳ năm trước."


def _plain_earnings_growth(v: float) -> str:
    if v < 0:
        return f"Lợi nhuận sau thuế giảm {_vn_number(abs(v), 1)}% so với cùng kỳ năm trước."
    return f"Lợi nhuận sau thuế tăng {_vn_number(v, 1)}% so với cùng kỳ năm trước."


def _plain_beta(v: float) -> str:
    if v > 1.15:
        tail = "biến động mạnh hơn thị trường chung, lãi nhanh mà lỗ cũng nhanh."
    elif v < 0.85:
        tail = "biến động nhẹ hơn thị trường chung."
    else:
        tail = "biến động gần như cùng nhịp với thị trường chung."
    return f"VN-Index nhích 1%, mã này thường nhích khoảng {_vn_number(v)}% — {tail}"


_SPECS: List[Dict[str, Any]] = [
    {
        "key": "pe",
        "label": "P/E (giá / lợi nhuận)",
        "direction": "lower_cheaper",
        "fmt": _times,
        "plain": _plain_pe,
        "caveat": "P/E thấp không mặc nhiên là rẻ: có thể lợi nhuận năm nay tăng đột biến "
        "nhờ một khoản bất thường, sang năm không lặp lại.",
    },
    {
        "key": "pb",
        "label": "P/B (giá / sổ sách)",
        "direction": "lower_cheaper",
        "fmt": _times,
        "plain": _plain_pb,
        "caveat": "Doanh nghiệp công nghệ hay dịch vụ thường có P/B cao vì tài sản chính là "
        "con người và thương hiệu, không nằm trên sổ sách.",
    },
    {
        "key": "roe",
        "unit": "pct",
        "label": "ROE (lãi / vốn chủ)",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_roe,
        "caveat": "ROE cao có thể đến từ vay nợ nhiều chứ không phải kinh doanh giỏi — nên "
        "đọc kèm chỉ số Nợ vay / Vốn chủ ngay dưới.",
    },
    {
        "key": "roa",
        "unit": "pct",
        "label": "ROA (lãi / tài sản)",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_roa,
        "caveat": "Ngân hàng và bất động sản luôn có ROA thấp do đặc thù tài sản rất lớn; "
        "chỉ nên so trong cùng ngành.",
    },
    {
        "key": "net_margin",
        "unit": "pct",
        "label": "Biên lợi nhuận ròng",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_net_margin,
        "caveat": "Biên mỏng chưa chắc yếu: bán lẻ và phân phối lãi ít trên mỗi đồng doanh "
        "thu nhưng quay vòng vốn rất nhanh.",
    },
    {
        "key": "gross_margin",
        "unit": "pct",
        "label": "Biên lợi nhuận gộp",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_gross_margin,
        "caveat": "Biên gộp cao mà lợi nhuận ròng vẫn thấp nghĩa là chi phí bán hàng, quản lý "
        "hoặc lãi vay đang ăn hết phần chênh.",
    },
    {
        "key": "debt_to_equity",
        "label": "Nợ vay / Vốn chủ",
        "direction": "lower_safer",
        "fmt": _times,
        "plain": _plain_debt,
        "caveat": "Ngân hàng bản chất là đi vay để cho vay nên tỷ lệ này luôn rất cao — không "
        "đọc chung thang với doanh nghiệp sản xuất.",
    },
    {
        "key": "dividend_yield",
        "unit": "pct",
        "label": "Cổ tức tiền mặt",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_dividend,
        "caveat": "Lợi suất cổ tức cao bất thường thường là do giá cổ phiếu vừa giảm mạnh, "
        "chứ không phải doanh nghiệp vừa tăng chia.",
    },
    {
        "key": "revenue_growth",
        "unit": "pct",
        "label": "Tăng trưởng doanh thu",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_revenue_growth,
        "caveat": "Một quý tăng mạnh có thể chỉ do cùng kỳ năm trước quá thấp. Nên nhìn xu "
        "hướng nhiều quý thay vì một con số.",
    },
    {
        "key": "earnings_growth",
        "unit": "pct",
        "label": "Tăng trưởng lợi nhuận",
        "direction": "higher_stronger",
        "fmt": _pct,
        "plain": _plain_earnings_growth,
        "caveat": "Lợi nhuận tăng nhờ bán tài sản hoặc hoàn nhập dự phòng thì không lặp lại "
        "ở các quý sau.",
    },
    {
        "key": "eps",
        "label": "EPS (lãi / cổ phiếu)",
        "direction": "standalone",
        "fmt": _vnd,
        "plain": _plain_eps,
        "caveat": "Không so EPS giữa hai doanh nghiệp: số lượng cổ phiếu lưu hành khác nhau "
        "nên con số không cùng thang.",
    },
    {
        "key": "bvps",
        "label": "Sổ sách / cổ phiếu",
        "direction": "standalone",
        "fmt": _vnd,
        "plain": _plain_bvps,
        "caveat": "Giá trị sổ sách ghi theo giá mua ngày xưa, có thể lệch xa giá thị trường "
        "hiện tại của chính tài sản đó.",
    },
    {
        "key": "beta",
        "label": "Beta (độ nhạy)",
        "direction": "standalone",
        "fmt": lambda v: _vn_number(v, 2),
        "plain": _plain_beta,
        "caveat": "Beta đo quá khứ. Một tin bất ngờ về riêng doanh nghiệp có thể làm giá đi "
        "hoàn toàn khác thị trường.",
    },
]


# Trên mức chênh lệch tương đối này thì con số phần trăm hết ý nghĩa: chênh
# "1.188%" chỉ nói lên rằng trung vị ngành gần bằng 0, chứ không giúp hình dung.
_RATIO_CAP = 2.0


def _gap_phrase(value: float, median: float, unit: str) -> str:
    """
    Diễn đạt khoảng cách so với ngành.

    Chỉ số vốn đã tính bằng % (ROE, biên lãi, tăng trưởng) thì so bằng ĐIỂM PHẦN
    TRĂM. Lấy phần trăm của phần trăm là cách nhanh nhất tạo ra những câu như
    "cao hơn 1.188%" — đúng về số học nhưng chỉ phản ánh việc trung vị ngành gần
    bằng 0, và người đọc sẽ hiểu thành "gấp 12 lần lợi nhuận".
    """
    if unit == "pct":
        return f"{_vn_number(abs(value - median), 1)} điểm %"

    ratio = (value - median) / abs(median)
    if abs(ratio) > _RATIO_CAP and median != 0:
        return f"gấp {_vn_number(abs(value / median), 1)} lần"
    return f"{_vn_number(abs(ratio) * 100, 0)}%"


def _compare(
    value: float,
    median: float,
    direction: str,
    sector_name: str,
    fmt: Callable[[float], str],
    unit: str = "ratio",
) -> Dict[str, Optional[str]]:
    """So sánh với trung vị ngành. Trả về nhận xét mô tả, không phải khuyến nghị."""
    if direction == "standalone" or median is None or median == 0:
        return {"comparison": None, "comparison_text": None}

    diff_ratio = (value - median) / abs(median)
    if abs(diff_ratio) < INLINE_TOLERANCE:
        return {
            "comparison": "inline",
            "comparison_text": f"Ngang trung bình ngành {sector_name} ({fmt(median)}).",
        }

    low_word, high_word = _COMPARISON_WORDS[direction]
    word = high_word if diff_ratio > 0 else low_word
    gap = _gap_phrase(value, median, unit)
    # "gấp 3,9 lần" là một mệnh đề, cần dấu phẩy; "53%" và "22,4 điểm %" thì nối thẳng.
    joiner = ", " if gap.startswith("gấp") else " "
    return {
        "comparison": "above" if diff_ratio > 0 else "below",
        "comparison_text": (
            f"{word} trung bình ngành {sector_name}{joiner}{gap} (ngành {fmt(median)})."
        ),
    }


def explain_fundamentals(
    fundamentals: Optional[Dict[str, Any]],
    sector_name: Optional[str] = None,
    sector_stats: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Sinh giải thích cho từng chỉ số có trong `fundamentals`.

    `sector_stats` dạng {metric_key: {"median": float, "sample": int}}. Thiếu thì
    bỏ phần so sánh — thà không so còn hơn so với một trung vị dựng từ 2 mã.
    """
    if not fundamentals or not fundamentals.get("available"):
        return []

    stats = sector_stats or {}
    out: List[Dict[str, Any]] = []

    for spec in _SPECS:
        value = fundamentals.get(spec["key"])
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value != value:  # NaN
            continue

        entry: Dict[str, Any] = {
            "key": spec["key"],
            "label": spec["label"],
            "value": value,
            "display": spec["fmt"](value),
            "plain": spec["plain"](value),
            "caveat": spec["caveat"],
            "sector": None,
            "comparison": None,
            "comparison_text": None,
        }

        stat = stats.get(spec["key"])
        if stat and sector_name and (stat.get("sample") or 0) >= MIN_SECTOR_SAMPLE:
            median = stat.get("median")
            if median is not None:
                entry["sector"] = {
                    "name": sector_name,
                    "median": median,
                    "display": spec["fmt"](float(median)),
                    "sample": stat["sample"],
                }
                entry.update(
                    _compare(
                        value,
                        float(median),
                        spec["direction"],
                        sector_name,
                        spec["fmt"],
                        spec.get("unit", "ratio"),
                    )
                )

        out.append(entry)

    return out


# --- Bảng trung vị ngành, sinh sẵn bởi jobs/sector_benchmarks.py ---

_benchmarks_cache: Optional[Dict[str, Any]] = None
_benchmarks_mtime: Optional[float] = None


def load_benchmarks() -> Dict[str, Any]:
    """Đọc bảng trung vị ngành từ đĩa, nạp lại khi file đổi. Thiếu file thì trả rỗng."""
    global _benchmarks_cache, _benchmarks_mtime
    try:
        mtime = os.path.getmtime(_BENCHMARK_PATH)
    except OSError:
        return {"generated_at": None, "sectors": {}, "symbol_sector": {}}

    if _benchmarks_cache is None or mtime != _benchmarks_mtime:
        try:
            with open(_BENCHMARK_PATH, encoding="utf-8") as fh:
                _benchmarks_cache = json.load(fh)
        except (OSError, ValueError) as e:
            # Bảng hỏng thì bỏ phần so sánh ngành, KHÔNG làm sập endpoint cơ bản:
            # phần giải thích từng chỉ số vẫn dùng được và mới là phần chính.
            print(f"[metric_explainer] khong doc duoc bang nganh: {str(e)[:100]}")
            return {"generated_at": None, "sectors": {}, "symbol_sector": {}}
        _benchmarks_mtime = mtime
    return _benchmarks_cache


def explain_for_symbol(symbol: str, fundamentals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ghép chỉ số của một mã với bảng trung vị ngành đã tính sẵn.

    Trả về {"sector", "benchmark_date", "items"} để UI biết số so sánh cũ tới đâu.
    """
    data = load_benchmarks()
    sector_name = (data.get("symbol_sector") or {}).get((symbol or "").strip().upper())
    sector_stats = None
    if sector_name:
        sector_stats = (data.get("sectors") or {}).get(sector_name, {}).get("metrics")

    return {
        "sector": sector_name,
        "benchmark_date": data.get("generated_at"),
        "items": explain_fundamentals(fundamentals, sector_name, sector_stats),
    }
