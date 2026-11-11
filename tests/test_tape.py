from __future__ import annotations

import json
from pathlib import Path

from src.tapmock.tape import TapeMatcher, TapeStore, load_tape, query_key


def _record(store: TapeStore, path: str = "/api/login", body: bytes = b'{"password":"p"}'):
    return store.append_exchange(
        method="POST",
        url=f"http://demo.local{path}?token=abc&q=1",
        request_headers=[("Authorization", "Bearer live-token"), ("Content-Type", "application/json")],
        request_body=body,
        status=200,
        response_headers=[("Set-Cookie", "session=xyz"), ("Content-Type", "application/json")],
        response_body=b'{"token":"live-token"}',
        duration_ms=7,
    )


def test_store_writes_redacted_tape(tmp_path: Path):
    path = tmp_path / "tape.json"
    store = TapeStore(path, source="unit")
    exchange = _record(store)
    assert exchange.request.headers[0][1] == "<redacted>"
    assert "abc" not in exchange.request.url
    assert "password" in exchange.request.body
    assert json.loads(exchange.response.body)["token"] == "<redacted>"
    assert "live-token" not in path.read_text(encoding="utf-8")

    loaded = load_tape(path)
    assert loaded.source == "unit"
    assert len(loaded.exchanges) == 1
    assert loaded.exchanges[0].id == "ex-001"


def test_matcher_is_query_order_insensitive_and_sequences_responses(tmp_path: Path):
    store = TapeStore(tmp_path / "tape.json")
    _record(store)
    _record(store, body=b'{"password":"p2"}')
    matcher = TapeMatcher(load_tape(tmp_path / "tape.json"))

    first = matcher.match("POST", "/api/login", "q=1&token=<redacted>")
    second = matcher.match("POST", "/api/login", "token=<redacted>&q=1")
    third = matcher.match("POST", "/api/login", "token=<redacted>&q=1")
    assert first is not None and second is not None and third is not None
    assert first.id == "ex-001"
    assert second.id == "ex-002"
    assert third.id == "ex-002"  # 超出录制次数时复用最后一条
    assert matcher.match("GET", "/api/login") is None


def test_query_key_normalizes_order():
    assert query_key("b=2&a=1") == query_key("a=1&b=2")
