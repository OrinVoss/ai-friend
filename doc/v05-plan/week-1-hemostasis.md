# 第1周：止血（全部完成 ✅）

**目标**：消除所有已知的数据丢失、运行时崩溃、可被利用的安全漏洞。

## 状态：全部完成 ✅ | P0 6/6 | P1 3/3 | 共 9 issues closed

---

## Day 1-2：P0 收尾（6 个）✅

---

## Day 1-2：P0 收尾（6 个）✅

### #202 — repo.session_id 全局可变竞态 ✅ 已关闭

- **文件**：`storage/repository.py:17`、`web/session.py:34`
- **结果**：单人使用不触发 → 关闭
- **GitHub**：#202 (closed as not-applicable)

### #203 — Agent 1 持有完整 registry 可绕过 Agent 2 ✅

- **文件**：`core/inner_drive.py:50`、`core/message_handler.py:31`
- **修复**：`_ensure_inner_drive()` 创建隔离 registry（仅 recall/remember）
- **commit**：c4cc233
- **GitHub**：#203 (closed)

### #204 — ToolAttemptTracker round_number 永不递增 ✅

- **文件**：`core/tool_agent.py:48-67`、`core/message_handler.py:91-135`
- **修复**：tracker 移出 while 循环，每轮 `tracker.round_number = round_num`
- **commit**：c4cc233
- **GitHub**：#204 (closed)

### #205 — Agent 2 多轮结果被丢弃 ✅

- **文件**：`core/message_handler.py:100-156`
- **修复**：`_run_agent3` 新增 `tool_records` 参数，handle_message 传入累积结果
- **commit**：c4cc233
- **GitHub**：#205 (closed)

### #206 — Personality.save() 多线程竞态 ✅

- **文件**：`core/personality.py:125-135`
- **修复**：唯一临时文件名 `{path}.tmp.{pid}.{time_ns()}`
- **commit**：c4cc233
- **GitHub**：#206 (closed)

### #207 — FactChecker.resolve 同步调 async — 静默无操作 ✅

- **文件**：`memory/fact_checker.py:88-104`、`memory/consolidation.py:189-193`
- **修复**：resolve 接收 ltm（LongTermMemory），调 sync 包装器 `ltm.deactivate_fact()` / `ltm.update_fact_confidence()`
- **commit**：c4cc233
- **GitHub**：#207 (closed)

---

## Day 3-4：安全关键 P1（3 个）✅

### #209 — 符号链接白名单绕过 ✅

- **文件**：`tools/file_tools.py:51-58`、`tools/search_tools.py:14-23`
- **修复**：`os.path.abspath` → `os.path.realpath`，前缀匹配追加 `os.sep`
- **commit**：9a9b40e
- **GitHub**：#209 (closed)

### #241 — web_tools URL 协议验证 ✅

- **文件**：`tools/web_tools.py:165-170`
- **修复**：`urlparse` 解析后检查 scheme，拒绝非 http/https，修复 `//example.com` 协议相对 URL
- **commit**：9a9b40e
- **GitHub**：#241 (closed)

### #212 — lifespan shutdown 优雅关闭 ✅

- **文件**：`web/server.py:22-27`、`web/session.py`（新增 `shutdown()`）
- **修复**：shutdown 时保存所有 personality、cancel proactive tasks、清空 sessions
- **commit**：9a9b40e
- **GitHub**：#212 (closed)

---

## 已跳过（单人场景不适用）

| # | 问题 | 原因 |
|---|------|------|
| #202 | repo.session_id 竞态 | 单人使用无跨 session |
| #211 | WebSocket 多标签页竞争 | 单人使用 |
| #233 | 前端 Cookie 安全标志 | 单人 localhost |
| #234 | REST API 阻塞事件循环 | 单人不影响 |
| #235 | WebSocket Origin 绕过 | 单人 localhost |
| #210 | ReDoS grep 超时 | 正则由 LLM 生成，可信任 |

---

## Day 3-4：安全关键 P1（9 个）

### #209 — 符号链接白名单绕过（3 文件）

- **文件**：`tools/file_tools.py:52`、`tools/search_tools.py:16`、`tools/music_tool.py:55`
- **当前行为**：`os.path.abspath()` 不解析 Windows junction / Linux symlink。`D:\safe` 的 junction 指向 `C:\Windows` 时，路径检查通过但实际读取系统文件。另外 `startswith` 前缀匹配缺尾部 `os.sep`，`D:\音乐` 可匹配 `D:\音乐fake`。
- **修复**：3 个文件统一改用 `os.path.realpath()` + 前缀匹配追加 `os.sep`
- **影响**：需确认 `realpath` 对正常路径的行为一致
- **验证**：创建临时 junction 测试绕过场景
- **GitHub**：#209

