from __future__ import annotations

from src.tapmock.models import Exchange, RecordedRequest, RecordedResponse, Tape
from src.tapmock.view import render_view


def _tape(body: str = '{"password":"<redacted>"}') -> Tape:
    return Tape(
        source="unit",
        created_at="2026-11-11T00:00:00+00:00",
        exchanges=[
            Exchange(
                id="ex-001",
                request=RecordedRequest(
                    method="POST",
                    url="http://demo.local/api/login",
                    headers=[["Authorization", "<redacted>"]],
                    body='{"password":"<redacted>"}',
                ),
                response=RecordedResponse(
                    status=200,
                    headers=[["Content-Type", "application/json"]],
                    body=body,
                ),
                duration_ms=12,
                redactions=["request.body.password", "request.headers.authorization"],
            )
        ],
    )


def test_view_marks_redacted_values():
    html = render_view(_tape())
    assert "<redacted>" not in html
    assert "&lt;redacted&gt;" in html
    assert "request.body.password" in html


def test_view_escapes_response_body():
    evil = '{"x":"<script>alert(1)</script>"}'
    html = render_view(_tape(body=evil))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
