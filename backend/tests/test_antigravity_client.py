"""
Client gọi Antigravity CLI — phải phân biệt "AI trả lời" với "AI không trả lời gì".

Lỗi đã gặp thật: agy hết --print-timeout vẫn in status SUCCESS với response rỗng,
0 token, 0 lượt. Client cũ coi đó là thành công, nên job bản tin báo nhầm "schema
không hợp lệ" trong khi nguyên nhân là app Antigravity chưa mở / hết phiên đăng nhập.
Không test nào gọi agy thật: subprocess.run được thay bằng bản giả.
"""
from __future__ import annotations

import subprocess

import pytest

from jobs import antigravity_client as ac

EMPTY = '{"status":"SUCCESS","response":"","num_turns":0,"usage":{"input_tokens":0,"output_tokens":0}}'


def _fake_run(stdout, stderr=""):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=stderr)

    return run


@pytest.fixture(autouse=True)
def _co_agy(monkeypatch):
    monkeypatch.setattr(ac, "find_agy", lambda: "agy.exe")


def test_het_gio_tra_ket_qua_rong_thi_bao_loi_ro_nguyen_nhan(monkeypatch):
    out = (
        "[agy] print timeout after 30s with turn in progress; returning partial output\n"
        + EMPTY
    )
    monkeypatch.setattr(ac.subprocess, "run", _fake_run(out))
    with pytest.raises(ac.AntigravityError, match="không trả lời"):
        ac.run_agent("xin chao")


def test_success_nhung_rong_hoan_toan_cung_la_loi(monkeypatch):
    monkeypatch.setattr(ac.subprocess, "run", _fake_run(EMPTY))
    with pytest.raises(ac.AntigravityError, match="đăng nhập"):
        ac.run_agent("xin chao")


def test_co_schema_ma_tra_rong_khong_bi_do_loi_cho_schema(monkeypatch):
    monkeypatch.setattr(ac.subprocess, "run", _fake_run(EMPTY))
    with pytest.raises(ac.AntigravityError) as excinfo:
        ac.run_agent("xin chao", schema={"type": "object", "properties": {}})
    assert "schema" not in str(excinfo.value)


def test_ket_qua_that_van_tra_binh_thuong(monkeypatch):
    out = '{"status":"SUCCESS","response":"OK","num_turns":1,"usage":{"input_tokens":20000,"output_tokens":3}}'
    monkeypatch.setattr(ac.subprocess, "run", _fake_run(out))
    result = ac.run_agent("xin chao")
    assert result.text == "OK"
    assert result.input_tokens == 20000


def test_chua_dang_nhap_van_bao_nhu_cu(monkeypatch):
    monkeypatch.setattr(ac.subprocess, "run", _fake_run("", "Error: not logged into Antigravity"))
    with pytest.raises(ac.AntigravityError, match="chưa đăng nhập"):
        ac.run_agent("xin chao")


def test_qua_han_cho_cua_client_co_kem_goi_y(monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(ac.subprocess, "run", run)
    with pytest.raises(ac.AntigravityError, match="app Antigravity"):
        ac.run_agent("xin chao", timeout=5)
