"""命令行入口。

python -m src.tapmock demo --open
python -m src.tapmock record --target http://127.0.0.1:9000 --port 8081 --out tape.json
python -m src.tapmock mock --tape tape.json --port 8080
python -m src.tapmock replay --tape tape.json --target http://127.0.0.1:9000
python -m src.tapmock view --tape tape.json --out reports/tape.html
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__
from .demo import run_demo
from .mock import running_mock
from .recorder import recorder_process
from .replay import replay
from .tape import load_tape
from .view import write_view

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAPE = ROOT / "demo" / "tape.json"
DEFAULT_REPORT_DIR = ROOT / "reports"


def _setup_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def cmd_demo(args: argparse.Namespace) -> int:
    print("▶ 启动上游服务 → reverse 代理录制 → 脱敏 → Mock 回放")
    summary = run_demo(args.tape, Path(args.report_dir) / "demo.json")
    tape = load_tape(args.tape)
    view = write_view(tape, Path(args.report_dir) / "tape.html")
    print(f"\n✓ 录制 {summary['exchanges']} 条 → {args.tape}")
    print(f"✓ 脱敏字段：{', '.join(summary['redactions']) or '无'}")
    print("\nMock 回放：")
    for call in summary["mock_calls"]:
        marker = "✓" if call["exchange"] else "✗"
        print(
            f"  {marker} {call['method']:<5} {call['path']:<20} "
            f"HTTP {call['status']}  {call['exchange'] or '未命中（预期 404）'}"
        )
    print(f"\n流量视图：{view}")
    if args.open:
        webbrowser.open(view.resolve().as_uri())
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    if not args.target and not args.forward:
        print("✗ 需要 --target（反向代理）或 --forward（正向代理）")
        return 1
    extra = [item for item in args.redact.split(",") if item.strip()]
    try:
        with recorder_process(args.out, port=args.port, target=args.target, extra_redact=extra):
            if args.target:
                print(f"▶ 反向代理录制：http://127.0.0.1:{args.port} → {args.target}")
                print(f"  把请求发到代理地址即可，例如 curl http://127.0.0.1:{args.port}/api/...")
            else:
                print(f"▶ 正向代理录制：127.0.0.1:{args.port}")
                print("  浏览器/手机代理设为该地址；HTTPS 需要访问 http://mitm.it 安装 mitmproxy 证书")
            print("  按 Ctrl+C 结束录制")
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n停止录制")
    except Exception as exc:  # noqa: BLE001 - 启动失败要给可读信息
        print(f"✗ 录制失败：{exc}")
        return 1

    tape = load_tape(args.out)
    print(f"✓ 已录制 {len(tape.exchanges)} 条 → {args.out}")
    if args.view:
        view = write_view(tape, args.view)
        print(f"  视图：{view}")
    return 0


def cmd_mock(args: argparse.Namespace) -> int:
    tape = load_tape(args.tape)
    if not tape.exchanges:
        print("✗ tape 为空")
        return 1
    with running_mock(tape, port=args.port, cors=args.cors) as (server, url):
        print(f"▶ Mock 已启动：{url}（{len(tape.exchanges)} 条记录，Ctrl+C 停止）")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        print(f"\n未命中请求：{len(server.unmatched)}")
        for item in server.unmatched[:10]:
            print(f"  {item['method']} {item['path']}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    tape = load_tape(args.tape)
    overrides = {}
    for item in args.header or []:
        if "=" not in item:
            print(f"✗ --header 格式应为 Name=Value：{item}")
            return 1
        name, value = item.split("=", 1)
        overrides[name.strip()] = value
    results = replay(tape, args.target, timeout=args.timeout, header_overrides=overrides)
    matched = sum(1 for item in results if item.matched)
    for item in results:
        marker = "✓" if item.matched else "✗"
        print(f"{marker} {item.exchange_id} {item.method:<6} {item.path}")
        for issue in item.issues[:6]:
            print(f"    {issue.kind:<12} {issue.path}: {issue.expected} → {issue.actual}")
        if item.error:
            print(f"    error: {item.error}")
    print(f"\n一致 {matched}/{len(results)}")
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [
                    {
                        "exchange_id": item.exchange_id,
                        "method": item.method,
                        "path": item.path,
                        "matched": item.matched,
                        "issues": [issue.__dict__ for issue in item.issues],
                        "error": item.error,
                    }
                    for item in results
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.fail_on_diff and matched != len(results):
        return 1
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    tape = load_tape(args.tape)
    view = write_view(tape, args.out)
    print(f"✓ {len(tape.exchanges)} 条请求 → {view}")
    if args.open:
        webbrowser.open(view.resolve().as_uri())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tapmock",
        description="录一次 HTTP(S) 流量，脱敏后变成可离线回放的 Mock 服务。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="本地完整演示：录制 → 脱敏 → Mock")
    demo.add_argument("--tape", default=str(DEFAULT_TAPE))
    demo.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    demo.add_argument("--open", action="store_true")
    demo.set_defaults(func=cmd_demo)

    record = sub.add_parser("record", help="启动 mitmproxy 录制")
    record.add_argument("--out", default=str(DEFAULT_TAPE))
    record.add_argument("--port", type=int, default=8081)
    record.add_argument("--target", default="", help="反向代理目标，例如 http://127.0.0.1:9000")
    record.add_argument("--forward", action="store_true", help="作为普通正向代理运行")
    record.add_argument("--redact", default="", help="额外脱敏字段，逗号分隔")
    record.add_argument("--view", default="", help="录制结束后生成 HTML 视图")
    record.set_defaults(func=cmd_record)

    mock = sub.add_parser("mock", help="从 tape 启动 Mock 服务")
    mock.add_argument("--tape", default=str(DEFAULT_TAPE))
    mock.add_argument("--port", type=int, default=8080)
    mock.add_argument("--cors", action="store_true")
    mock.set_defaults(func=cmd_mock)

    replay = sub.add_parser("replay", help="把 tape 重放到真实服务并比较差异")
    replay.add_argument("--tape", default=str(DEFAULT_TAPE))
    replay.add_argument("--target", required=True)
    replay.add_argument("--timeout", type=float, default=15.0)
    replay.add_argument("--header", action="append", default=[], help="覆盖请求头 Name=Value")
    replay.add_argument("--json", default="")
    replay.add_argument("--fail-on-diff", action="store_true")
    replay.set_defaults(func=cmd_replay)

    view = sub.add_parser("view", help="把 tape 渲染成 HTML")
    view.add_argument("--tape", default=str(DEFAULT_TAPE))
    view.add_argument("--out", default=str(DEFAULT_REPORT_DIR / "tape.html"))
    view.add_argument("--open", action="store_true")
    view.set_defaults(func=cmd_view)
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
