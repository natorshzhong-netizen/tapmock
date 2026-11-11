from __future__ import annotations

import requests

from src.tapmock.mock import running_mock
from src.tapmock.models import Exchange, RecordedRequest, RecordedResponse, Tape


def _tape() -> Tape:
    return Tape(
        source="unit",
        exchanges=[
            Exchange(
                id="ex-001",
                request=RecordedRequest(method="GET", url="http://demo.local/api/hello?q=1"),
                response=RecordedResponse(
                    status=200,
                    headers=[["Content-Type", "application/json"]],
                    body='{"ok":true}',
                ),
            ),
            Exchange(
                id="ex-002",
                request=RecordedRequest(method="POST", url="http://demo.local/api/echo"),
                response=RecordedResponse(
                    status=201,
                    headers=[["Content-Type", "text/plain"]],
                    body="created",
                ),
            ),
        ],
    )


def test_mock_returns_recorded_response_and_marker():
    with running_mock(_tape()) as (server, url):
        response = requests.get(f"{url}/api/hello?q=1", timeout=5)
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert response.headers["X-Tapmock-Exchange"] == "ex-001"

        created = requests.post(f"{url}/api/echo", data="x", timeout=5)
        assert created.status_code == 201
        assert created.text == "created"
        assert created.headers["X-Tapmock-Exchange"] == "ex-002"

        missing = requests.get(f"{url}/api/missing", timeout=5)
        assert missing.status_code == 404
        assert server.unmatched == [{"method": "GET", "path": "/api/missing", "query": ""}]


def test_mock_cors_option():
    with running_mock(_tape(), cors=True) as (_, url):
        response = requests.options(f"{url}/api/hello", timeout=5)
        assert response.status_code == 204
        assert response.headers["Access-Control-Allow-Origin"] == "*"
