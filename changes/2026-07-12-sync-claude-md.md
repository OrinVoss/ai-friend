# 同步 CLAUDE.md 与近期架构/安全修复 (#58/#54/#45/#43/#23/#28/#24)

## 修改文件

- `CLAUDE.md`

## 修改原因

`9296694` 修复了 7 个 issue 后，`1d75b59` 已同步 11 份 doc/ 文档，但项目的根目录规则文件 `CLAUDE.md` 仍未更新。`CLAUDE.md` 是开发者的核心指引，其中的架构概要、文档清单与代码规范必须与当前实现保持一致。

## 修改内容摘要

- **架构概要**：
  - 新增 `core/embedding_server.py`（CLI/Web 共享 embedding 启动）。
  - 将 `core/provider.py` 从“DeepSeek API 客户端”更新为 `LLMProvider(ABC)` 抽象基类 + `DeepSeekProvider` 实现。
  - 新增 `web/schemas.py`（Pydantic 请求/响应模型）。
  - 新增 `web/rate_limit.py`（内存滑动窗口限流中间件）。
  - 更新 `web/server.py` 描述，加入 Pydantic 校验、CORS、速率限制、CSP。
  - 更新 `web/session.py` 描述，加入 `WebAgent` 对 `Agent` 私有属性的封装。
  - 新增 `web/static/style.css` CSS 变量说明。

- **文档规范**：
  - 将 `CLAUDE.md` 纳入“代码变更时必须同步更新”的文档清单。
  - 文档总数从 12 更新为 13，新增 `doc/open-issues-修复报告-2026-07-12.md`。

- **代码规范**：
  - Provider 必须继承 `LLMProvider(ABC)`，通过抽象接口注入 Agent。
  - Web 层通过 `WebAgent` 公共接口与 Agent 交互，禁止直接访问 `agent._xxx`。
  - REST API 入参/返回使用 `web/schemas.py` 中的 Pydantic 模型。
  - CSS 颜色统一使用 CSS 变量，禁止硬编码色值。
  - CORS 来源通过 `config.allowed_origins` 扩展；速率限制/CSP 安全头由 `web/server.py` 统一添加。
