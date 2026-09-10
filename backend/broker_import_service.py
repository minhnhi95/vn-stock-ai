"""
Nhập sổ lệnh thật từ file sao kê công ty chứng khoán.

Vì sao không gọi API công ty chứng khoán: ngân hàng VN không có open banking cho
khách cá nhân, còn API môi giới (DNSE EntradeX, SSI FastConnect...) đòi đăng ký
riêng và giữ khoá bí mật. Nhập file là con đường ai cũng dùng được ngay, không
phải giao mật khẩu cho bất kỳ ai.

Mỗi công ty xuất một kiểu cột khác nhau (và hay đổi), nên parser dò cột theo từ
khoá thay vì cố định vị trí. Không nhận dạng được thì báo rõ đã thấy cột gì để
người dùng tự map, chứ không đoán bừa rồi ghi sai sổ.

Đầu ra chuẩn hoá: {date, symbol, side, quantity, price, fee, tax, note, ext_id}
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from symbol_utils import is_vn_symbol

# Phí/thuế mặc định khi file sao kê không tách riêng cột. Số liệu 2024-2026:
# - Phí môi giới: 0,15%-0,35% giá trị khớp mỗi chiều (tuỳ công ty và gói).
# - Thuế TNCN khi BÁN: 0,1% giá trị bán, thu ngay, không phụ thuộc lãi hay lỗ.
DEFAULT_BROKER_FEE_RATE = 0.0015
SELL_TAX_RATE = 0.001

_SIDE_BUY_TOKENS = ("mua", "buy", "b", "long")
_SIDE_SELL_TOKENS = ("ban", "sell", "s", "short")

# Từ khoá dò cột — đã bỏ dấu, viết thường.
_COLUMN_HINTS: Dict[str, Tuple[str, ...]] = {
    "date": ("ngay giao dich", "ngay gd", "trade date", "ngay khop", "ngay", "date", "thoi gian"),
    "symbol": ("ma ck", "ma chung khoan", "ma cp", "symbol", "ticker", "stock", "ma"),
    "side": ("loai gd", "loai lenh", "lenh", "side", "type", "mua ban", "giao dich", "dien giai"),
    "quantity": ("khoi luong", "kl khop", "so luong", "quantity", "volume", "kl"),
    "price": ("gia khop", "don gia", "gia gd", "price", "gia"),
    "fee": ("phi", "fee", "phi giao dich", "phi mua", "phi ban"),
    "tax": ("thue", "tax", "thue tncn"),
    "value": ("gia tri", "thanh tien", "value", "amount", "tong tien"),
}

_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d.%m.%Y", "%Y%m%d",
)


class ImportError_(Exception):
    """Lỗi người dùng sửa được (sai định dạng file), không phải bug."""


def _fold(text: Any) -> str:
    """Bỏ dấu + hạ chữ thường + gộp khoảng trắng."""
    raw = "" if text is None else str(text)
    lowered = unicodedata.normalize("NFD", raw.lower())
    stripped = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.replace("đ", "d")).strip()


def _parse_number(value: Any) -> Optional[float]:
    """
    '1.234.567,89' (VN), '1,234,567.89' (EN) và '73.500' đều phải ra đúng số.

    Quy tắc: dấu phân cách thập phân là dấu XUẤT HIỆN SAU CÙNG, và chỉ khi phần
    đứng sau nó ngắn hơn 3 chữ số — '73.500' là bảy mươi ba nghìn rưỡi chứ không
    phải 73,5.
    """
    if value is None:
        return None
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not text or text in {"-", "--"}:
        return None

    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("()-+")
    text = re.sub(r"[^\d.,]", "", text)
    if not text:
        return None

    last_dot = text.rfind(".")
    last_comma = text.rfind(",")
    sep = max(last_dot, last_comma)
    if sep != -1 and len(text) - sep - 1 < 3:
        integer = re.sub(r"[.,]", "", text[:sep])
        fraction = text[sep + 1:]
        text = f"{integer}.{fraction}"
    else:
        text = re.sub(r"[.,]", "", text)

    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _parse_date(value: Any) -> Optional[str]:
    """Trả 'YYYY-MM-DD'. None nếu không phải ngày."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Sao kê hay kèm giờ: '05/03/2026 09:31:22'
    text = text.split()[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_side(value: Any) -> Optional[str]:
    """'Mua'/'B'/'Khớp mua' -> BUY. Trả None nếu không xác định được."""
    folded = _fold(value)
    if not folded:
        return None
    # Kiểm tra BÁN trước: chuỗi "mua ban" chứa cả hai, nhưng dòng thực tế
    # thường là "khop ban" / "ban thuong".
    for token in _SIDE_SELL_TOKENS:
        if re.search(rf"\b{token}\b", folded):
            return "SELL"
    for token in _SIDE_BUY_TOKENS:
        if re.search(rf"\b{token}\b", folded):
            return "BUY"
    return None


def _match_column(headers_folded: List[str], hints: Tuple[str, ...]) -> Optional[int]:
    """Khớp chính xác trước, rồi mới substring — tránh 'ma' nuốt 'ma tai khoan'."""
    for hint in hints:
        for idx, header in enumerate(headers_folded):
            if header == hint:
                return idx
    for hint in hints:
        for idx, header in enumerate(headers_folded):
            if hint in header:
                return idx
    return None


def _detect_columns(headers: List[str]) -> Dict[str, Optional[int]]:
    folded = [_fold(h) for h in headers]
    return {field: _match_column(folded, hints) for field, hints in _COLUMN_HINTS.items()}


def _read_rows(content: bytes, filename: str = "") -> List[List[str]]:
    """
    Đọc CSV thành list dòng. Tự dò encoding và dấu phân cách.

    Sao kê VN hay là UTF-8-BOM hoặc CP1258; dấu phân cách có thể là ',' ';' hoặc
    tab (Excel bản tiếng Việt mặc định ';').
    """
    if filename.lower().endswith((".xlsx", ".xls")):
        raise ImportError_(
            "Chưa hỗ trợ đọc trực tiếp Excel. Mở file rồi 'Save As' → CSV UTF-8 và tải lại."
        )

    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportError_("Không đọc được nội dung file (encoding lạ).")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        # Sniffer thua thì chọn ký tự xuất hiện nhiều nhất trong vài dòng đầu.
        counts = {d: sample.count(d) for d in ",;\t|"}
        delimiter = max(counts, key=counts.get) if max(counts.values()) else ","

    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in row)]
    if not rows:
        raise ImportError_("File rỗng.")
    return rows


