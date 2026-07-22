# 文档同步任务：doc/ 目录按最近三周工作更新（2026-07-01 → 2026-07-22）

> 面向执行者：本清单只列"哪些文档可能过期、该往哪个方向查"。**具体事实一律以代码和 `changes/` 记录为准**，动笔前先 grep 核实，不要凭本清单照抄。
> 项目：D:/桌面/编程作品/AI朋友。测试现状：`python -m pytest tests --ignore=tests/real_api -q` → **838 passed + 2 skipped**。
> 风格：保持各文档现有结构与中文风格；不新增文档（已有 doc/ 内更新即可）；改动处与 `changes/` 对应记录口径一致。

## 最近三周的主要变更（查这些 changes/ 记录与提交）

### 第一周（07-01 ~ 07-08）
1. **监控面板**（`core/monitor.py` + `/monitor` 页）：LLM 调用环形缓冲、浅色主题、展开状态保持、JSON/Markdown 导出、CSP/favicon 修复（MN-001~005）。
2. **工具**：music_play 随机播放、file_tree 目录树工具、notify 参数别名与报错改进。
3. **dispatcher 别名事故**（title→song 冲突修复，known-issues #1 起源）。
4. **InnerDrive 结构化**：JSON Schema 决策替代关键词解析、Agent 1 可见工具历史、短输入规则扩宽、Agent 3 条件 JSON 意图 + Agent 1 审批回路。
5. **睡眠**：晨醒兜底窗口、睡前/醒消息持久化（页面刷新可恢复）。
6. **文档**：`doc/startup-flow.md`、`doc/known-issues.md` 建立。

### 第二周（07-09 ~ 07-15）
7. **#160 分层 PromptCache**（`core/prompt_cache.py`）：静态/慢变/动态三层块 + Agent 1 context_summary 复用（Think Once 雏形）+ 对话示例限轮注入。
8. **MessageHandler 重构**：状态机、ToolExecutionResult、注册表隔离（#203）、封装与错误恢复、魔法数字常量化。
9. **#294 指令集中化**：`prompts/instructions.py`、`prompts/tools_description.py` 工具规则按 registry 动态生成。
10. **系统化方案**（`doc/systematic-solution.md`）：六层重构蓝图；`doc/refactor/` 各层计划目录建立。
11. **Layer 1 一期（ML-001）**：Observation→Fact 双写、`MemoryLifecycleManager`、`use_observation_fact` 开关（后于第三周删除）。

### 第三周（07-16 ~ 07-22）
12. **统一管线 P0-P3**：`core/session_factory.py`（共享装配）、`core/conversation_engine.py`、`core/runtime_driver.py`——CLI/Web 同一管线，CLI 内联状态机删除。
13. **MemoryAgent**：P0-P1 装配接入 InnerDrive（`use_memory_agent` 开关）、MA-002 相关性下限、P2 矛盾传播+向量锚点指代；空查询跳过（F3）。
14. **Agent 1 短输入跳过整体移除**（`dc7d7f8`）：所有输入走完整 Agent 1 推理。
15. **2026-07-17 全库审计修复**（`changes/2026-07-17-审计修复-阶段0-5汇总.md`，约 50 项）：DB threading.Lock、personality 锁+合并保存、Agent3 内部注册表、WS 断开宽限期、REST 走 executor、proactivity 状态持久化等。
16. **Memory Layer 1 完整上线**：schema v4（user_facts→facts_v2）、v5（reflections→insights_v2）、v6（删两张 archive 表）；`use_observation_fact` 开关删除；Insight 替换 Reflection。
17. **主动沉思循环 + 挂念清单**（`core/inner_drive_state.py`）：一期扁平列表、二期类型化条目+生命周期+情绪浮现+响应路径注入+consolidation 合流。
18. **F1-F6 主动空转修复**（`changes/2026-07-20-主动思考空转修复.md`）：silent 指数退避、空查询跳过 memory_agent、梦境标注【梦境】、沉默疲劳、API 熔断。
19. **A 批（A1-A8）**：Web token 鉴权、Provider 截断语义、request_id 全链路、人格校验器、GC 语义合并、情绪按时间衰减、归档表 DROP。
20. **工具系统 Layer 5**：ToolResult v2 错误分类、per-tool 超时、并行调度、智能重试、参数校验、工具 metrics；dispatcher 全局别名删除、各工具 `ALIASES`（KI-1）。
21. **embedding 看门狗**（M-18）；**SL-012 睡眠兜底**（睡到合法时段外立即唤醒）。
22. **#244/#263/#164**：Cookie SameSite=Lax、run_async 超时取消传播、记忆固化合并为一次 LLM 调用（`consolidation_unified_call`）。
23. **recall 修复**：RecallTool/retrieve_by_recall_tag 改走 retrieve_for_query 混合检索；统一固化 `max_tokens=1024` 防截断。
24. **R1-R5 推理与 prompt 修复**（`doc/fix-plan-2026-07-22-reasoning-and-prompt.md`）。
25. **CognitiveState**（`core/cognitive_state.py`，Phase 1+2）+ prompt 污染修复（输入去重、error_fallback 跳过、Agent 1 决策温度 0.3）。

