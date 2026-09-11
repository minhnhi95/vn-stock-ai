"""
Lớp gọi Gemini dùng chung — thay SDK bằng bản giả để kiểm tra đúng cách gọi.
"""
from __future__ import annotations

import pytest

import gemini_client as gc


def _fake_sdk(record):
    class _Response:
        text = '  {"a": 1}  '

    class _Model:
        def __init__(self, name):
            record["model"] = name

        def generate_content(self, prompt, generation_config=None):
            record["prompt"] = prompt
            record["config"] = generation_config
            return _Response()

    class _Sdk:
        @staticmethod
        def configure(api_key):
            record["key"] = api_key

        GenerativeModel = _Model

        @staticmethod
        def embed_content(model, content, task_type):
            record["embed"] = (model, content, task_type)
            return {"embedding": (0.1, 0.2)}

    return _Sdk


@pytest.fixture()
def record(monkeypatch):
    rec = {}
    monkeypatch.setattr(gc, "_sdk", _fake_sdk(rec))
    monkeypatch.setattr(gc, "HAS_SDK", True)
    return rec


def test_che_do_json_yeu_cau_mime_json(record):
    assert gc.generate_text("hoi", "k1", json_mode=True) == '{"a": 1}'
    assert record["config"] == {"response_mime_type": "application/json"}
    assert record["key"] == "k1"
    assert record["model"] == gc.GEMINI_MODEL


def test_che_do_thuong_khong_gui_cau_hinh(record):
    gc.generate_text("hoi", "k1")
    assert record["config"] is None


def test_chon_duoc_model_khac(record):
    gc.generate_text("hoi", "k1", model="gemini-khac")
    assert record["model"] == "gemini-khac"


def test_embed_tra_vector_dang_list(record):
    assert gc.embed_text("tin tuc", "k1") == [0.1, 0.2]
    assert record["embed"] == (gc.EMBED_MODEL, "tin tuc", "retrieval_document")


def test_thieu_sdk_thi_bao_loi_ro_khong_lam_sap(monkeypatch):
    monkeypatch.setattr(gc, "HAS_SDK", False)
    with pytest.raises(RuntimeError, match="google-generativeai"):
        gc.generate_text("hoi", "k1")
    assert gc.embed_text("tin tuc", "k1") is None
    assert gc.is_available() is False


def test_key_tren_giao_dien_uu_tien_hon_key_server(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", " key-server ")
    assert gc.resolve_key("key-giao-dien") == "key-giao-dien"
    assert gc.resolve_key("") == "key-server"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert gc.resolve_key(None) == ""
