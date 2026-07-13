# 刷新浏览器后对话轮次不再重置

## 问题
Web 页面刷新后，`turn_count` 会重置为 0。虽然历史消息会从数据库恢复，但右上角的轮次数和 consolidation 触发逻辑都从零开始，导致关系指标更新节奏也被打乱。

## 改动
- `storage/repository.py`
  - 新增 `get_max_turn_number(session_id)`，返回某 session 已持久化的最大 `turn_number`。
- `web/session.py`
  - `WebAgent.__init__` 在创建内部 `Agent` 后，调用 `get_max_turn_number()` 恢复 `self.agent.turn_count`。

## 效果
刷新浏览器重新连接 WebSocket 后，轮次数从数据库中恢复，继续累加而不是从 0 开始。

## 验证
- `python -m py_compile web/session.py storage/repository.py` 通过。
- 重启服务后刷新页面，`/api/status` 返回的 `turn` 与数据库中 `conversation_turns` 的最大 `turn_number` 一致。
