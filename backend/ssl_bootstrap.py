"""
Sửa lỗi SSL khi đường dẫn dự án có ký tự không phải ASCII.

Triệu chứng: yfinance/curl báo
    curl: (77) error setting certificate verify locations: CAfile: ...

Nguyên nhân: thư mục dự án là "Chứng khoán". certifi trả về đường dẫn CA bundle
nằm bên trong .venv của thư mục đó, mà libcurl trên Windows không mở được file
có ký tự Unicode trong đường dẫn. requests thì chịu được, curl_cffi (yfinance
dùng) thì không — nên vnstock chạy bình thường còn yfinance thì hỏng.

Cách xử lý: copy CA bundle sang một đường dẫn thuần ASCII trong thư mục temp,
rồi trỏ các biến môi trường SSL vào đó. Gọi `ensure_ca_bundle()` TRƯỚC khi
import/dùng yfinance.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

_SSL_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

_applied = False


def _is_ascii_path(path: str) -> bool:
    try:
        path.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _existing_override() -> Optional[str]:
    """CA bundle đã được đặt sẵn qua env và dùng được thì tôn trọng, không đè."""
    for var in _SSL_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value and os.path.isfile(value) and _is_ascii_path(value):
            return value
    return None


def ensure_ca_bundle() -> Optional[str]:
    """
    Đảm bảo có CA bundle ở đường dẫn ASCII và các biến môi trường trỏ vào đó.

    Idempotent. Trả về đường dẫn đang dùng, hoặc None nếu không cần/không làm được.
    """
    global _applied
    if _applied:
        return os.environ.get("SSL_CERT_FILE")

    existing = _existing_override()
    if existing:
        for var in _SSL_ENV_VARS:
            os.environ.setdefault(var, existing)
        _applied = True
        return existing

    try:
        import certifi

        source = certifi.where()
    except Exception:
        return None

    if _is_ascii_path(source):
        # Đường dẫn đã sạch, không cần copy.
        for var in _SSL_ENV_VARS:
            os.environ.setdefault(var, source)
        _applied = True
        return source

    target = Path(tempfile.gettempdir()) / "vnstock_cacert.pem"
    try:
        # Copy lại khi thiếu hoặc khác kích thước (certifi vừa được cập nhật).
        if not target.exists() or target.stat().st_size != os.path.getsize(source):
            shutil.copyfile(source, target)
    except OSError:
        return None

    for var in _SSL_ENV_VARS:
        os.environ[var] = str(target)
    _applied = True
    return str(target)
