"""
Một chỗ duy nhất gọi Gemini.

App gọi Gemini ở ba nơi: AI giải thích một mã, review danh mục, và embedding cho
tìm tin theo nghĩa. Gom về đây vì hai lẽ:

1. Đổi SDK chỉ phải sửa một file. File này đã chuyển từ `google.generativeai`
   (ngừng được hỗ trợ) sang `google-genai` mà ba module kia không đổi dòng nào.
2. Thiếu thư viện không được làm sập cả backend: import có chặn lỗi, thiếu SDK chỉ
   làm các tính năng AI báo lỗi rõ ràng.

Test chỉ cần giả lập generate_text / embed_text, không phải giả lập cả SDK.
"""
from __future__ import annotations

import os
from typing import List, Optional

try:
    from google import genai as _genai
    from google.genai import types as _types

    HAS_SDK = True
except ImportError:  # pragma: no cover - phụ thuộc môi trường cài đặt
    _genai = None
    _types = None
    HAS_SDK = False

# Đặt qua biến môi trường để đổi model mà không sửa code.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/text-embedding-004")

_MISSING_SDK = "Chưa cài thư viện Gemini (google-genai) trong môi trường này."


def resolve_key(api_key: Optional[str]) -> str:
    """Key người dùng nhập trên giao diện, nếu không có thì lấy GEMINI_API_KEY của server."""
    return (api_key or os.getenv("GEMINI_API_KEY") or "").strip()


def is_available() -> bool:
    return HAS_SDK


def _client(api_key: str):
    # Tạo client theo từng lần gọi: key có thể khác nhau giữa các lần (key người dùng
    # nhập trên giao diện, hoặc key của server), nên không giữ một client toàn cục.
    return _genai.Client(api_key=api_key)


def generate_text(
    prompt: str,
    api_key: str,
    *,
    json_mode: bool = False,
    model: Optional[str] = None,
) -> str:
    """
    Gửi prompt, trả văn bản đã bỏ khoảng trắng hai đầu.

    `json_mode=True` yêu cầu mô hình trả JSON thuần. Mọi lỗi (key sai, hết hạn
    ngạch, mạng) được ném ra nguyên vẹn để caller tự phân loại và báo cho người dùng.
    """
    if not HAS_SDK:
        raise RuntimeError(_MISSING_SDK)
    config = (
        _types.GenerateContentConfig(response_mime_type="application/json")
        if json_mode
        else None
    )
    # Giữ biến `client` suốt lời gọi. Client của google-genai tự đóng kết nối khi bị thu
    # hồi bộ nhớ, nên viết gọn `_client(key).models.generate_content(...)` thì client tạm
    # bị huỷ ngay sau khi lấy `.models`, và request báo "client has been closed".
    client = _client(api_key)
    response = client.models.generate_content(
        model=model or GEMINI_MODEL,
        contents=prompt,
        config=config,
    )
    return (response.text or "").strip()


def embed_text(
    text: str,
    api_key: str,
    *,
    task_type: str = "retrieval_document",
) -> Optional[List[float]]:
    """Vector embedding của một đoạn văn bản. Thiếu SDK thì trả None; lỗi mạng được ném ra."""
    if not HAS_SDK:
        return None
    client = _client(api_key)  # giữ tham chiếu suốt lời gọi — xem generate_text
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=_types.EmbedContentConfig(task_type=task_type.upper()),
    )
    embeddings = getattr(result, "embeddings", None) or []
    values = getattr(embeddings[0], "values", None) if embeddings else None
    return list(values) if values is not None else None
