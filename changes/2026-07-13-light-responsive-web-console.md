# 2026-07-13 浅色响应式 Web 控制台

## 变更摘要
将 `web/static/` 下的深色聊天首页重写为浅色、响应式的 Web 控制台，并接入全部后端接口（聊天、状态、历史、日志）。

## 后端变更
- `web/server.py`
  - 新增 `GET /api/logs` SSE 接口，实时推送当天日志文件最后 100 行并持续 tail 新日志。
  - 导入 `StreamingResponse`。

## 前端变更
- `web/static/index.html`
  - 重写为浅色三栏布局：左侧状态面板、中间聊天区、右侧日志面板。
  - 移动端底部 Tab 切换「聊天 / 状态 / 日志」。
  - 保留原有 DOM 契约（`#chat-messages`、 `#input`、 `#send-btn` 等）。
- `web/static/style.css`
  - 全新浅色主题变量（纯白/浅灰背景 + 蓝色强调色）。
  - 响应式断点：桌面三栏、平板侧滑面板、手机单栏 + 底部 Tab。
  - 保留消息气泡 Markdown 样式。
- `web/static/app.js`
  - 接入 `WS /ws`、`POST /api/chat`、`GET /api/status`、`GET /api/chat/history`。
  - 新增 `EventSource('/api/logs')` 实时日志渲染。
  - 实现状态面板、日志面板、移动端 Tab 切换交互。

## 备份
旧页面备份存放于 `web/backups/`，避免通过 `/static` 直接暴露：
- `web/backups/index.html.v1.bak`
- `web/backups/style.css.v1.bak`
- `web/backups/app.js.v1.bak`

## 验证
- `python -m py_compile web/server.py` 通过（仅预存在 SyntaxWarning）。
- `python -m pytest tests/test_web_agent.py tests/test_message_handler.py -q`：23 passed。

## 相关文档
- `doc/api.md` 已更新 `/api/logs` 接口说明。

## 回滚方式
如需恢复旧页面：
```bash
cp web/backups/index.html.v1.bak web/static/index.html
cp web/backups/style.css.v1.bak web/static/style.css
cp web/backups/app.js.v1.bak web/static/app.js
```
并删除 `web/server.py` 中的 `/api/logs` 端点。
