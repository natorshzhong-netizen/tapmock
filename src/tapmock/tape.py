"""Tape 的读写、脱敏与匹配索引。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .models import Exchange, RecordedRequest, RecordedResponse, Tape, encode_body
from .redact import Redactor


def query_key(query: str) -> str:
    pairs = sorted(parse_qsl(query, keep_blank_values=True))
    return "&".join(f"{key}={value}" for key, value in pairs)


def _content_type(headers: list[tuple[str, str]] | list[list[str]]) -> str:
    for name, value in headers:
        if str(name).lower() == "content-type":
            return str(value)
    return ""


def load_tape(path: str | Path) -> Tape:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Tape.from_dict(payload)


class TapeStore:
    """录音时用：每次响应后追加并落盘，进程被 Ctrl+C 也不会丢已录内容。"""

    def __init__(
        self,
        path: str | Path,
        *,
        source: str = "",
        extra_redact: list[str] | tuple[str, ...] = (),
        append: bool = False,
    ):
        self.path = Path(path)
        self.redactor = Redactor(extra_redact)
        if append and self.path.exists():
            self.tape = load_tape(self.path)
        else:
            self.tape = Tape.new(source)
        self.source = source

    @property
    def count(self) -> int:
        return len(self.tape.exchanges)

    def append_exchange(
        self,
        *,
        method: str,
        url: str,
        request_headers: list[tuple[str, str]],
        request_body: bytes,
        status: int,
        response_headers: list[tuple[str, str]],
        response_body: bytes,
        duration_ms: int = 0,
    ) -> Exchange:
        clean_url, url_fields = self.redactor.url(url)
        clean_req_headers, req_header_fields = self.redactor.headers(request_headers)
        clean_resp_headers, resp_header_fields = self.redactor.headers(response_headers)
        clean_req_body, req_body_fields = self.redactor.body(request_body, _content_type(request_headers))
        clean_resp_body, resp_body_fields = self.redactor.body(response_body, _content_type(response_headers))

        redactions = [f"request.{item}" for item in (*url_fields, *req_header_fields, *req_body_fields)]
        redactions += [f"response.{item}" for item in (*resp_header_fields, *resp_body_fields)]

        exchange = Exchange(
            id=f"ex-{len(self.tape.exchanges) + 1:03d}",
            request=RecordedRequest(
                method=method.upper(),
                url=clean_url,
                headers=[list(pair) for pair in clean_req_headers],
                **encode_body(clean_req_body),
            ),
            response=RecordedResponse(
                status=int(status),
                headers=[list(pair) for pair in clean_resp_headers],
                **encode_body(clean_resp_body),
            ),
            duration_ms=int(duration_ms),
            redactions=redactions,
        )
        self.tape.exchanges.append(exchange)
        self.save()
        return exchange

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.tape.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class TapeMatcher:
    """Mock 时用：method + path + query 精确匹配，重复请求按录制顺序返回。"""

    def __init__(self, tape: Tape):
        self.tape = tape
        self.index: dict[tuple[str, str, str], list[Exchange]] = defaultdict(list)
        for exchange in tape.exchanges:
            key = (exchange.request.method.upper(), exchange.path, query_key(exchange.query))
            self.index[key].append(exchange)
        self.counters: dict[tuple[str, str, str], int] = defaultdict(int)

    def match(self, method: str, path: str, query: str = "") -> Exchange | None:
        key = (method.upper(), path or "/", query_key(query))
        items = self.index.get(key)
        if not items:
            return None
        position = min(self.counters[key], len(items) - 1)
        self.counters[key] += 1
        return items[position]

    def reset(self) -> None:
        self.counters.clear()

    @property
    def size(self) -> int:
        return len(self.tape.exchanges)


def exchange_target(exchange: Exchange, base_url: str) -> str:
    """把录制时的 URL 换到新的 target 上，保留 path/query。"""
    parts = urlsplit(exchange.request.url)
    base = base_url.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{base}{parts.path or '/'}{query}"
