from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.tapmock.models import Exchange, RecordedRequest, RecordedResponse, Tape
from src.tapmock.replay import replay


class _Handler(BaseHTTPRequestHandler):
    payload = b'{"value":1}'

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextmanager
def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _tape() -> Tape:
    return Tape(
        exchanges=[
            Exchange(
                id="ex-001",
                request=RecordedRequest(method="GET", url="http://demo.local/api/x?a=1"),
                response=RecordedResponse(
                    status=200,
                    headers=[["Content-Type", "application/json"]],
                    body='{"value":1}',
                ),
            )
        ]
    )


def test_replay_matches_identical_response():
    _Handler.payload = b'{"value":1}'
    with _server() as url:
        results = replay(_tape(), url)
    assert results[0].matched
    assert results[0].issues == []


def test_replay_detects_changed_json_value():
    _Handler.payload = b'{"value":2}'
    with _server() as url:
        results = replay(_tape(), url)
    assert not results[0].matched
    assert any(issue.kind == "changed" and issue.path == "$.value" for issue in results[0].issues)


def test_replay_reports_connection_error():
    results = replay(_tape(), "http://127.0.0.1:1", timeout=1)
    assert not results[0].matched
    assert results[0].error
