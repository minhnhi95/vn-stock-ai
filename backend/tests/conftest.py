"""
Cấu hình chung cho test backend.

Nguyên tắc: KHÔNG test nào được gọi mạng thật (vnstock/yfinance/Gemini) — chậm,
phụ thuộc rate limit 20 req/phút của vnstock free tier, và kết quả đổi theo ngày.
Test chỉ phủ phần logic thuần và tầng lưu trữ.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def temp_storage(tmp_path, monkeypatch):
    """
    storage_service với SQLite riêng cho mỗi test.

    storage_service đọc STOCK_DB_PATH ở thời điểm import nên phải set env rồi
    reload module, không thể chỉ monkeypatch attribute.
    """
    import importlib

    db_file = tmp_path / "test.db"
    monkeypatch.setenv("STOCK_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import storage_service

    module = importlib.reload(storage_service)
    yield module

    # Trả module về cấu hình mặc định cho các test sau.
    monkeypatch.delenv("STOCK_DB_PATH", raising=False)
    importlib.reload(storage_service)
