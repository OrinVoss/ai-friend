# 修复 issue #349：同 session 并发消息无串行化

## 修改的文件
- `web/session.py`
- `web/server.py`

## 修改原因
REST `/api/chat` 与 WS message 路径都把 `agent.process_message` 丢进默认线程池；同一 session 的两条快速消息（或 WS+REST 同时）并发执行，共享的 short_term、turn_count、情绪等可变状态会被并发写坏。

## 修改内容
- `SessionManager.session_lock(session_id)`：每 session 一把 asyncio.Lock（懒创建，受 `_lock` 保护）。
- REST 与 WS 两条消息路径都在锁内执行 `process_message`。
- 验证：`pytest -k "web or server or session"` 89 passed, 2 skipped。
