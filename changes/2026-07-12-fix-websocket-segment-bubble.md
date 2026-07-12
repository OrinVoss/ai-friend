# 2026-07-12 修复 WebSocket segment 气泡分裂 (Fix #297)

## 修改原因

后端 `_send_segments` 分段推送消息时，前端每次收到 `segment` 都创建新气泡，
导致一条回复显示成多个独立气泡。

## 修改文件

- `web/static/app.js` — `case 'segment':` 处理改为先查找最后一个 assistant 气泡，
  存在则追加文本，不存在才创建新气泡。
