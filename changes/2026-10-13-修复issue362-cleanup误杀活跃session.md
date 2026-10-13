# 修复 issue #362：cleanup_old 误杀活跃连接 session

## 修改的文件
- `web/session.py`

## 修改原因
`cleanup_old` 只按 `last_activity` 判 TTL；proactive driver 在跑、用户长时间未发消息但仍挂着 WebSocket 的 session 会被驱逐并 cancel driver。

## 修改内容
- TTL 驱逐与 max_sessions 淘汰均跳过 `_active_ws` 中仍有活跃连接的 session。
- 验证：`pytest -k "session or web"` 77 passed。
