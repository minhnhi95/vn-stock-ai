"""
Một chỗ duy nhất gọi Gemini.

App gọi Gemini ở ba nơi: AI giải thích một mã, review danh mục, và embedding cho
tìm tin theo nghĩa. Gom về đây vì hai lẽ:

1. Thư viện `google.generativeai` đã ngừng được hỗ trợ. Khi chuyển sang
   `google-genai`, chỉ phải sửa file này — ba module kia không đổi.
2. Thiếu thư viện không được làm sập cả backend. Trước đây ai_service import thẳng
   SDK ở đầu file, nên thiếu SDK là main.py không khởi động được. Giờ thiếu SDK chỉ
   làm các tính năng AI báo lỗi rõ ràng.

Test chỉ cần giả lập generate_text / embed_text, không phải giả lập cả SDK.
"""
from __future__ import annotations

import os
from typing import List, Optional

try:
    import google.generativeai as _sdk

    HAS_SDK = True
except ImportError:  # pragma: no cover - phụ thuộc môi trường cài đặt
    _sdk = None
    HAS_SDK = False

# Đặt qua biến môi trường để đổi model mà không sửa code.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/text-embedding-004")

_MISSING_SDK = "Chưa cài thư viện Gemini (google-generativeai) trong môi trường này."


def resolve_key(api_key: Optional[str]) -> str:
    """Key người dùng nhập trên giao diện, nếu không có thì lấy GEMINI_API_KEY của server."""
    return (api_key or os.getenv("GEMINI_API_KEY") or "").strip()


def is_available() -> bool:
    return HAS_SDK


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
    _sdk.configure(api_key=api_key)
    client = _sdk.GenerativeModel(model or GEMINI_MODEL)
    if json_mode:
        response = client.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
    else:
        response = client.generate_content(prompt)
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
    _sdk.configure(api_key=api_key)
    result = _sdk.embed_content(model=EMBED_MODEL, content=text, task_type=task_type)
    vec = result.get("embedding") if isinstance(result, dict) else getattr(result, "embedding", None)
    return list(vec) if vec is not None else None
