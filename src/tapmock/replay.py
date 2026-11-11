"""把 tape 里的请求重放到真实 target，并比较响应有没有变化。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

from .models import Exchange, Tape
from .tape import exchange_target

SKIP_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "accept-encoding",
}


@dataclass
class DiffIssue:
    kind: str
    path: str
    expected: str
    actual: str


@dataclass
class ReplayResult:
    exchange_id: str
    method: str
    path: str
    matched: bool
    status_ok: bool
    body_ok: bool
    issues: list[DiffIssue] = field(default_factory=list)
    error: str | None = None


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "…"


def diff_json(expected: Any, actual: Any, path: str = "$", limit: int = 20) -> list[DiffIssue]:
    issues: list[DiffIssue] = []
    if len(issues) >= limit:
        return issues
    if type(expected) is not type(actual):
        return [
            DiffIssue(
                kind="type",
                path=path,
                expected=_short(expected),
                actual=_short(actual),
            )
        ]
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}"
            if key not in actual:
                issues.append(DiffIssue("removed", child, _short(expected[key]), "—"))
            elif key not in expected:
                issues.append(DiffIssue("added", child, "—", _short(actual[key])))
            else:
                issues.extend(diff_json(expected[key], actual[key], child, limit))
            if len(issues) >= limit:
                break
        return issues
    if isinstance(expected, list):
        if len(expected) != len(actual):
            issues.append(DiffIssue("length", path, str(len(expected)), str(len(actual))))
        for index, (left, right) in enumerate(zip(expected, actual, strict=False)):
            issues.extend(diff_json(left, right, f"{path}[{index}]", limit))
            if len(issues) >= limit:
                break
        return issues
    if expected != actual:
        issues.append(DiffIssue("changed", path, _short(expected), _short(actual)))
    return issues


def _is_json(exchange: Exchange) -> bool:
    content_type = exchange.response.headers or []
    for name, value in content_type:
        if name.lower() == "content-type" and "json" in value.lower():
            return True
    return False


def compare_exchange(exchange: Exchange, response: requests.Response) -> list[DiffIssue]:
    issues: list[DiffIssue] = []
    if response.status_code != exchange.response.status:
        issues.append(
            DiffIssue("status", "$status", str(exchange.response.status), str(response.status_code))
        )

    expected_type = next(
        (value for name, value in exchange.response.headers if name.lower() == "content-type"),
        "",
    )
    actual_type = response.headers.get("content-type", "")
    if expected_type.split(";")[0].strip() != actual_type.split(";")[0].strip():
        issues.append(DiffIssue("content-type", "$headers.content-type", expected_type, actual_type))

    expected_body = exchange.response.body_bytes()
    if _is_json(exchange):
        try:
            expected_json = json.loads(expected_body)
            actual_json = response.json()
            issues.extend(diff_json(expected_json, actual_json))
        except (json.JSONDecodeError, requests.JSONDecodeError, UnicodeDecodeError):
            if expected_body != response.content:
                issues.append(
                    DiffIssue(
                        "body", "$", _short(expected_body.decode("utf-8", "replace")), _short(response.text)
                    )
                )
    elif expected_body != response.content:
        issues.append(
            DiffIssue(
                "body",
                "$",
                _short(expected_body.decode("utf-8", "replace")),
                _short(response.text[:500]),
            )
        )
    return issues


def replay(
    tape: Tape,
    target: str,
    *,
    timeout: float = 15.0,
    header_overrides: dict[str, str] | None = None,
) -> list[ReplayResult]:
    overrides = {name.lower(): value for name, value in (header_overrides or {}).items()}
    session = requests.Session()
    session.trust_env = False
    results: list[ReplayResult] = []

    for exchange in tape.exchanges:
        headers = [
            (name, value) for name, value in exchange.request.headers if name.lower() not in SKIP_HEADERS
        ]
        if overrides:
            names = {name.lower() for name, _ in headers}
            headers = [(name, value) for name, value in headers if name.lower() not in overrides]
            headers.extend((name, value) for name, value in overrides.items() if name not in names)

        url = exchange_target(exchange, target)
        try:
            response = session.request(
                exchange.request.method,
                url,
                headers=dict(headers),
                data=exchange.request.body_bytes() or None,
                timeout=timeout,
                allow_redirects=False,
            )
            issues = compare_exchange(exchange, response)
            results.append(
                ReplayResult(
                    exchange_id=exchange.id,
                    method=exchange.request.method,
                    path=exchange.path,
                    matched=not issues,
                    status_ok=not any(item.kind == "status" for item in issues),
                    body_ok=not any(
                        item.kind in ("body", "changed", "added", "removed", "length", "type")
                        for item in issues
                    ),
                    issues=issues,
                )
            )
        except requests.RequestException as exc:
            results.append(
                ReplayResult(
                    exchange_id=exchange.id,
                    method=exchange.request.method,
                    path=exchange.path,
                    matched=False,
                    status_ok=False,
                    body_ok=False,
                    error=str(exc)[:300],
                )
            )
    session.close()
    return results
