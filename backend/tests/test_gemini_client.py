"""
Lớp gọi Gemini dùng chung — thay SDK google-genai bằng bản giả để kiểm tra đúng
cách gọi: model nào, nội dung gì, cấu hình gì.
"""
from __future__ import annotations

import pytest

import gemini_client as gc


def _fake_sdk(record):
    """Bản giả tối thiểu của `google.genai` và `google.genai.types`."""

    class _Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Types:
        GenerateContentConfig = _Config
        EmbedContentConfig = _Config

    class _Response:
        text = '  {"a": 1}  '

    class _Embedding:
        values = (0.1, 0.2)

    class _EmbedResult:
        embeddings = [_Embedding()]

    class _Models:
        def generate_content(self, *, model, contents, config=None):
            record["model"] = model
            record["contents"] = contents
            record["config"] = config.kwargs if config is not None else None
            return _Response()

        def embed_content(self, *, model, contents, config=None):
            record["embed"] = (model, contents, config.kwargs if config is not None else None)
            return _EmbedResult()

    class _Client:
        def __init__(self, api_key):
            record["key"] = api_key
            self.models = _Models()

    class _Genai:
        Client = _Client

    return _Genai, _Types


@pytest.fixture()
def record(monkeypatch):
    rec = {}
    genai, types = _fake_sdk(rec)
    monkeypatch.setattr(gc, "_genai", genai)
    monkeypatch.setattr(gc, "_types", types)
    monkeypatch.setattr(gc, "HAS_SDK", True)
    return rec


def test_che_do_json_yeu_cau_mime_json(record):
    assert gc.generate_text("hoi", "k1", json_mode=True) == '{"a": 1}'
    assert record["config"] == {"response_mime_type": "application/json"}
    assert record["key"] == "k1"
    assert record["model"] == gc.GEMINI_MODEL
    assert record["contents"] == "hoi"


def test_che_do_thuong_khong_gui_cau_hinh(record):
    gc.generate_text("hoi", "k1")
    assert record["config"] is None


def test_chon_duoc_model_khac(record):
    gc.generate_text("hoi", "k1", model="gemini-khac")
    assert record["model"] == "gemini-khac"


def test_embed_tra_vector_dang_list(record):
    assert gc.embed_text("tin tuc", "k1") == [0.1, 0.2]
    model, contents, config = record["embed"]
    assert (model, contents) == (gc.EMBED_MODEL, "tin tuc")
    # SDK mới dùng tên task viết hoa.
    assert config == {"task_type": "RETRIEVAL_DOCUMENT"}


def test_embed_khong_co_vector_thi_tra_none(record, monkeypatch):
    class _Empty:
        embeddings = []

    class _Models:
        def embed_content(self, **kwargs):
            return _Empty()

    class _Client:
        def __init__(self, api_key):
            self.models = _Models()

    monkeypatch.setattr(gc._genai, "Client", _Client)
    assert gc.embed_text("tin tuc", "k1") is None


def test_thieu_sdk_thi_bao_loi_ro_khong_lam_sap(monkeypatch):
    monkeypatch.setattr(gc, "HAS_SDK", False)
    with pytest.raises(RuntimeError, match="google-genai"):
        gc.generate_text("hoi", "k1")
    assert gc.embed_text("tin tuc", "k1") is None
    assert gc.is_available() is False


def test_key_tren_giao_dien_uu_tien_hon_key_server(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", " key-server ")
    assert gc.resolve_key("key-giao-dien") == "key-giao-dien"
    assert gc.resolve_key("") == "key-server"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert gc.resolve_key(None) == ""


def test_client_con_song_suot_loi_goi(monkeypatch):
    """
    Lỗi đã gặp với SDK thật: Client của google-genai đóng kết nối khi bị thu hồi bộ
    nhớ. Viết `_client(key).models.generate_content(...)` thì client tạm bị huỷ ngay
    sau khi lấy `.models`, và request báo "client has been closed". Các test giả lập
    khác đều pass trong khi lời gọi thật hỏng — test này tái hiện đúng hành vi đó.
    """
    import gc as garbage

    class _Api:
        closed = False

    class _Response:
        text = "ok"

    class _Embedding:
        values = (1.0,)

    class _EmbedResult:
        embeddings = [_Embedding()]

    class _Models:
        def __init__(self, api):
            self._api = api

        def _check(self):
            if self._api.closed:
                raise RuntimeError("Cannot send a request, as the client has been closed.")

        def generate_content(self, **kwargs):
            self._check()
            return _Response()

        def embed_content(self, **kwargs):
            self._check()
            return _EmbedResult()

    class _Client:
        def __init__(self, api_key):
            self._api = _Api()
            self.models = _Models(self._api)

        def __del__(self):
            self._api.closed = True

    class _Types:
        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

        @staticmethod
        def EmbedContentConfig(**kwargs):
            return kwargs

    class _Genai:
        Client = _Client

    monkeypatch.setattr(gc, "_genai", _Genai)
    monkeypatch.setattr(gc, "_types", _Types)
    monkeypatch.setattr(gc, "HAS_SDK", True)
    garbage.collect()
    assert gc.generate_text("hoi", "k1") == "ok"
    assert gc.generate_text("hoi", "k1", json_mode=True) == "ok"
    assert gc.embed_text("tin", "k1") == [1.0]
