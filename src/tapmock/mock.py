"""从 tape 回放的 Mock HTTP 服务。"""

from __future__ import annotations

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .models import Tape
from .tape import TapeMatcher

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
    "date",
    "server",
}
MAX_BODY = 10 * 1024 * 1024


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, tape: Tape, cors: bool = False):
        self.matcher = TapeMatcher(tape)
        self.cors = cors
        self.unmatched: list[dict] = []
        super().__init__(address, MockHandler)


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        server: MockServer = self.server  # type: ignore[assignment]
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        if server.cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Expose-Headers", "X-Tapmock-Exchange")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _handle(self) -> None:
        server: MockServer = self.server  # type: ignore[assignment]
        if self.command == "OPTIONS" and server.cors:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, [("Content-Type", "application/json")], b'{"error":"body too large"}')
            return
        if length:
            self.rfile.read(length)

        parsed = urlsplit(self.path)
        exchange = server.matcher.match(self.command, parsed.path, parsed.query)
        if exchange is None:
            server.unmatched.append({"method": self.command, "path": parsed.path, "query": parsed.query})
            payload = json.dumps(
                {
                    "error": "no matching exchange",
                    "method": self.command,
                    "path": parsed.path,
                    "query": parsed.query,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(404, [("Content-Type", "application/json; charset=utf-8")], payload)
            return

        headers = [
            (name, value) for name, value in exchange.response.headers if name.lower() not in HOP_BY_HOP
        ]
        headers.append(("X-Tapmock-Exchange", exchange.id))
        self._send(exchange.response.status, headers, exchange.response.body_bytes())

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle
    do_OPTIONS = _handle


@contextmanager
def running_mock(
    tape: Tape, *, port: int = 0, cors: bool = False
) -> Generator[tuple[MockServer, str], None, None]:
    server = MockServer(("127.0.0.1", port), tape, cors=cors)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield server, url
    finally:
        server.shutdown()
        server.server_close()
