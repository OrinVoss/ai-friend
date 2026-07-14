# 修复 #156：睡/醒消息持久化不完整

## 问题

午睡/醒来消息刷新页面后消失，或出现在错误的位置。

`web/server.py` 的 proactive 循环里虽然写了持久化代码：

```python
agent.short_term.add_turn("assistant", msg, metadata={"source": "sleep"})
await agent.ltm.repo.insert_turn(agent.turn_count, "assistant", msg)
```

但存在三个问题：

1. **没有递增 `turn_count`**。`insert_turn` 使用当前 `agent.turn_count`，写完没有 `increment_turn_count()`，后续对话回合可能复用或覆盖同一个 turn ID。
2. **绕过了 `Agent.add_turn()`**。`Agent.add_turn()` 会同时写 `short_term` 和 `ltm`，并记录情绪状态；这里手动拆成两步，短记忆和长记忆写入不在同一事务，且缺少情绪字段。
3. `metadata` 格式不统一。`core/message_handler.py` 中睡前消息使用 `{"sleep": True}`，而这里用 `{"source": "sleep"}`，没有代码读取 `"source"` 字段。

## 改动

### 1. `web/session.py`

给 `WebAgent` 新增两个转发方法，让 `web/server.py` 可以通过 `WebAgent` 调用 `Agent` 的 turn 管理：

- `add_turn(role, content, metadata=None)` → `self.agent.add_turn(...)`
- `increment_turn_count()` → `self.agent.increment_turn_count()`

### 2. `web/server.py`

把原来的手动拆写改成：

```python
agent.add_turn("assistant", msg, metadata={"sleep": True})
agent.increment_turn_count()
```

与 `core/message_handler.py` 中睡前回复的处理方式保持一致。

### 3. `tests/test_web_agent.py`

新增两个单元测试：

- `test_add_turn_forwards_to_agent`：验证 `WebAgent.add_turn` 正确转发给底层 `Agent.add_turn`。
- `test_increment_turn_count_forwards_to_agent`：验证 `WebAgent.increment_turn_count` 正确转发。

## 验证

```bash
python -m pytest tests/test_web_agent.py tests/test_message_handler.py -v
# 34 passed

python -m pytest tests --ignore=tests/real_api -q
# 391 passed, 2 skipped
```

## 相关文件

- `web/session.py`
- `web/server.py`
- `tests/test_web_agent.py`
- `changes/2026-07-14-fix-156-sleep-message-persistence.md`