## 各文档检查清单

### `doc/architecture.md`
- 测试数与测试文件数（→ 838+2）；schema 版本（→ v6）与表清单（user_facts_archive/reflections_archive 已删，insights_v2 上线）。
- 记忆系统段：Observation→Fact→Insight 三层、MemoryAgent、unified consolidation、recall 混合检索。
- 新增模块：`core/cognitive_state.py`、`core/inner_drive_state.py`（挂念清单）、沉思循环、`core/prompt_cache.py`（#160）、`core/monitor.py`（监控面板）。
- 统一管线 P0-P3（session_factory / conversation_engine / runtime_driver）表述核对。
- 配置示例中的 `use_observation_fact` 删除；审计修复相关描述（DB threading.Lock 等）。

### `doc/message-flow.md`
- 三层流水线描述更新：Agent 1 结构化决策 + recall 循环；CognitiveState 装配；proactive 沉思循环（think rounds + care list + silent 退避）；Agent 3 意图审批回路。
- REFLECT 段：unified consolidation（一次调用三段式）、Observation/Insight 写入。
- 情绪更新：软边界 + 时间衰减（decay_elapsed）。
- MessageHandlerState 状态机与统一管线 P0-P3 的现状核对（旧 CLI 状态机描述是否已清）。

### `doc/technical.md`
- 记忆系统章：facts_v2/insights_v2/observations 字段、GC、矛盾检测（LLM 复核）、A5 合并。
- 工具系统章：ToolResult v2 错误分类、per-tool 超时、并行调度、`ALIASES` 别名（替代全局 _normalize_args）、to_json_schema per-tool（#273）。
- Provider：重试 2/4/8s + 熔断、截断语义（4 种模式）、per-call temperature。
- 情绪章：软边界、时间衰减、turns_without_anger 字段化。

### `doc/config-reference.md`
- 新增项核对（以 config.py 为准）：`proactive_think_loop`、`proactive_think_max_rounds`(2)、`inner_drive_*`（surface_top_k/response_k/decay_rate/care_similarity_threshold/care_list_size）、`consolidation_unified_call`、`degrade_threshold`、`max_fake_actions`、`use_memory_agent` 及 memory_agent 相关阈值、web token（A1 的 key 名称查代码）、`AI_FRIEND_PERSONALITY_FILE` 环境变量。
- 删除项：`use_observation_fact`。

### `doc/api.md`
- A1 Web token 鉴权：何时需要、Header/query 两种传法、WS init 校验、未配置时的行为（查 web/server.py 与 changes/2026-07-21-a1-web-token-auth.md）。
- 监控字段新增（request_id、truncated/finish_reason 等，查 core/monitor.py）；`/monitor` 页与 `/api/monitor` 导出能力（JSON/Markdown，MN-005）。

### `doc/prompt-reference.md`
- Agent 1 prompt：推理约束（只判意图）、工具规则动态生成（rule_tools）、分层缓存（#160 静态/慢变/动态块与 TTL）。
- Agent 3 prompt 区块表更新：判断块截断+免责标题、insight ≤120 字符 ≤2 条、tool history 3 条、梦境标注【梦境】、error_fallback/sleep/重复输入过滤。
- 模板表新增：CONSOLIDATION_UNIFIED_PROMPT、CARE_CLUE_PROMPT、沉思循环协议；FACT_EXTRACTION 口径（亲口陈述）。

### `doc/tool-development.md`
- 已部分更新（ALIASES）。补：ToolResult v2 错误分类与 retryable、per-tool `timeout_seconds`、并行执行、参数校验（_validate_args）、智能重试。

### `doc/personality-guide.md`
- emotional_state 新运行时字段：`turns_without_anger`、`last_decay_at`、`turn_seconds`、`_valence_boundary_count`（A6/R4）。
- 人格校验器存在（A4，查代码确认入口）。

### `doc/deployment.md`
- 已含看门狗段。补：Web token 鉴权部署注意（何时必须开、反代下的传递）、schema v6 迁移自动备份说明。

### `doc/startup-flow.md`
- 嵌入服务段：看门狗交接（就绪后 _watch_then_guard）。

### `doc/systematic-solution.md` 与 `doc/refactor/progress.md`
- 六层状态与 closure 文档对齐（多数已被各 executor 更新，抽查核对即可）；CognitiveState Phase 1+2 补记。

### `doc/testing-guide.md`
- 测试数 → 838 passed + 2 skipped；新测试文件（test_cognitive_state.py、test_consolidation_unified.py、test_proactivity.py、test_database_concurrency.py 等，以 tests/ 目录为准）。

### `doc/known-issues.md`
- #1 已标根治（勿动）；确认无其他需要新增标注的已修条目（不确定就不要动）。

## 验收

1. 每处改动与 `changes/` 记录口径一致；数字类事实（测试数、schema 版本、配置默认值）与代码 grep 结果一致。
2. 不引入虚构配置项/模块名；引用文件路径必须真实存在。
3. 完成后写 `changes/2026-07-22-doc-sync.md` 列出各文档改了哪些段。
