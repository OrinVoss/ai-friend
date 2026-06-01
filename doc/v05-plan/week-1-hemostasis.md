# 第1周：止血（P0 + 安全关键，15 个）

**目标**：消除所有已知的数据丢失、运行时崩溃、可被利用的安全漏洞。

---

## Day 1-2：P0 收尾（6 个）

### #202 — repo.session_id 全局可变竞态

- **文件**：`storage/repository.py:17`、`web/session.py:34`
- **当前行为**：所有 WebAgent 共享一个 Repository 实例。`repo.session_id = session_id` 直接修改全局属性。两用户并发时，A 的 session_id 可能被 B 覆盖，A 的数据写入 B 的会话或查询到 B 的数据。
- **崩溃条件**：2+ WebSocket 同时连接 → `get_or_create` → 各自设置 `repo.session_id`
- **修复**：用 `threading.local()` 存储每线程 session_id，Repository 方法读 `self._local.session_id`
- **影响文件**：`repository.py`（17 行方法签名不变，仅改属性读取）、`session.py`（设置方式改）
- **副作用**：无。方法签名不变，所有调用方不受影响。
- **验证**：`test_repository.py` + 新增多 session 并发测试
- **GitHub**：#202

### #203 — Agent 1 持有完整 registry 可绕过 Agent 2

- **文件**：`core/inner_drive.py:50`、`core/message_handler.py:31`
- **当前行为**：`InnerDriveAgent._full_registry` 包含所有外部工具。Agent 1 的 ReAct 循环调用 `parse_tool_calls(resp)` 和 `execute_tool_calls(self._full_registry, calls)`。正常情况下 Agent 1 prompt 只列内部工具，LLM 不会输出外部工具。但如果 LLM 输出了 `web_fetch`，dispatcher 会直接执行，完全绕过 Agent 2 的重试机制。
- **崩溃条件**：LLM 幻觉输出外部工具调用（罕见但可能）
- **修复**：在 `_ensure_inner_drive()` 中创建隔离 registry（仅 recall/remember），不传 `_full_registry`
- **影响文件**：`message_handler.py`（改 `_ensure_inner_drive`）
- **副作用**：无。Agent 1 只用内部工具是设计意图。
- **验证**：现有 `test_inner_drive.py` 全部通过 + 新增 registry 隔离测试
- **GitHub**：#203

### #204 — ToolAttemptTracker round_number 永不递增

- **文件**：`core/tool_agent.py:48-67`、`core/message_handler.py:91-135`
- **当前行为**：`ToolAttemptTracker()` 在 while 循环内创建（`message_handler.py:91`），每轮新建实例，`round_number` 始终为 0。`can_start_new_round` 检查 `round_number < max_rounds` 永远为 True，理论上允许无限重试。实际被 `MAX_AGENT2_ROUNDS=3` 的 while 条件限制，所以没有实际后果。
- **崩溃条件**：无明显崩溃，但代码逻辑错误
- **修复**：在 while 循环外创建 tracker，每轮 `tracker.round_number = round_num`
- **影响文件**：`message_handler.py:91`（移动 tracker 创建位置）
- **副作用**：无。行为不变（while 条件已有限制），只是代码逻辑正确了。
- **验证**：现有测试全部通过
- **GitHub**：#204

### #205 — Agent 2 多轮结果被丢弃

- **文件**：`core/message_handler.py:100-156`
- **当前行为**：`_run_agent3(user_input, drive_result, tool_result)` 传入的是**最后一轮**的 `tool_result`。`_run_agent3` 内部 `tool_records = self._tool_agent.format_for_phase2(tool_result)` 只包含最后一轮结果。如果第一轮搜索成功但第二轮获取失败，Agent 3 看不到搜索成功的数据。
- **崩溃条件**：多轮 Agent 2 调用，第一轮有结果但后一轮覆盖
- **修复**：`_run_agent3` 改为接收 `all_tool_records` 字符串（已在 `handle_message` 中累积），不再依赖 `tool_result` 参数
- **影响文件**：`message_handler.py`（`_run_agent3` 签名 + `handle_message` 传参）
- **副作用**：prompt 增大（多轮结果累积）。加 3000 字符截断保护。
- **验证**：现有测试 + 新增多轮结果测试
- **GitHub**：#205

### #206 — Personality.save() 多线程竞态

- **文件**：`core/personality.py:125-135`
- **当前行为**：`save()` 写入固定临时文件 `personality.json.tmp`，然后 `os.replace()` 到正式文件。多个线程同时写同一个 `.tmp` → 数据交错损坏。
- **崩溃条件**：Web 模式多 session 同时调用 save（proactive 回复 + 用户消息同时触发）
- **修复**：唯一临时文件名：`f"{path}.tmp.{os.getpid()}.{time.time_ns()}"`
- **影响文件**：`personality.py:128`（仅改 tmp 文件名生成）
- **副作用**：可能残留 `.tmp` 文件（上次崩溃留下的）。加启动时清理。
- **验证**：现有测试通过
- **GitHub**：#206

### #207 — FactChecker.resolve 同步调 async — 静默无操作

- **文件**：`memory/fact_checker.py:88-104`、`memory/consolidation.py:189-193`
- **当前行为**：`resolve()` 是 sync 方法，调用 `repo.deactivate_fact()` 和 `repo.update_fact_confidence()` 而不 `await`。返回 coroutine 对象，实际 SQL 从未执行。矛盾检测完全无效。
- **崩溃条件**：不会崩溃。矛盾检测静默失效，虚假记忆从未被修正。
- **修复**：`resolve()` 改为接收 `ltm`（LongTermMemory）而非 `repo`，调用 sync 包装器 `ltm.deactivate_fact()` 和 `ltm.update_fact_confidence()`
- **影响文件**：`fact_checker.py:88`（resolve 参数改 ltm）、`consolidation.py:190`（传入 ltm 而非 ltm.repo）
- **副作用**：无。sync 包装器走现有的 `run_async` 路径。
- **验证**：`test_fact_checker.py` 更新 mock + 新增真实 DB 测试
- **GitHub**：#207

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
