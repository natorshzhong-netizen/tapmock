"""四项可回归评测：脱敏、Mock 匹配、回放 diff、端到端录放。

python eval/run_eval.py
"""

from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from src.tapmock.demo import run_demo  # noqa: E402
from src.tapmock.mock import running_mock  # noqa: E402
from src.tapmock.replay import replay  # noqa: E402
from src.tapmock.tape import TapeStore, load_tape  # noqa: E402

RESULTS_DIR = ROOT / "eval" / "results"
TOTAL = 20


class TargetHandler(BaseHTTPRequestHandler):
    changed: set[int] = set()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        try:
            index = int(self.path.rsplit("/", 1)[-1].split("?")[0])
        except ValueError:
            index = 0
        value = index + 1 if index in self.changed else index
        body = json.dumps({"token": "<redacted>", "value": value}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextmanager
def target_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _fixture_tape(path: Path):
    store = TapeStore(path, source="eval")
    for index in range(1, TOTAL + 1):
        store.append_exchange(
            method="POST",
            url=f"http://demo.local/api/item/{index}?token=secret-{index}",
            request_headers=[
                ("Authorization", f"Bearer secret-{index}"),
                ("Content-Type", "application/json"),
            ],
            request_body=json.dumps({"password": f"secret-{index}", "value": index}).encode(),
            status=200,
            response_headers=[
                ("Content-Type", "application/json"),
                ("Set-Cookie", f"session=secret-{index}"),
            ],
            response_body=json.dumps({"token": f"resp-secret-{index}", "value": index}).encode(),
            duration_ms=5,
        )
    return load_tape(path)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tape_path = RESULTS_DIR / "fixture-tape.json"
    tape = _fixture_tape(tape_path)
    raw = tape_path.read_text(encoding="utf-8")
    leaks = sum(raw.count(f"secret-{index}") for index in range(1, TOTAL + 1))
    leaks += sum(raw.count(f"resp-secret-{index}") for index in range(1, TOTAL + 1))

    hits = 0
    with running_mock(tape) as (server, url):
        session = requests.Session()
        session.trust_env = False
        for index in range(1, TOTAL + 1):
            response = session.post(
                f"{url}/api/item/{index}",
                params={"token": "<redacted>"},
                json={"password": "<redacted>", "value": index},
                timeout=5,
            )
            if response.status_code == 200 and response.headers.get("X-Tapmock-Exchange"):
                hits += 1
        missing = session.get(f"{url}/api/missing", timeout=5)
        session.close()
    unmatched_ok = missing.status_code == 404 and len(server.unmatched) == 1

    TargetHandler.changed = set(range(1, 6))
    with target_server() as target:
        results = replay(tape, target)
    detected = sum(1 for item in results if not item.matched)
    false_positives = sum(
        1 for item in results if item.matched is False and int(item.path.rsplit("/", 1)[-1]) > 5
    )

    demo = run_demo(RESULTS_DIR / "demo-tape.json", RESULTS_DIR / "demo.json")
    demo_hits = sum(1 for call in demo["mock_calls"][:4] if call["exchange"])

    checks = {
        "脱敏无泄漏": leaks == 0,
        "Mock 全命中": hits == TOTAL,
        "未命中返回 404": unmatched_ok,
        "回放检出全部变化": detected == 5,
        "回放无误报": false_positives == 0,
        "端到端录放": demo["exchanges"] == 4 and demo_hits == 4,
    }

    print("tapmock · eval")
    print("=" * 58)
    print(f"脱敏泄漏          {leaks} 处（{TOTAL} 条请求）")
    print(f"Mock 命中         {hits}/{TOTAL}")
    print(f"未命中 404        {'✓' if unmatched_ok else '✗'}")
    print(f"回放检出          {detected}/5 变化，误报 {false_positives}")
    print(f"端到端录放        {demo['exchanges']} 条录制 / {demo_hits} 条回放")
    print("-" * 58)
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")

    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(
            {
                "leaks": leaks,
                "mock_hits": hits,
                "total": TOTAL,
                "replay_detected": detected,
                "replay_false_positives": false_positives,
                "demo": {"exchanges": demo["exchanges"], "hits": demo_hits},
                "checks": checks,
                "passed": all(checks.values()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n结果：{RESULTS_DIR / 'latest.json'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
