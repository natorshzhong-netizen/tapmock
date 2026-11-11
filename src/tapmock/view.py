"""把 tape 渲染成可读的 HTML：请求、响应、脱敏字段一屏看完。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .models import Exchange, Tape

METHOD_CLASS = {
    "GET": "get",
    "POST": "post",
    "PUT": "put",
    "PATCH": "patch",
    "DELETE": "delete",
}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _redacted(value: str) -> str:
    return _e(value).replace("&lt;redacted&gt;", '<span class="redacted">&lt;redacted&gt;</span>')


def _headers_table(headers: list[list[str]]) -> str:
    if not headers:
        return '<p class="empty">没有请求头</p>'
    rows = "".join(
        f"<tr><th>{_redacted(str(name))}</th><td>{_redacted(str(value))}</td></tr>" for name, value in headers
    )
    return f"<table class='headers'>{rows}</table>"


def _body(raw: bytes, content_type: str) -> str:
    if not raw:
        return '<p class="empty">空 body</p>'
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f'<p class="empty">二进制内容，{len(raw)} 字节</p>'
    if "json" in content_type.lower() or text.lstrip()[:1] in ("{", "["):
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    if len(text) > 20_000:
        text = text[:20_000] + "\n…（已截断）"
    return f'<pre class="body">{_redacted(text)}</pre>'


def _content_type(headers: list[list[str]]) -> str:
    for name, value in headers:
        if str(name).lower() == "content-type":
            return str(value)
    return ""


def _exchange_card(exchange: Exchange) -> str:
    method = exchange.request.method.upper()
    method_class = METHOD_CLASS.get(method, "other")
    status = exchange.response.status
    status_class = "s2" if 200 <= status < 300 else "s4" if 400 <= status < 500 else "s5"
    redactions = "".join(f"<code>{_e(item)}</code>" for item in exchange.redactions) or "无"
    search = f"{method} {exchange.request.url} {status} {exchange.id}".lower()

    return f"""
    <article class="exchange" data-search="{_e(search)}">
      <div class="ex-head">
        <span class="method {method_class}">{_e(method)}</span>
        <span class="path">{_redacted(exchange.request.url)}</span>
        <span class="status {status_class}">{status}</span>
        <span class="ex-id">{_e(exchange.id)}</span>
        <span class="duration">{exchange.duration_ms} ms</span>
      </div>
      <div class="redactions"><span>脱敏</span>{redactions}</div>
      <div class="cols">
        <section>
          <h3>请求</h3>
          {_headers_table(exchange.request.headers)}
          {_body(exchange.request.body_bytes(), _content_type(exchange.request.headers))}
        </section>
        <section>
          <h3>响应</h3>
          {_headers_table(exchange.response.headers)}
          {_body(exchange.response.body_bytes(), _content_type(exchange.response.headers))}
        </section>
      </div>
    </article>
    """


def render_view(tape: Tape, title: str = "tapmock · 流量回放") -> str:
    redactions = sorted({item for exchange in tape.exchanges for item in exchange.redactions})
    cards = "".join(_exchange_card(exchange) for exchange in tape.exchanges)
    empty = '<p class="empty">tape 里还没有请求。</p>' if not tape.exchanges else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_e(title)}</title>
<style>
:root {{
  color-scheme: light;
  --page: #f7f8fa; --surface: #fff; --ink: #0f172a; --ink-2: #475569;
  --muted: #94a3b8; --line: #e2e8f0; --accent: #2a78d6; --accent-soft: #eaf2fd;
  --good: #0ca30c; --good-soft: #eaf7ea; --warn: #fab219; --warn-soft: #fff6df;
  --bad: #d03b3b; --bad-soft: #fdecec; --violet: #6250d6; --violet-soft: #f0edfd;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7;
    --muted: #898781; --line: #2c2c2a; --accent: #3987e5; --accent-soft: #17273a;
    --good: #0ca30c; --good-soft: #142614; --warn-soft: #2b2110;
    --bad: #e66767; --bad-soft: #2a1515; --violet: #9085e9; --violet-soft: #231f3a;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 14px; line-height: 1.6; -webkit-font-smoothing: antialiased; }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 30px 24px 56px; }}
header.top {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 24px; }}
.brand strong {{ font-size: 18px; letter-spacing: -0.02em; }}
.brand span {{ margin-left: 10px; color: var(--muted); font-size: 12px; }}
.meta {{ color: var(--muted); font-size: 12px; text-align: right; }}
h1 {{ margin: 0 0 6px; font-size: 32px; letter-spacing: -0.03em; }}
.sub {{ margin: 0; color: var(--ink-2); }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 22px 0; }}
.stat {{ padding: 14px 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }}
.stat p {{ margin: 0; color: var(--muted); font-size: 11.5px; }}
.stat strong {{ display: block; margin-top: 3px; font-size: 23px; letter-spacing: -0.02em; }}
.toolbar {{ display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }}
input[type=search] {{ flex: 1; padding: 9px 12px; border: 1px solid var(--line); border-radius: 9px;
  background: var(--surface); color: var(--ink); font: inherit; font-size: 13px; }}
.exchange {{ margin-bottom: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }}
.exchange[hidden] {{ display: none; }}
.ex-head {{ display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }}
.method {{ padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 800; letter-spacing: 0.04em; }}
.method.get {{ background: var(--accent-soft); color: var(--accent); }}
.method.post {{ background: var(--good-soft); color: var(--good); }}
.method.put {{ background: var(--warn-soft); color: var(--ink); }}
.method.patch {{ background: var(--violet-soft); color: var(--violet); }}
.method.delete {{ background: var(--bad-soft); color: var(--bad); }}
.path {{ flex: 1; min-width: 200px; font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 12px; word-break: break-all; }}
.status {{ padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }}
.status.s2 {{ background: var(--good-soft); color: var(--good); }}
.status.s4 {{ background: var(--warn-soft); color: var(--ink); }}
.status.s5 {{ background: var(--bad-soft); color: var(--bad); }}
.ex-id {{ color: var(--muted); font-size: 11px; }}
.duration {{ color: var(--muted); font-size: 11px; }}
.redactions {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 8px 16px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 11px; }}
.redactions code {{ padding: 1px 6px; border-radius: 5px; background: var(--warn-soft); color: var(--ink); font-size: 10.5px; }}
.cols {{ display: grid; grid-template-columns: 1fr 1fr; }}
.cols section {{ padding: 14px 16px; min-width: 0; }}
.cols section + section {{ border-left: 1px solid var(--line); }}
h3 {{ margin: 0 0 8px; font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }}
table.headers {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 10px; }}
table.headers th {{ width: 34%; padding: 4px 6px; color: var(--muted); text-align: left; font-weight: 500; vertical-align: top; }}
table.headers td {{ padding: 4px 6px; color: var(--ink-2); word-break: break-all; }}
pre.body {{ margin: 0; padding: 10px 12px; max-height: 320px; overflow: auto; border-radius: 8px;
  background: var(--page); color: var(--ink-2); font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  font-size: 11px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }}
.redacted {{ padding: 0 4px; border-radius: 4px; background: var(--warn-soft); color: var(--ink); }}
.empty {{ margin: 4px 0; color: var(--muted); font-size: 12px; }}
footer {{ margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11.5px; }}
@media (max-width: 820px) {{ .cols {{ grid-template-columns: 1fr; }} .cols section + section {{ border-left: 0; border-top: 1px solid var(--line); }} .stats {{ grid-template-columns: 1fr 1fr; }} .meta {{ display: none; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand"><strong>tapmock</strong><span>流量回放</span></div>
    <div class="meta">{_e(tape.source or "未标注来源")}<br />{_e(tape.created_at)}</div>
  </header>

  <h1>{len(tape.exchanges)} 条请求被录制</h1>
  <p class="sub">敏感字段已在写盘前替换为 &lt;redacted&gt;；Mock 按 method + path + query 回放。</p>

  <section class="stats">
    <div class="stat"><p>请求</p><strong>{len(tape.exchanges)}</strong></div>
    <div class="stat"><p>脱敏字段</p><strong>{len(redactions)}</strong></div>
    <div class="stat"><p>4xx / 5xx</p><strong>{sum(1 for item in tape.exchanges if item.response.status >= 400)}</strong></div>
    <div class="stat"><p>平均耗时</p><strong>{(sum(item.duration_ms for item in tape.exchanges) // max(1, len(tape.exchanges)))} ms</strong></div>
  </section>

  <div class="toolbar">
    <input id="search" type="search" placeholder="搜索 method / URL / 状态码 / exchange id" aria-label="搜索请求" />
  </div>

  <div id="list">
    {cards}
    {empty}
  </div>

  <footer>由 tapmock 生成 · 单文件，可直接归档或发给同事</footer>
</div>
<script>
(function () {{
  var search = document.getElementById('search');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.exchange'));
  if (!search) return;
  search.addEventListener('input', function () {{
    var q = search.value.trim().toLowerCase();
    cards.forEach(function (card) {{
      card.hidden = q && (card.dataset.search || '').indexOf(q) === -1;
    }});
  }});
}})();
</script>
</body>
</html>
"""


def write_view(tape: Tape, path: str | Path, title: str | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_view(tape, title or "tapmock · 流量回放"), encoding="utf-8")
    return target
