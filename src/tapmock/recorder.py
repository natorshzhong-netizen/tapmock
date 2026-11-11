"""mitmproxy 侧的录制逻辑，以及启动/停止 mitmdump 的进程管理。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .tape import TapeStore

SRC_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = Path(__file__).with_name("addon.py")


def store_from_env() -> TapeStore:
    tape = os.environ.get("TAPMOCK_TAPE")
    if not tape:
        raise RuntimeError("TAPMOCK_TAPE 未设置")
    extra = [item for item in os.environ.get("TAPMOCK_REDACT", "").split(",") if item]
    return TapeStore(tape, source=os.environ.get("TAPMOCK_SOURCE", ""), extra_redact=extra)


def record_flow(store: TapeStore, flow) -> None:
    """mitmproxy response 钩子调用的纯逻辑，方便单测替代 flow 对象。"""
    response = getattr(flow, "response", None)
    if response is None:
        return
    request = flow.request
    started = getattr(request, "timestamp_start", None)
    ended = getattr(response, "timestamp_end", None)
    duration_ms = int((ended - started) * 1000) if started and ended else 0

    store.append_exchange(
        method=str(request.method),
        url=str(request.pretty_url),
        request_headers=list(request.headers.items(multi=True)),
        request_body=request.get_content() or b"",
        status=int(response.status_code),
        response_headers=list(response.headers.items(multi=True)),
        response_body=response.get_content() or b"",
        duration_ms=max(0, duration_ms),
    )


def _mitmdump_path() -> str:
    candidate = Path(sys.executable).with_name("mitmdump.exe" if os.name == "nt" else "mitmdump")
    if candidate.exists():
        return str(candidate)
    from shutil import which

    found = which("mitmdump")
    if found:
        return found
    raise RuntimeError("找不到 mitmdump，请先 `pip install mitmproxy`")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


@contextmanager
def recorder_process(
    tape_path: str | Path,
    *,
    port: int,
    target: str | None = None,
    extra_redact: list[str] | tuple[str, ...] = (),
    startup_timeout: float = 20.0,
) -> Generator[subprocess.Popen, None, None]:
    """启动 mitmdump；target 为空时以普通正向代理运行。"""
    command = [
        _mitmdump_path(),
        "-q",
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        str(port),
        "-s",
        str(ADDON_PATH),
    ]
    source = "forward proxy"
    if target:
        command += ["--mode", f"reverse:{target}"]
        source = f"reverse:{target}"

    env = os.environ.copy()
    env["TAPMOCK_TAPE"] = str(Path(tape_path).resolve())
    env["TAPMOCK_SOURCE"] = source
    env["TAPMOCK_REDACT"] = ",".join(extra_redact)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_ROOT) + (os.pathsep + existing if existing else "")

    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"mitmdump 启动失败：{stderr.strip()[-800:]}")
            if _port_open(port):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"mitmdump 在 {startup_timeout:.0f}s 内没有开始监听 {port}")
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stderr:
            process.stderr.close()
