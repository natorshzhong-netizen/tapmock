from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlsplit

from src.tapmock.redact import Redactor


def test_headers_are_redacted_case_insensitively():
    redactor = Redactor()
    clean, fields = redactor.headers(
        [("Authorization", "Bearer secret"), ("X-Api-Key", "k1"), ("Content-Type", "application/json")]
    )
    assert dict(clean)["Authorization"] == "<redacted>"
    assert dict(clean)["X-Api-Key"] == "<redacted>"
    assert dict(clean)["Content-Type"] == "application/json"
    assert set(fields) == {"headers.authorization", "headers.x-api-key"}


def test_query_params_are_redacted_and_order_kept():
    redactor = Redactor()
    url, fields = redactor.url("http://demo.local/api?token=abc&q=1&password=p")
    pairs = dict(parse_qsl(urlsplit(url).query))
    assert pairs["token"] == "<redacted>"
    assert pairs["password"] == "<redacted>"
    assert pairs["q"] == "1"
    assert set(fields) == {"query.token", "query.password"}


def test_json_body_redacts_nested_secrets_but_keeps_shape():
    redactor = Redactor()
    raw = json.dumps(
        {
            "username": "alice",
            "password": "p",
            "access_token": "t",
            "profile": {"email": "a@b.com", "phone": "123", "tier": "gold"},
            "items": [{"api_key": "k", "name": "x"}],
        }
    ).encode()
    clean, fields = redactor.body(raw, "application/json; charset=utf-8")
    payload = json.loads(clean)
    assert payload["username"] == "alice"
    assert payload["password"] == "<redacted>"
    assert payload["access_token"] == "<redacted>"
    assert payload["profile"]["email"] == "<redacted>"
    assert payload["profile"]["tier"] == "gold"
    assert payload["items"][0]["api_key"] == "<redacted>"
    assert "body.profile.email" in fields


def test_form_body_and_extra_keys():
    redactor = Redactor(extra_keys=["device_id"])
    clean, fields = redactor.body(b"user=alice&password=p&device_id=d", "application/x-www-form-urlencoded")
    pairs = dict(parse_qsl(clean.decode()))
    assert pairs["user"] == "alice"
    assert pairs["password"] == "<redacted>"
    assert pairs["device_id"] == "<redacted>"
    assert set(fields) == {"body.password", "body.device_id"}


def test_plain_text_body_untouched():
    redactor = Redactor()
    raw = b"hello world"
    clean, fields = redactor.body(raw, "text/plain")
    assert clean == raw
    assert fields == []