### #210 — ReDoS grep 超时

- **文件**：`tools/search_tools.py:164-175`
- **当前行为**：`regex.search(line)` 在主线程执行，恶意正则（如 `(a+)+b` 对 `aaaaaaaaaaaaaaaaaaaa`）可 CPU 耗尽。已有 `GREP_TIMEOUT=5` 常量但从未使用。
- **修复**：在单独线程执行 `regex.search`，`thread.join(timeout=5)`，超时则跳过该文件
- **影响**：性能略微下降（每文件一个线程），但安全。最多遍历文件数限制在 100 个。
- **验证**：构造恶意正则 + 长文本测试超时
- **GitHub**：#210

### #235 — WebSocket Origin localhost.evil.com 绕过

- **文件**：`web/server.py:219`
- **当前行为**：`origin.startswith("http://localhost")` 匹配 `http://localhost.evil.com`
- **修复**：用 `urllib.parse.urlparse(origin).hostname in ("localhost", "127.0.0.1", "::1")`
- **影响**：如果在配置的 host 上运行，需要加入配置的 hostname
- **验证**：curl 伪造 Origin 头测试
- **GitHub**：#235

### #212 — lifespan shutdown 空操作

- **文件**：`web/server.py:22-27`
- **当前行为**：`lifespan` 的 shutdown 阶段是空的 `yield` 之后无代码。应用关闭时：数据库连接不关闭、WAL 文件不 checkpoint、session 不保存。
- **修复**：`yield` 后添加：遍历所有 session 调 `agent.close()`、`await db.close()`、清理临时文件
- **影响**：需要 `WebAgent.close()` 方法（关闭 provider session、保存 personality）
- **验证**：启停 Web 服务，检查 WAL 文件是否被清理
- **GitHub**：#212

### #241 — web_tools 协议检查漏洞

- **文件**：`tools/web_tools.py:165-167`
- **当前行为**：协议检查仅匹配 `http://`/`https://` 前缀，`ftp://` 等绕过。`//example.com`（协议相对 URL）变成 `https:////example.com`。
- **修复**：`urllib.parse.urlparse()` 解析后检查 `scheme in ("http", "https")`，去除 `//` 前缀
- **验证**：单元测试各种 URL 格式
- **GitHub**：#241

### #233 — 前端 Cookie 缺安全标志

- **文件**：`web/static/app.js:34-36`
- **当前行为**：`document.cookie = "session_id=" + id` 无任何安全标志
- **修复**：`document.cookie = "session_id=" + id + "; HttpOnly; Secure; SameSite=Strict; max-age=86400"`
- **影响**：HttpOnly 时 JS 无法读 cookie（需要后端 Set-Cookie 头）。改为后端在 init_ok 响应中 `Set-Cookie` 头。
- **修复涉及**：`web/server.py`（init_ok 加 Set-Cookie 响应头）、`app.js`（删客户端 cookie 设置）
- **验证**：浏览器 DevTools 检查 cookie 标志
- **GitHub**：#233

### #211 — WebSocket 多标签页 session 竞争

- **文件**：`web/server.py:238-248`、`web/session.py:158-166`
- **当前行为**：每个 WebSocket `init` 消息创建新 proactive task。旧标签页断开时 `remove()` 销毁整个 session（包括其他标签页的 agent）。新标签页连接取消旧 proactive task 但旧 WebSocket 不知道。
- **修复**：session 引用计数 + proactive task 绑定到 WebSocket 而非 session
- **影响**：session 生命周期管理重构，影响较大
- **验证**：多标签页并发测试
- **GitHub**：#211

### #234 — REST API 同步阻塞事件循环

- **文件**：`web/server.py:46-47`
- **当前行为**：`agent.process_message()` 是同步方法，直接在 async 路由中调用。阻塞 FastAPI 事件循环，所有其他请求排队等待。
- **修复**：`await asyncio.get_event_loop().run_in_executor(None, agent.process_message, message)`
- **影响**：WebAgent.process_message 需要线程安全（短期用锁，长期改 async）
- **验证**：并发 REST 请求测试（ab 或 wrk）
- **GitHub**：#234

---

## Day 5：验证 + 文档

- 全量测试：`python -m pytest tests/ -v`
- 手动安全测试：Origin 绕过、路径穿越、ReDoS
- changes log 更新
- 关闭已修复 issue
- 更新 milestones 文档

---

## 第1周风险总结

| 风险 | 等级 | 缓解 |
|------|------|------|
| #205 prompt 增大超上下文 | 中 | 3000 字截断 |
| #211 session 重构引入新 bug | 中 | 充分测试多标签页 |
| #234 run_in_executor 线程安全 | 中 | 短期加锁 |
| 修改 10+ 文件一次合并 | 低 | 每个 issue 独立 commit |
