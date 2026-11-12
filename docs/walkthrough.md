# tapmock · 一步一步使用与讲解

按「录一次 → 脱敏 → 回放 → 对比」的顺序写，照着做就能跑通。

## 0. 五分钟路线

1. 跑 `demo`：自动录制 4 条真实请求，脱敏后 Mock 回放。
2. 打开流量视图，看哪些字段被替换成 `<redacted>`。
3. 用 `record` 录自己的接口。
4. 用 `mock` 给前端用，用 `replay` 做接口回归。
5. 看最后的「面试怎么讲」。

---

## 1. 它解决什么问题

- **后端没就绪**：前端对着录好的 Mock 开发，字段、状态码、header 都是真的。
- **线上问题复现**：把一次真实请求录成 tape，本地反复回放。
- **接口回归**：把 tape 重放到新服务，逐字段指出变化。

tape 是 JSON，可提交、可 review、可脱敏；不是二进制抓包文件。

---

## 2. 环境准备（Windows）

```powershell
cd C:\ClaudeProjects\tapmock
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

依赖 `mitmproxy`（录制）和 `requests`（回放/演示）。`mitmproxy 12` 需要 Python ≥ 3.12。

---

## 3. 跑第一次 demo

```powershell
.\.venv\Scripts\python.exe -m src.tapmock demo
```

这条命令做四件事：

1. 在本地启动一个演示上游 API（登录、商品、订单、个人资料）。
2. 启动 `mitmdump` 反向代理，把请求转发到上游并录制。
3. 发 4 个真实请求：登录、商品列表、订单（带 Authorization）、个人资料。
4. 停止代理，从 tape 启动 Mock，再发一遍请求。

预期输出：

```text
✓ 录制 4 条 → demo\tape.json
✓ 脱敏字段：request.body.password, request.headers.authorization,
  request.headers.cookie, response.body.email, response.body.phone,
  response.body.token, response.headers.set-cookie

Mock 回放：
  ✓ POST  /api/login      HTTP 200  ex-001
  ✓ GET   /api/products   HTTP 200  ex-002
  ✓ GET   /api/orders     HTTP 200  ex-003
  ✓ GET   /api/profile    HTTP 200  ex-004
  ✗ GET   /api/unmatched  HTTP 404  未命中（预期 404）
```

打开 `reports/tape.html`：左边请求、右边响应，脱敏值会高亮。

---

## 4. 录制自己的接口

### 4.1 反向代理（推荐，不用装证书）

```powershell
.\.venv\Scripts\python.exe -m src.tapmock record `
  --target http://127.0.0.1:9000 `
  --port 8081 `
  --out tape.json `
  --view reports\tape.html
```

然后把请求发到 `http://127.0.0.1:8081`：

```powershell
curl http://127.0.0.1:8081/api/products
```

`mitmdump` 会转发到 `http://127.0.0.1:9000`，同时写入 `tape.json`。按 Ctrl+C 结束。

### 4.2 正向代理（浏览器 / 手机）

```powershell
.\.venv\Scripts\python.exe -m src.tapmock record --forward --port 8081 --out tape.json
```

- 浏览器/手机代理设为 `127.0.0.1:8081`。
- 抓 HTTPS 需要访问 <http://mitm.it> 安装 mitmproxy CA 证书。
- 有证书固定（pinning）的 App 抓不到，这是限制，不是 bug。

### 4.3 额外脱敏

```powershell
... record --target http://127.0.0.1:9000 --redact device_id,session_id
```

内置规则覆盖 token / password / secret / cookie / email / phone 等；业务自定义字段用 `--redact` 补。

---

## 5. 用 Mock 给前端联调

```powershell
.\.venv\Scripts\python.exe -m src.tapmock mock --tape tape.json --port 8080 --cors
```

把前端请求指向 `http://127.0.0.1:8080`。

匹配规则：

- `method + path + query` 完全匹配。
- query 参数顺序无关。
- 同一路径录了多次 → 按录制顺序返回；超出次数后复用最后一条。
- 匹配 host 被忽略，tape 可以从测试域名搬到本地端口。

未命中：

```json
{"error": "no matching exchange", "method": "GET", "path": "/api/nope", "query": ""}
```

同时返回 404，并记录在服务的 `unmatched` 列表里。命中时响应头带 `X-Tapmock-Exchange: ex-00x`，方便确认用的是哪条录音。

---

## 6. 回放与差异检查

```powershell
.\.venv\Scripts\python.exe -m src.tapmock replay `
  --tape tape.json `
  --target http://127.0.0.1:9000 `
  --fail-on-diff
```

输出：

```text
✓ ex-001 POST   /api/login
✗ ex-003 GET    /api/orders
    changed      $.orders[0].status: "shipped" → "pending"
