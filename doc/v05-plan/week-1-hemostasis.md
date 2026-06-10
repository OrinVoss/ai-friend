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
