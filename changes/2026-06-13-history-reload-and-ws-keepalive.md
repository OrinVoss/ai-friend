# 修复 WebSocket 掉线 + 刷新后对话历史恢复

## 修改文件

### web/static/app.js
- **init_ok 后加载历史**：新增 `loadHistory()` 调用 `/api/chat/history`，刷新页面后自动恢复对话记录
- **WebSocket 保活**：每 25 秒发送 ping 防止代理超时断开
- **断线重连**：从 3 秒缩短到 2 秒

### web/server.py
- **新增 `/api/chat/history` 端点**：根据 `session_id` 返回 `short_term` 中的历史对话

### storage/repository.py
- **R-020**：`get_recent_turns` 新增 `WHERE session_id = ?` 过滤，不同 session 的对话不再混合返回
