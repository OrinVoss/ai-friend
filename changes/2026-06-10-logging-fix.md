# 2026-06-10 — 修复 uvicorn 启动后日志不落盘

## 修改文件

- **core/logging_setup.py** — 重新挂载日志前清空旧 handlers，防止重复
- **web/server.py** — lifespan 启动重调 setup_logging()，确保 uvicorn 不顶掉 FileHandler

## 原因

uvicorn 启动时修改 root logger handlers，`setup_logging()` 在 web_main.py 中添加的 FileHandler 被移除。日志只写到 stderr（uvicorn 终端），不入文件。

## 效果

日志正常写入 `logs/YYYY-MM-DD.log`，对话/工具/情绪记录落盘。
