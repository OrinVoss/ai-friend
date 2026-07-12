# 同步 README.md 与近期修复 (#58/#54/#45/#43/#23/#28/#24)

## 修改文件

- `README.md`

## 修改原因

`9296694` 修复了 7 个 issue 后，`1d75b59` 已同步 11 份 doc/ 文档，`51fd45b` 已同步 `CLAUDE.md`，但项目根目录的 `README.md` 仍为旧描述。README 是用户和开发者的首要入口，需要与当前架构、配置、安全能力保持一致。

## 修改内容摘要

- **项目介绍**：将“基于 DeepSeek API”更新为“基于 OpenAI 兼容 API（默认 DeepSeek / KimiProvider）”。
- **特性补充**：
  - Provider 抽象层：`LLMProvider(ABC)` + `KimiProvider`。
  - REST API 类型安全：Pydantic 校验。
  - Web 安全加固：CORS 可配置、滑动窗口速率限制、CSP/X-Frame-Options 安全头。
  - 对话示例可配置：`config.json` 的 `conversation_examples`。
  - 共享 embedding 启动：`core/embedding_server.py` 消除 CLI/Web 启动代码重复。
- **配置表**：修正 `embedding_dim` 默认值为 `1024`；新增 `conversation_examples`、`allowed_origins` 字段说明。
- **CLAUDE.md 规则摘要**：补充 README 同步要求、Provider ABC、WebAgent 封装、Pydantic 模型、CSS 变量等规范。
- **项目结构**：
  - 新增 `core/embedding_server.py`、`web/schemas.py`、`web/rate_limit.py`。
  - 更新 `core/provider.py`、`web/server.py`、`web/session.py`、`web/static/` 描述。
  - doc 列表新增 `open-issues-修复报告-2026-07-12.md`。
  - 测试数量更新为 `312 collected`。