def _find_header_row(rows: List[List[str]]) -> int:
    """
    Sao kê thường có vài dòng tiêu đề/logo trước bảng thật. Dòng header là dòng
    đầu tiên nhận ra được cả cột mã lẫn cột khối lượng.
    """
    for idx, row in enumerate(rows[:25]):
        detected = _detect_columns(row)
        if detected["symbol"] is not None and detected["quantity"] is not None:
            return idx
    return 0


def parse_broker_csv(
    content: bytes,
    filename: str = "",
    fee_rate: float = DEFAULT_BROKER_FEE_RATE,
) -> Dict[str, Any]:
    """
    Parse sao kê -> danh sách giao dịch chuẩn hoá + báo cáo dòng bị bỏ.

    fee_rate chỉ dùng khi file KHÔNG có cột phí. Thuế bán luôn tính 0,1% nếu
    file không tách riêng, vì đó là mức luật định, không phụ thuộc công ty.
    """
    rows = _read_rows(content, filename)
    header_idx = _find_header_row(rows)
    headers = rows[header_idx]
    columns = _detect_columns(headers)

    missing = [f for f in ("date", "symbol", "quantity", "price") if columns[f] is None]
    if missing:
        raise ImportError_(
            "Không nhận ra các cột bắt buộc: "
            + ", ".join(missing)
            + ". Cột đọc được trong file: "
            + ", ".join(h.strip() for h in headers if h.strip())
        )

    def cell(row: List[str], field: str) -> Any:
        idx = columns[field]
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    records: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for line_no, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        date = _parse_date(cell(row, "date"))
        symbol = _fold(cell(row, "symbol")).upper().strip()
        quantity = _parse_number(cell(row, "quantity"))
        price = _parse_number(cell(row, "price"))

        # Cột "loại lệnh" đôi khi không có; thử suy từ cột diễn giải hoặc dấu
        # của khối lượng (một số công ty ghi bán bằng số âm).
        side = _parse_side(cell(row, "side"))
        if side is None and quantity is not None and quantity < 0:
            side = "SELL"

        problem = None
        if not date:
            problem = "không đọc được ngày"
        elif not is_vn_symbol(symbol):
            problem = f"mã không hợp lệ ({symbol or 'rỗng'})"
        elif not quantity:
            problem = "khối lượng rỗng hoặc bằng 0"
        elif price is None or price <= 0:
            problem = "giá không hợp lệ"
        elif side is None:
            problem = "không xác định được Mua hay Bán"

        if problem:
            skipped.append({"line": line_no, "reason": problem, "raw": " | ".join(row)[:160]})
            continue

        quantity = abs(int(round(quantity)))
        gross = quantity * price

        fee = _parse_number(cell(row, "fee"))
        if fee is None:
            fee = gross * fee_rate
        tax = _parse_number(cell(row, "tax"))
        if tax is None:
            tax = gross * SELL_TAX_RATE if side == "SELL" else 0.0

        # ext_id để nhập lại cùng file không tạo bản ghi trùng. Không dùng số
        # dòng vì thứ tự dòng đổi giữa các lần xuất sao kê.
        fingerprint = f"{date}|{symbol}|{side}|{quantity}|{round(price, 4)}"
        records.append(
            {
                "id": str(uuid.uuid4()),
                "ext_id": hashlib.sha1(fingerprint.encode("utf-8")).hexdigest(),
                "date": date,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "fee": round(abs(fee), 2),
                "tax": round(abs(tax), 2),
                "note": "",
                "source": filename or "csv",
            }
        )

    records.sort(key=lambda r: (r["date"], r["symbol"]))
    return {
        "records": records,
        "skipped": skipped,
        "detected_columns": {k: (headers[v].strip() if v is not None and v < len(headers) else None)
                             for k, v in columns.items()},
        "fee_rate_used": fee_rate,
        "fee_from_file": columns["fee"] is not None,
    }


