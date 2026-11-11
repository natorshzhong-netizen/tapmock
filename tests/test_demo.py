from __future__ import annotations

from pathlib import Path

import pytest

from src.tapmock.demo import run_demo
from src.tapmock.tape import load_tape

pytestmark = pytest.mark.proxy


def test_demo_records_redacts_and_replays(tmp_path: Path):
    tape_path = tmp_path / "tape.json"
    summary = run_demo(tape_path, tmp_path / "demo.json")

    assert summary["exchanges"] == 4
    assert [call["exchange"] for call in summary["mock_calls"][:4]] == [
        "ex-001",
        "ex-002",
        "ex-003",
        "ex-004",
    ]
    assert summary["mock_calls"][-1]["status"] == 404
    assert summary["unmatched"] == [{"method": "GET", "path": "/api/unmatched", "query": ""}]

    raw = tape_path.read_text(encoding="utf-8")
    assert "secret123" not in raw
    assert "tok_live_abc123" not in raw
    assert "alice@example.com" not in raw

    tape = load_tape(tape_path)
    assert tape.source == "demo:local-upstream"
    assert all(exchange.request.url.startswith("http://demo.local/") for exchange in tape.exchanges)
