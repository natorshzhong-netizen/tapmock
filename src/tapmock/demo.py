"""端到端演示：录制 → 脱敏 → Mock 回放，全程本地、不需要浏览器配置代理。"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .mock import running_mock
from .recorder import recorder_process
from .tape import load_tape


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _json(self, status: int, payload: dict, extra: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/products":
            self._json(
                200,
                {
                    "items": [
                        {"id": "kb-01", "name": "机械键盘", "price": 299},
                        {"id": "ms-02", "name": "无线鼠标", "price": 129},
                    ]
                },
            )
        elif path == "/api/orders":
            if not self.headers.get("Authorization"):
                self._json(401, {"error": "missing authorization"})
                return
            self._json(200, {"orders": [{"id": "A1001", "status": "shipped", "amount": 299}]})
        elif path == "/api/profile":
            self._json(
                200,
                {
                    "name": "alice",
                    "email": "alice@example.com",
                    "phone": "13800138000",
                    "tier": "gold",
                },
            )
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/login":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "bad json"})
            return
        if payload.get("username") == "alice" and payload.get("password") == "secret123":
            self._json(
                200,
                {"token": "tok_live_abc123", "user": {"name": "alice", "tier": "gold"}},
                extra={"Set-Cookie": "session=live-cookie-xyz; HttpOnly"},
            )
        else:
            self._json(401, {"error": "bad credentials"})


@contextmanager
def running_upstream() -> Generator[str, None, None]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _exercise(base_url: str) -> list[tuple[str, str, int]]:
    session = _session()
    login = session.post(
        f"{base_url}/api/login",
        json={"username": "alice", "password": "secret123"},
        timeout=10,
    )
    token = login.json().get("token", "")
    results = [
        ("POST", "/api/login", login.status_code),
        ("GET", "/api/products", session.get(f"{base_url}/api/products", timeout=10).status_code),
        (
            "GET",
            "/api/orders",
            session.get(
                f"{base_url}/api/orders",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            ).status_code,
        ),
        ("GET", "/api/profile", session.get(f"{base_url}/api/profile", timeout=10).status_code),
    ]
    session.close()
    return results


def run_demo(tape_path: str | Path, report_path: str | Path) -> dict:
    tape_path = Path(tape_path)
    if tape_path.exists():
        tape_path.unlink()

    with running_upstream() as upstream:
        port = _free_port()
        with recorder_process(tape_path, port=port, target=upstream):
            proxy = f"http://127.0.0.1:{port}"
            recorded = _exercise(proxy)

    tape = load_tape(tape_path)
    if len(tape.exchanges) != len(recorded):
        raise RuntimeError(f"录制数量不符：期望 {len(recorded)}，实际 {len(tape.exchanges)}")

    # 演示站端口是随机的；把 host 归一成稳定值，tape 可以安全提交和分享。
    from urllib.parse import urlsplit, urlunsplit

    for exchange in tape.exchanges:
        parts = urlsplit(exchange.request.url)
        exchange.request.url = urlunsplit(("http", "demo.local", parts.path, parts.query, ""))
    tape.source = "demo:local-upstream"
    tape_path.write_text(json.dumps(tape.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    matched: list[dict] = []
    with running_mock(tape) as (server, mock_url):
        session = _session()
        login = session.post(
            f"{mock_url}/api/login",
            json={"username": "alice", "password": "secret123"},
            timeout=10,
        )
        token = login.json().get("token", "")
        calls = [
            ("POST", "/api/login", login),
            ("GET", "/api/products", session.get(f"{mock_url}/api/products", timeout=10)),
            (
                "GET",
                "/api/orders",
                session.get(
                    f"{mock_url}/api/orders",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                ),
            ),
            ("GET", "/api/profile", session.get(f"{mock_url}/api/profile", timeout=10)),
            ("GET", "/api/unmatched", session.get(f"{mock_url}/api/unmatched", timeout=10)),
        ]
        session.close()
        for method, path, response in calls:
            matched.append(
                {
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "exchange": response.headers.get("X-Tapmock-Exchange"),
                }
            )

    redactions = sorted({item for exchange in tape.exchanges for item in exchange.redactions})
    summary = {
        "tape": str(tape_path),
        "exchanges": len(tape.exchanges),
        "redactions": redactions,
        "mock_calls": matched,
        "unmatched": server.unmatched,
    }
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
