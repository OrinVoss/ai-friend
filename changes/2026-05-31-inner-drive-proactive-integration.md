# 2026-05-31 - Inner Drive + Proactive Behavior 集成 (#125)

## 修改文件

### 核心代码
- **core/inner_drive.py** — 新增 `ProactiveIntent` dataclass，`assess_proactive()` 方法，`_parse_proactive_intent()` 解析器
- **prompts/system.py** — 新增 `build_inner_drive_proactive_prompt()` 主动决策 prompt
- **core/message_handler.py** — 新增 `ensure_inner_drive()` 公开方法，`handle_proactive()` 和 `handle_explore()` 支持 `intent` 参数
- **core/agent.py** — 新增 `decide_proactive_action()`，`process_proactive` 和 `process_explore` 支持 intent 参数
- **web/session.py** — `WebAgent.process_proactive/explore` 支持 intent，新增 `process_proactive_with_intent/explore_with_intent` 便捷方法
- **web/server.py** — `_proactive_loop` 用 inner drive 决策替换随机 40/60 分流，新增 silent/rate-limited 日志

### 测试
- **tests/test_inner_drive.py** — 新增 TestProactiveIntent、TestParseProactiveIntent、TestAssessProactive（+10 测试，18→28）
- **tests/test_message_handler.py** — 新增 proactive with/without intent、explore with intent（+3 测试，7→10）
- **tests/test_agent_proactive.py** — 新建，Agent decide_proactive_action/process_proactive/explore（6 测试）

### 文档
- **README.md** — 更新测试数量（171→202）、自主行为流程（两级门控）、项目结构
- **doc/architecture.md** — 新增两级门控决策架构说明
- **doc/milestones-and-issues.md** — #125 标记为已完成，v0.5 进度 4→5/21，统计更新

## 修改原因

主动行为引擎之前完全绕过 Agent 1 (InnerDrive)，使用硬编码评分和随机话题选择。
现在 inner drive 成为主动行为的决策大脑，在 ProactivityManager 轻量预筛选触发后，
由 LLM 推理决定：主动聊天/自由探索/保持安静，以及聊什么话题。

## 架构

两级门控：ProactivityManager 评分（轻量）→ InnerDrive 决策（LLM）→ 执行
