"""
Gọi Antigravity CLI (`agy`) ở chế độ không tương tác để lấy phân tích AI.

Vì sao dùng CLI thay vì API key: CLI đã đăng nhập sẵn bằng tài khoản Google của
người dùng và cho truy cập cả Gemini 3.8 Flash lẫn Claude Opus 4.6 mà không cần
quản lý khoá bí mật nào.

Đánh đổi (đo thực tế trên máy dev, 2026-09):
- Mỗi lần gọi mất ~11-12 giây và nạp ~20.000 token system prompt của agent.
  => CHỈ dùng cho job chạy nền theo lịch, KHÔNG gọi trong lúc phục vụ request.
- Xác thực là OAuth tài khoản cá nhân nằm trong keyring của máy.
  => Không deploy được lên Railway/Vercel. Job chạy trên máy người dùng, ghi
     kết quả vào DB; app web chỉ đọc lại từ DB.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# Thứ tự ưu tiên khi dò đường dẫn agy.exe.
_AGY_CANDIDATES = (
    os.path.expandvars(r"%LOCALAPPDATA%\agy\bin\agy.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\agy\bin\agy.exe"),
    str(Path.home() / ".local" / "bin" / "agy"),
    "agy",
)

# Model nhanh/rẻ cho việc gom, phân loại, trích xuất.
MODEL_FAST = "gemini-3.8-flash-low"
# Model suy luận sâu cho việc viết bản tin và đánh giá tác động.
MODEL_DEEP = "claude-opus-4-6-thinking"

DEFAULT_TIMEOUT_SECONDS = 300


class AntigravityError(RuntimeError):
    """Gọi CLI thất bại — thiếu binary, chưa đăng nhập, timeout, hoặc agent lỗi."""


@dataclass
class AgentResult:
    """Kết quả một lần gọi. `data` chỉ có khi truyền schema."""

    text: str
    data: Optional[Dict[str, Any]]
    model: str
    duration_seconds: float
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def find_agy() -> Optional[str]:
    """Đường dẫn agy.exe, hoặc None nếu chưa cài."""
    for candidate in _AGY_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def is_available() -> bool:
    return find_agy() is not None


def _write_schema(schema: Dict[str, Any]) -> str:
    """
    Ghi schema ra file tạm KHÔNG BOM.

    Quan trọng: nếu file có BOM, agy coi toàn bộ nội dung là một chuỗi mô tả
    thay vì parse thành JSON schema, và agent lỗi ngay lập tức.
    """
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8", newline="\n"
    )
    try:
        json.dump(schema, handle, ensure_ascii=False)
    finally:
        handle.close()
    return handle.name


def _parse_output(stdout: str) -> Dict[str, Any]:
    """
    Lấy bản ghi JSON kết quả từ stdout.

    agy in lẫn log và tiến trình; dòng kết quả là dòng JSON cuối cùng có khoá
    "status". Duyệt ngược để bỏ qua phần nhiễu phía trên.
    """
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{") or '"status"' not in line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AntigravityError(
        "Không đọc được kết quả JSON từ agy. Đầu ra cuối:\n" + stdout[-800:]
    )


# agy hết --print-timeout mà mô hình chưa trả lời vẫn in status SUCCESS, kèm response
# rỗng, 0 token, 0 lượt. Coi đó là thành công thì job ghi ra một bản tin rỗng, hoặc báo
# nhầm "schema không hợp lệ". Trên thực tế gần như luôn là app Antigravity chưa mở hoặc
# phiên đăng nhập đã hết hạn — nên nói thẳng điều đó.
_NO_RESPONSE_HINT = (
    "Antigravity không trả lời: mô hình chưa nhận được yêu cầu (0 token, 0 lượt). "
    "Thường là do app Antigravity chưa mở hoặc phiên đăng nhập đã hết hạn — mở app "
    "Antigravity, đăng nhập lại, rồi chạy lại job."
)


def run_agent(
    prompt: str,
    *,
    model: str = MODEL_FAST,
    schema: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: Optional[str] = None,
) -> AgentResult:
    """
    Chạy một prompt và trả kết quả.

    Truyền `schema` để ép output đúng cấu trúc — luôn nên dùng cho job tự động,
    vì parse văn bản tự do của LLM là nguồn lỗi bất tận.
    """
    agy = find_agy()
    if not agy:
        raise AntigravityError(
            "Không tìm thấy agy.exe. Cài Antigravity CLI, hoặc đặt biến môi trường "
            "PATH trỏ tới thư mục chứa nó."
        )

    command = [
        agy,
        "--print",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        # Job chạy nền không có ai bấm xác nhận.
        "--dangerously-skip-permissions",
        # Tắt slash command để một prompt bắt đầu bằng '/' không bị hiểu nhầm.
        "--disable-slash-commands",
        "--print-timeout",
        f"{max(60, timeout - 30)}s",
    ]

    schema_path = None
    if schema is not None:
        schema_path = _write_schema(schema)
        command += ["--json-schema", schema_path]

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise AntigravityError(f"agy quá {timeout}s chưa trả lời. {_NO_RESPONSE_HINT}") from exc
    finally:
        if schema_path:
            try:
                os.unlink(schema_path)
            except OSError:
                pass

    elapsed = time.monotonic() - started
    stdout = completed.stdout or ""

    # Chưa đăng nhập là lỗi hay gặp nhất và thông báo gốc rất khó hiểu.
    combined = stdout + (completed.stderr or "")
    if "not logged into Antigravity" in combined:
        raise AntigravityError(
            "Antigravity CLI chưa đăng nhập. Mở app Antigravity và đăng nhập lại, "
            "rồi chạy job này."
        )

    if "print timeout" in combined and "turn in progress" in combined:
        raise AntigravityError(_NO_RESPONSE_HINT)

    payload = _parse_output(stdout)
    usage = payload.get("usage") or {}
    if (
        payload.get("status") == "SUCCESS"
        and not payload.get("num_turns")
        and not payload.get("response")
        and not payload.get("structured_output")
        and not int(usage.get("input_tokens") or 0)
    ):
        raise AntigravityError(_NO_RESPONSE_HINT)

    if payload.get("status") != "SUCCESS":
        raise AntigravityError(
            f"agy trả về status={payload.get('status')}: {payload.get('error') or 'không rõ lý do'}"
        )

    data = payload.get("structured_output")
    if schema is not None and not isinstance(data, dict):
        raise AntigravityError(
            "Đã yêu cầu schema nhưng agy không trả structured_output. "
            "Kiểm tra schema có hợp lệ không."
        )

    return AgentResult(
        text=payload.get("response") or "",
        data=data if isinstance(data, dict) else None,
        model=model,
        duration_seconds=round(elapsed, 2),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )
