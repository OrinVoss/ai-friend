# 2026-07-12 Linter 更新 + 前端改进

## 修改原因

Linter 自动优化了部分代码，前端 WebSocket segment 追加增加 markdown 渲染，
main.py/web_main.py 增加 `_kill_existing_llama` 函数确保嵌入服务器重启前
清理旧进程。

## 修改文件

- `web/static/app.js` — segment 消息追加时保留 raw text 并用 `marked.parse`
  渲染 markdown；REST 回退分支清理 typo
- `web/static/index.html` — CSP meta + referrer meta 标签
- `web/static/style.css` — 样式补充
- `main.py` — 新增 `_kill_existing_llama()` 避免嵌入服务器端口冲突
- `web_main.py` — 同上
