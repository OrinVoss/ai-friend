# 同步 11 份文档与近期修复 (#58/#54/#45/#43/#23/#28/#24)

## 修改文件

- `doc/api.md`
- `doc/architecture.md`
- `doc/config-reference.md`
- `doc/deployment.md`
- `doc/message-flow.md`
- `doc/milestones-and-issues.md`
- `doc/open-issues-修复报告-2026-07-12.md`
- `doc/personality-guide.md`
- `doc/prompt-reference.md`
- `doc/technical.md`
- `doc/testing-guide.md`
- `doc/tool-development.md`

## 修改原因

`9296694` 集中修复了 7 个 issue（#58/#54/#45/#43/#23/#28/#24），涉及 embedding 启动复用、CSS 变量化、WebAgent 封装、Pydantic 校验、Provider 抽象基类、对话示例可配置化以及 CORS/速率限制/CSP 安全细化。doc/ 下的核心文档需要同步反映这些代码与配置变更，避免文档与实现脱节。

## 修改内容摘要

- `doc/architecture.md`：更新模块说明，补充 `core/embedding_server.py`、`LLMProvider(ABC)`、`web/schemas.py`、`web/rate_limit.py`、`WebAgent`、CSS 变量等。
- `doc/api.md`：补充 `/api/chat`、`/api/status`、`/api/chat/history` 的 Pydantic 请求/响应模型、校验示例、错误码与 WebSocket 安全头说明。
- `doc/config-reference.md`：新增 `conversation_examples` 与 `allowed_origins` 配置项说明。
- `doc/deployment.md`：补充 CORS、CSP、速率限制在生产环境的配置建议。
- `doc/message-flow.md`：补充 Web 消息经 `WebAgent` 封装后的调用链路。
- `doc/milestones-and-issues.md`：更新 issue 状态，将 #58/#54/#45/#43/#23/#28/#24 标记为已关闭。
- `doc/open-issues-修复报告-2026-07-12.md`：新增这 7 个 issue 的关闭记录与验证说明。
- `doc/personality-guide.md`：说明对话示例可配置化对人格风格的影响。
- `doc/prompt-reference.md`：更新系统提示词中对话示例的渲染逻辑说明。
- `doc/technical.md`：细化 Provider ABC、WebAgent 封装、Pydantic 校验、限流安全等技术实现。
- `doc/testing-guide.md`：补充新增测试（Provider ABC、RateLimit、WebAgent、ConversationExamples）的说明。
- `doc/tool-development.md`：更新工具与 WebAgent 交互的注意事项。