def build_manual_record(
    date: str,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    fee: Optional[float] = None,
    tax: Optional[float] = None,
    fee_rate: float = DEFAULT_BROKER_FEE_RATE,
    note: str = "",
) -> Dict[str, Any]:
    """Dựng một giao dịch nhập tay, cùng schema với bản ghi từ file."""
    parsed_date = _parse_date(date)
    if not parsed_date:
        raise ImportError_("Ngày không hợp lệ (dùng dạng YYYY-MM-DD hoặc DD/MM/YYYY).")

    symbol = (symbol or "").strip().upper()
    if not is_vn_symbol(symbol):
        raise ImportError_("Mã chứng khoán phải gồm 3 ký tự, bắt đầu bằng chữ (vd FPT, HT1).")

    side = (side or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ImportError_("Loại lệnh phải là BUY hoặc SELL.")

    quantity = int(quantity)
    price = float(price)
    if quantity <= 0 or price <= 0:
        raise ImportError_("Khối lượng và giá phải lớn hơn 0.")

    gross = quantity * price
    if fee is None:
        fee = gross * fee_rate
    if tax is None:
        tax = gross * SELL_TAX_RATE if side == "SELL" else 0.0

    fingerprint = f"{parsed_date}|{symbol}|{side}|{quantity}|{round(price, 4)}"
    return {
        "id": str(uuid.uuid4()),
        "ext_id": hashlib.sha1(fingerprint.encode("utf-8")).hexdigest(),
        "date": parsed_date,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "fee": round(abs(float(fee)), 2),
        "tax": round(abs(float(tax)), 2),
        "note": note or "",
        "source": "manual",
    }
