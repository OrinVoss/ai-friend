# 同步 13 份核心文档到当前代码状态

## 范围

对项目主文档进行一次全面同步，共 13 份：

- `doc/architecture.md`
- `doc/known-issues.md`
- `doc/config-reference.md`
- `doc/systematic-solution.md`
- `doc/startup-flow.md`
- `doc/api.md`
- `doc/personality-guide.md`
- `doc/prompt-reference.md`
- `doc/technical.md`
- `doc/message-flow.md`
- `doc/deployment.md`
- `doc/testing-guide.md`
- `doc/tool-development.md`

全部为文档改动，无代码变更。

## 同步基准

1. **记忆系统 Layer 1 一期**：SQLite 9 表（新增 observations / facts_v2）、Observation / FactV2 模型、memory/lifecycle.py、MemoryConsolidator 双写、`use_observation_fact` 开关（默认 false）。
2. **Prompt 分层缓存 #160**：core/prompt_cache.py、build_system_prompt 静态/慢变/动态块拆分、`context_summary` 复用、三个新配置项（prompt_cache_ttl_seconds / agent1_short_input_threshold / conversation_examples_max_turns）。
3. **2026-07-16 修复落地**：语义向量 1024 维自适应解码；get_similar_facts / deactivate_fact 加 session_id 过滤/校验。
4. **模块现状**：core/ 16 模块（新增 monitor.py、prompt_cache.py）、memory/ 7 模块（新增 lifecycle.py）。
5. **测试现状**：410 用例 / 30 个测试文件（408 passed + 2 skipped）。
6. **已删除文档清理**：移除所有对已删文件（milestones-and-issues.md、v05-plan/、code-review-report、db-report.html、incident-dispatcher、open-issues-修复报告）的引用。

## 各文档改动摘要

| 文档 | 主要更新 |
|---|---|
| `architecture.md` | 模块树（core 16 / memory 7）、9 表、记忆生命周期、新增「模块依赖」分层图、删除已删文档链接 |
| `known-issues.md` | 新增 3 条发现（user_facts 唯一约束缺 session_id、按 id 写方法无 session 校验、experiences embedding 死路径）；删除对已删 incident-dispatcher 的引用 |
| `config-reference.md` | 补全新字段（use_observation_fact、max_tool_iterations、monitor_enabled、prompt cache 三项），修正 max_tokens 情绪映射说明，修正 personality.json / 示例 JSON |
| `systematic-solution.md` | 同步 refactor/ 文档链接与进度、补 Layer 0 的 session 隔离例外说明、验收标准更新到 408 passed |
| `startup-flow.md` | 同步 embedding server 自动启动、schema v2/9 表、lifecycle 装配点、端点清单、惰性创建 Agent、中间件顺序 |
| `api.md` | 补齐监控端点 /monitor、/api/monitor、/api/monitor/clear；WS 重连退避、init 语义、分段推送现状（单段）、主动消息入历史、连接数限制 |
| `personality-guide.md` | 角色 JSON 无顶层 id、emotional_state 字段对照代码修正、conversation_examples 仅前 3 轮、first_run_greeting 行为修正、Web 切换角色流程 |
| `prompt-reference.md` | system prompt 分层块 + PromptCache、inner_drive JSON Schema / context_summary、tool_agent 真实 prompt 与 JSON calls、模板清单更新、动态 max_tokens 修正、梦境生成位置 |
| `technical.md` | 全模块技术细节大同步（16/7 模块、9 表、1024 维、生命周期、PromptCache、monitor、ReAct 5 轮、1M 上下文/800K 阈值、2000–2500 字摘要等） |
| `message-flow.md` | MessageHandler 编排、短输入跳过、context_summary 复用、Agent 3 intent 审批循环、Web 单段推送、Observation/FactV2 双写 |
| `deployment.md` | 单进程（多 worker 会分裂会话状态）、embedding server 自动启动、1024 维模型路径、无自动备份提醒、环境变量补齐、0.0.0.0 安全提示 |
| `testing-guide.md` | 410 用例 / 30 文件、新测试文件清单、Mock 策略按真实 mocks.py 重写、real_api 基类机制、新增 4 条功能测试要点 |
| `tool-development.md` | EXTERNAL_TOOL_NAMES（8 个外部工具）、Tool 基类权限元数据、check_permission 未生效现状、execute 同步方法、dispatcher 别名结构、file_tree CLI/Web 注册差异 |

## 未修但已记录的不一致

- `README.md` 仍有少量与代码不一致：max_tokens 情绪映射表、人格示例 JSON 含 `"id"` 字段。README 不在本次同步范围内，后续单独处理。
- `doc/refactor/README.md` 的总览表写 Layer 2 "未开始"，与 `doc/refactor/progress.md` "大部分已完成" 口径不一，归 refactor 内部口径统一处理。

## 验证

- 全文 grep 确认 13 份文档中无已删除文件引用残留。
- 子代理逐份对照源码核实，未改动任何代码文件。
- 纯文档变更，未运行测试。
