"""
Chặn phán quyết mua/bán lọt ra từ câu trả lời của AI.

Nguyên tắc xuyên suốt app: không nhãn MUA/BÁN, không điểm tổng hợp, không "độ
tin cậy", không giá mục tiêu hay mức cắt lỗ. Prompt đã cấm, nhưng mô hình ngôn
ngữ không phải lúc nào cũng nghe lời — nên mọi văn bản AI sinh ra đều đi qua
lớp lọc này trước khi tới người dùng.

Chỉ bắt câu mang tính CHỈ DẪN ("nên mua", "khuyến nghị bán", "giá mục tiêu"),
không bắt câu mô tả ("khối ngoại chốt lời", "nhà đầu tư bán ra"). Lọc nhầm câu
mô tả làm mất thông tin thật; lọt câu chỉ dẫn thì phá đúng lời hứa của app.

Lọc theo từng câu chứ không bỏ cả đoạn: một đoạn giải thích RSI tốt không nên
mất trắng chỉ vì câu cuối lỡ thêm "nên chốt lời".
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Tuple

_ACTIONS = (
    r"(?:mua thêm|bán bớt|mua|bán|nắm giữ|giữ lại|chốt lời|cắt lỗ|gom|tích lũy|"
    r"tích luỹ|bắt đáy|thoát hàng|giải ngân)"
)

_PATTERNS = [
    re.compile(rf"\bnên\s+(?:cân nhắc\s+)?{_ACTIONS}", re.IGNORECASE),
    re.compile(rf"\b(?:khuyến nghị|khuyên)\s+(?:bạn\s+)?{_ACTIONS}", re.IGNORECASE),
    re.compile(rf"\b(?:hãy|có thể cân nhắc)\s+{_ACTIONS}", re.IGNORECASE),
    re.compile(r"\b(?:giá|vùng)\s+mục tiêu", re.IGNORECASE),
    re.compile(r"\bđiểm\s+(?:mua|bán)\b", re.IGNORECASE),
    re.compile(r"\b(?:mức|ngưỡng)\s+cắt lỗ\b", re.IGNORECASE),
    re.compile(r"\bđộ tin cậy\b", re.IGNORECASE),
    re.compile(
        r"\b(?:stop[\s-]?loss|take[\s-]?profit|target price|strong[_\s]?(?:buy|sell))\b",
        re.IGNORECASE,
    ),
]

# "Đây không phải khuyến nghị mua" hay "tôi không đưa khuyến nghị bán" là câu TỪ
# CHỐI, không phải phán quyết. Nhưng "không nên mua" vẫn là phán quyết (khuyên
# tránh mua), nên chỉ miễn khi ngay trước là "không đưa / không phải / không có".
_REFUSAL_PREFIX = re.compile(
    r"(?:không|chẳng|chưa)\s+(?:đưa(?: ra)?|phải là|phải|có|là)\s*$", re.IGNORECASE
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# Câu thông báo đã lọc. Cố ý tránh chính các cụm bị cấm, để nó không tự lọc mình.
FILTER_NOTE = (
    "Một phần câu trả lời của AI đã bị ẩn vì mang tính chỉ dẫn giao dịch. "
    "App chỉ giải thích số liệu, không đưa lời khuyên đầu tư."
)


def contains_verdict(text: Any) -> bool:
    """Câu này có mang tính chỉ dẫn mua/bán không."""
    if not text:
        return False
    s = str(text)
    for pattern in _PATTERNS:
        for match in pattern.finditer(s):
            if not _REFUSAL_PREFIX.search(s[: match.start()]):
                return True
    return False


def strip_verdicts(text: Any) -> Tuple[str, int]:
    """
    Bỏ các câu mang tính chỉ dẫn, giữ phần còn lại.

    Trả (văn bản đã lọc, số câu đã bỏ). Giữ nguyên xuống dòng để câu trả lời dạng
    gạch đầu dòng không bị dồn thành một khối.
    """
    if not text:
        return "", 0
    removed = 0
    out_lines = []
    for line in str(text).splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        parts = _SENTENCE_SPLIT.split(line)
        kept = [p for p in parts if not contains_verdict(p)]
        removed += len(parts) - len(kept)
        if kept:
            out_lines.append(" ".join(kept))
    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    return clean, removed


def clean_fields(
    data: Dict[str, Any],
    text_fields: Iterable[str] = (),
    list_fields: Iterable[str] = (),
) -> Tuple[Dict[str, Any], int]:
    """
    Chỉ giữ các trường được khai báo, lọc phán quyết trong từng trường.

    Trường không khai báo bị bỏ hẳn — kể cả "recommendation" hay "confidence" mà mô
    hình tự thêm dù prompt không xin. Trả (dict sạch, tổng số câu/ý đã bỏ).
    """
    out: Dict[str, Any] = {}
    removed = 0
    for key in text_fields:
        value = data.get(key)
        if value is None:
            continue
        clean, n = strip_verdicts(value)
        removed += n
        if clean:
            out[key] = clean
    for key in list_fields:
        value = data.get(key)
        if not isinstance(value, list):
            continue
        items = []
        for item in value:
            s = str(item).strip() if item is not None else ""
            if not s:
                continue
            if contains_verdict(s):
                removed += 1
                continue
            items.append(s)
        if items:
            out[key] = items
    return out, removed
