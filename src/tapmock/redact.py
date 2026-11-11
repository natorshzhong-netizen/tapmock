"""在写盘之前脱敏：请求头、URL query、JSON / form body。

原则：保留结构（字段名、数组长度），只替换值，Mock 匹配不会因为脱敏而失效。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "<redacted>"

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
}

_SENSITIVE_WORDS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "secret",
    "clientsecret",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "sessionid",
    "csrf",
    "csrftoken",
    "signature",
    "sig",
    "email",
    "phone",
    "mobile",
}


def _normalize(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def is_sensitive_key(word: str, extra: set[str] | None = None) -> bool:
    normalized = _normalize(word)
    if not normalized:
        return False
    if normalized in _SENSITIVE_WORDS:
        return True
    if extra and normalized in extra:
        return True
    return normalized.endswith(("token", "secret", "password", "apikey"))


class Redactor:
    def __init__(self, extra_keys: list[str] | tuple[str, ...] = ()):
        self.extra = {_normalize(item) for item in extra_keys if item.strip()}

    def headers(
        self, headers: list[tuple[str, str]] | list[list[str]]
    ) -> tuple[list[tuple[str, str]], list[str]]:
        result: list[tuple[str, str]] = []
        fields: list[str] = []
        for raw_name, raw_value in headers:
            name = str(raw_name)
            if name.lower() in SENSITIVE_HEADERS:
                result.append((name, REDACTED))
                fields.append(f"headers.{name.lower()}")
            else:
                result.append((name, str(raw_value)))
        return result, fields

    def url(self, url: str) -> tuple[str, list[str]]:
        parts = urlsplit(url)
        if not parts.query:
            return url, []
        fields: list[str] = []
        pairs: list[tuple[str, str]] = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if is_sensitive_key(key, self.extra):
                pairs.append((key, REDACTED))
                fields.append(f"query.{key}")
            else:
                pairs.append((key, value))
        rebuilt = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(pairs, doseq=True), parts.fragment)
        )
        return rebuilt, fields

    def _json(self, value: Any, path: str) -> tuple[Any, list[str]]:
        fields: list[str] = []
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for key, item in value.items():
                key_path = f"{path}.{key}" if path else str(key)
                if is_sensitive_key(str(key), self.extra):
                    output[key] = REDACTED
                    fields.append(key_path)
                else:
                    output[key], child = self._json(item, key_path)
                    fields.extend(child)
            return output, fields
        if isinstance(value, list):
            output_list = []
            for index, item in enumerate(value):
                redacted_item, child = self._json(item, f"{path}[{index}]")
                output_list.append(redacted_item)
                fields.extend(child)
            return output_list, fields
        return value, fields

    def body(self, raw: bytes, content_type: str) -> tuple[bytes, list[str]]:
        if not raw:
            return raw, []
        media = content_type.split(";")[0].strip().lower()
        stripped = raw.lstrip()

        if media == "application/json" or (not media and stripped[:1] in (b"{", b"[")):
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return raw, []
            redacted, fields = self._json(payload, "body")
            return json.dumps(redacted, ensure_ascii=False).encode("utf-8"), fields

        if media == "application/x-www-form-urlencoded":
            try:
                pairs = parse_qsl(raw.decode("utf-8", errors="strict"), keep_blank_values=True)
            except UnicodeDecodeError:
                return raw, []
            output: list[tuple[str, str]] = []
            fields = []
            for key, value in pairs:
                if is_sensitive_key(key, self.extra):
                    output.append((key, REDACTED))
                    fields.append(f"body.{key}")
                else:
                    output.append((key, value))
            return urlencode(output).encode("utf-8"), fields

        return raw, []
