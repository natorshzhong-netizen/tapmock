"""Tape 的数据模型与 JSON 编解码。"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def encode_body(raw: bytes | None) -> dict[str, str]:
    if raw is None:
        return {}
    try:
        return {"body": raw.decode("utf-8")}
    except UnicodeDecodeError:
        return {"body_base64": base64.b64encode(raw).decode("ascii")}


def decode_body(payload: dict[str, Any]) -> bytes:
    if payload.get("body") is not None:
        return str(payload["body"]).encode("utf-8")
    if payload.get("body_base64") is not None:
        return base64.b64decode(payload["body_base64"])
    return b""


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: list[list[str]] = field(default_factory=list)
    body: str | None = None
    body_base64: str | None = None

    def body_bytes(self) -> bytes:
        return decode_body({"body": self.body, "body_base64": self.body_base64})

    def header(self, name: str) -> str | None:
        target = name.lower()
        for key, value in self.headers:
            if key.lower() == target:
                return value
        return None


@dataclass
class RecordedResponse:
    status: int
    headers: list[list[str]] = field(default_factory=list)
    body: str | None = None
    body_base64: str | None = None

    def body_bytes(self) -> bytes:
        return decode_body({"body": self.body, "body_base64": self.body_base64})


@dataclass
class Exchange:
    id: str
    request: RecordedRequest
    response: RecordedResponse
    duration_ms: int = 0
    redactions: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        from urllib.parse import urlsplit

        return urlsplit(self.request.url).path or "/"

    @property
    def query(self) -> str:
        from urllib.parse import urlsplit

        return urlsplit(self.request.url).query


@dataclass
class Tape:
    version: int = 1
    created_at: str = ""
    source: str = ""
    exchanges: list[Exchange] = field(default_factory=list)

    @classmethod
    def new(cls, source: str = "") -> Tape:
        return cls(
            version=1,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            source=source,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tape:
        exchanges: list[Exchange] = []
        for item in data.get("exchanges", []):
            request_data = item.get("request", {})
            response_data = item.get("response", {})
            exchanges.append(
                Exchange(
                    id=str(item.get("id", f"ex-{len(exchanges) + 1:03d}")),
                    request=RecordedRequest(
                        method=str(request_data.get("method", "GET")),
                        url=str(request_data.get("url", "")),
                        headers=[list(pair) for pair in request_data.get("headers", [])],
                        body=request_data.get("body"),
                        body_base64=request_data.get("body_base64"),
                    ),
                    response=RecordedResponse(
                        status=int(response_data.get("status", 200)),
                        headers=[list(pair) for pair in response_data.get("headers", [])],
                        body=response_data.get("body"),
                        body_base64=response_data.get("body_base64"),
                    ),
                    duration_ms=int(item.get("duration_ms", 0)),
                    redactions=list(item.get("redactions", [])),
                )
            )
        return cls(
            version=int(data.get("version", 1)),
            created_at=str(data.get("created_at", "")),
            source=str(data.get("source", "")),
            exchanges=exchanges,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["count"] = len(self.exchanges)
        return payload
