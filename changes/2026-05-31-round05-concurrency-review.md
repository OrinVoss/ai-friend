# 修改记录：第5轮性能与可扩展性审查（并发处理专项）

## 修改文件

- `doc/round05-concurrency.md`（新增）

## 修改原因

执行第5轮代码审查，聚焦并发处理。审查范围覆盖 Web 端并发模型、SessionManager 锁策略、数据库连接并发访问、Provider 并发安全性、asyncio vs threading 选择、run_in_executor 使用、事件循环嵌套问题、全局状态的并发影响。

## 修改内容摘要

- 审查了 24 个核心文件，发现 3 个高危风险、6 个中危风险、8 个低危风险
- 关键问题：
  1. `storage/repository.py` 和 `memory/long_term.py` 的 `_run_sync()` 每次调用都创建新线程池（高危）
  2. `storage/database.py` 的全局 `asyncio.Lock` 强制所有数据库操作串行化（高危）
  3. `web/session.py` 使用 `threading.Lock` 而非 `asyncio.Lock`（高危）
  4. `core/provider.py` 使用同步 `requests` 和 `time.sleep()` 阻塞线程池（中危）
  5. `core/personality.py` 的 `personality.json` 被多会话并发写入（中危）
  6. `web/server.py` 的 WebSocket 消息处理未限制同一会话并发（中危）
  7. `core/dispatcher.py` 的 `execute_tool_calls()` 使用 `asyncio.run()` 存在嵌套事件循环隐患（中危）
- 输出完整审查报告至 `doc/round05-concurrency.md`，包含文件路径、行号、风险评级、修复建议
