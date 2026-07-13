# 2026-07-13 修复午睡消息持久化的残留问题

## 修改原因

`changes/2026-07-13-fix-sleep-message-persistence.md` 中描述的修复未完全落地：

1. `web/session.py` 的 `WebAgent.check_rate_limit` 调用了不存在的 `Agent._check_rate_limit`，
   生产环境会触发 `AttributeError`，导致主动行为频率限制失效。
2. `WebAgent.record_rate_limit` 直接访问 `self.agent._proactive.record_rate_limit`，
   绕过了 `Agent` 的公共转发方法，违反 CLAUDE.md 中“禁止直接访问 `agent._xxx`”的规范。
3. `web/server.py` 处理用户消息时仍使用脏属性 `agent.last_activity`，
   与修改记录中“统一为 `last_activity_time`”的目标不一致。
4. 睡眠/醒来消息写入短期记忆时携带 `metadata={"add_to_history": False}`，
   该 metadata 对 `ConversationBuffer.add_turn` 无实际作用，且语义矛盾
   （此次修改正是为了让睡眠消息进入历史记录）。

## 修改文件

- `web/session.py`
  - `check_rate_limit` 改为调用 `self.agent.check_rate_limit(action)`
  - `record_rate_limit` 改为调用 `self.agent.record_rate_limit(action)`
- `web/server.py`
  - 用户消息处理分支：`agent.last_activity = time.time()` → `agent.last_activity_time = time.time()`
  - 睡眠/醒来消息持久化：`metadata={"add_to_history": False}` → `metadata={"source": "sleep"}`
- `tests/test_web_agent.py`
  - `test_check_rate_limit` mock 目标从 `_check_rate_limit` 改为 `check_rate_limit`
  - `test_record_rate_limit` mock 目标从 `_proactive.record_rate_limit` 改为 `record_rate_limit`

## 验证

- `python -m py_compile web/server.py web/session.py tests/test_web_agent.py` 通过
- `python -m pytest tests/test_web_agent.py tests/test_agent_proactive.py tests/test_message_handler.py -q` 通过（29 passed）
- 全量测试 `python -m pytest tests/ -q`：320 passed, 10 skipped