```

比较内容：

- HTTP 状态码
- Content-Type
- JSON 逐字段：新增、删除、类型变化、值变化，路径精确到 `$.orders[0].status`
- 非 JSON：文本/二进制内容

录制时被脱敏的 Authorization 不能直接用于真实回放，可以用：

```powershell
--header Authorization="Bearer 真实token"
```

---

## 7. 看 tape

```powershell
.\.venv\Scripts\python.exe -m src.tapmock view --tape tape.json --out reports\tape.html --open
```

单文件 HTML：请求/响应 header、body、耗时、脱敏字段；支持搜索 method / URL / 状态码。

tape 结构（已脱敏）：

```json
{
  "id": "ex-001",
  "request": {
    "method": "POST",
    "url": "http://demo.local/api/login",
    "headers": [["Content-Type", "application/json"]],
    "body": "{\"username\": \"alice\", \"password\": \"<redacted>\"}"
  },
  "response": {
    "status": 200,
    "headers": [["Content-Type", "application/json"]],
    "body": "{\"token\": \"<redacted>\", \"user\": {\"name\": \"alice\"}}"
  },
  "redactions": ["request.body.password", "response.body.token"]
}
```

---

## 8. 代码地图

| 文件 | 职责 |
|---|---|
| `src/tapmock/redact.py` | 头 / query / JSON / form 脱敏 |
| `src/tapmock/tape.py` | tape 读写、匹配索引、按顺序返回 |
| `src/tapmock/addon.py` | mitmproxy `response` 钩子 |
| `src/tapmock/recorder.py` | 启动/停止 mitmdump，注入环境变量 |
| `src/tapmock/mock.py` | Mock HTTP 服务 |
| `src/tapmock/replay.py` | 重放 + JSON 逐字段 diff |
| `src/tapmock/view.py` | 单文件 HTML 视图 |
| `src/tapmock/demo.py` | 上游 API + 端到端录放演示 |
| `src/tapmock/cli.py` | demo / record / mock / replay / view |

一次录制的内部顺序：

```text
mitmdump 收到请求
→ 转发到上游，拿到响应
→ response 钩子：头/query/body 脱敏
→ 编码为 UTF-8 或 base64
→ 追加到 tape 并原子写盘
```

---

## 9. 关键设计，面试可以直接讲

### 9.1 为什么脱敏发生在写盘之前

录完再清洗，原始 token 已经在磁盘/日志里了。response 钩子里先替换再落盘，即使进程被 Ctrl+C、tape 被误提交，也不会留下明文。

### 9.2 为什么保留字段名，只替换值

整段清空会让 Mock 返回的结构失真。JSON 只替换敏感 key 的 value，字段名、数组长度、嵌套结构不动，前端拿到的形状和真实一致。

### 9.3 为什么匹配忽略 host

录制时的 host 可能是 `127.0.0.1:随机端口` 或测试域名，Mock 在另一个端口启动。匹配 host 会让 tape 不可移植；只看 method + path + query 更实用。

### 9.4 为什么回放要逐字段 diff

整段字符串比较只会说「不一样」；逐字段 diff 才能说出 `$.orders[0].status` 从 shipped 变成 pending，直接定位兼容性问题。

---

## 10. 评测与测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe eval\run_eval.py
```

实测：

| 项目 | 结果 |
|---|---|
| 测试 | 16 passed |
| 脱敏泄漏 | 0（20 条请求 × 5 类字段） |
| Mock 命中 | 20/20 |
| 未命中 404 | ✓ |
| 回放检出变化 | 5/5，误报 0 |
| 端到端录放 | 4 条录制 / 4 条回放 |

---

## 11. 常见问题

| 现象 | 处理 |
|---|---|
| `mitmdump` 找不到 | `pip install -r requirements.txt`；确认 `.venv\Scripts\mitmdump.exe` 存在 |
| 端口被占用 | 换 `--port`；录制和 Mock 用不同端口 |
| HTTPS 页面打不开 | 正向代理需要访问 `http://mitm.it` 安装证书 |
| Mock 一直 404 | 检查 method/path/query 是否与录制一致；看 `unmatched` 列表 |
| 回放认证失败 | 录制时 Authorization 已脱敏，用 `--header` 覆盖 |
| 同一路径返回了错误的响应 | 同路径按录制顺序返回；确认请求次数和顺序 |

## 12. 局限

- HTTPS 正向代理需要安装 CA；证书固定（pinning）的客户端录不到。
- Mock 不比较请求 body，同一路径不同 body 靠录制顺序区分。
- 脱敏依赖字段名规则；二进制 body 不扫描。
- 不处理 WebSocket、HTTP/2 多路复用的协议细节，mitmproxy 解码成 HTTP 消息后才进入 tape。
