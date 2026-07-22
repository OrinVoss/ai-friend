# Token 节省三刀变更记录

> 2026-07-22，依据 `doc/fix-plan-2026-07-22-token-budget.md` 执行。

## T1：Agent 1 指令瘦身

**根因**：`prompts/instructions.py` 五段指令文本合计 ~1429 chars，占 Agent 1 prompt 的 66%。

**修法**：
1. 新增 `INNER_DRIVE_COMPRESSED`（684 chars，原五段压缩合并），保留全部硬规则：
   - "不要推断用户的人格、心理动机或'潜台词'"（一字保留）
   - "永远不需要为此调用工具"（一字保留）
   - 用户指令优先、指代规则、JSON 输出格式等
2. 旧五段常量保留为遗留别名（测试兼容）。
3. `_build_inner_drive_instructions_block` 新增 `tool_call_history=None` 可选参数：
   - `None`（缺省）：总是注入 followup_rules（向后兼容）
   - `[]`：省略 followup_rules 块及引导句
   - 非空：注入 followup_rules
4. `build_inner_drive_prompt` 传递 `tool_call_history` 时绕过 prompt cache（followup_rules 每轮动态）。

**影响文件**：
- `prompts/instructions.py` — 新增 `INNER_DRIVE_COMPRESSED`
- `prompts/system.py` — 修改 `_build_inner_drive_instructions_block` 和 `build_inner_drive_prompt`
- `tests/test_prompt_instructions.py` — 更新断言匹配压缩文本

## T2：Agent 3 对话历史预算

**根因**：`_build_messages` 只有 COMPRESS_THRESHOLD（~800k tokens），等于没有预算，单条 chars_in 13-19k。

**修法**：
1. `config.py` 新增 `react_history_budget_chars: int = 16000`。
2. `_build_messages` 在现有 token 预算外增加字符预算：倒序遍历历史时累计 chars，超过 16000 时从最旧开始丢弃。
3. 不触发 compress_context（丢弃部分由记忆系统兜底）。
4. 丢弃时打日志 `[msg] history budget: kept=N dropped=M`。

**影响文件**：
- `config.py` — 新增字段
- `config.example.json` — 新增配置项
- `core/message_handler.py` — 修改 `_build_messages`
- `doc/config-reference.md` — 文档同步

## T3：`history_search` 内部工具

**根因**：历史被预算裁剪后，Agent 需要能按需查原始对话。现有 `recall` 查的是提炼记忆不查原始 turn。

**修法**：
1. `storage/repository.py`：
   - 扩展 `get_recent_turns` 返回 `turn_number`、`created_at`（向后兼容）
   - 新增 `search_turns(query, limit)` — 关键词 LIKE 搜索原始对话
   - 新增 `get_turns_range(turn_from, count)` — 按轮次范围批量读取
2. `memory/long_term.py`：新增 `search_turns`、`get_turns_range` 同步包装
3. `memory/retrieval.py`：新增 `embedding_engine` 公共只读属性
4. `tools/memory_tools.py`：新增 `HistorySearchTool`（keyword/semantic/batch 三种模式）
5. `core/message_handler.py`：`_make_internal_registry` 注册 `HistorySearchTool`
6. `prompts/instructions.py`：`AGENT3_BASE_INSTRUCTIONS` recall 行补充 history_search 说明

**影响文件**：
- `storage/repository.py` — 扩展 `get_recent_turns` + 新增 `search_turns`/`get_turns_range`
- `memory/long_term.py` — 新同步包装
- `memory/retrieval.py` — 新增 `embedding_engine` 属性
- `tools/memory_tools.py` — 新增 `HistorySearchTool`
- `core/message_handler.py` — 注册新工具
- `prompts/instructions.py` — Agent 3 提示补充
- `tests/test_message_handler.py` — 内部工具清单更新

## 验收

- 全量测试：**840 passed, 2 skipped**（与基线一致）
- Agent 1 prompt 压缩率：1429 → 684 chars（**52%**，超过≤800 目标）
- Agent 3 历史不会无限增长（16000 chars 封顶）
- `history_search` 可被 Agent 1/3 调用查询已被裁剪的历史

## 观察点

- `/api/monitor` 中 source=inner_drive 的 chars_in 均值应降到 ~2000 以下
- react 的 chars_in 在长会话下不超过 ~19k
- 重启进程后生效（缓存键不随 instructions.py 变更失效）

---

## 复审追加（2026-07-22，主 agent 亲自把关）

**发现的问题**：T1 指令瘦身（内驱推理块 1415→726 chars，-49%）的成果会被 T3 吃回——`history_search` 的 JSON Schema（~660 chars）同时注入了 Agent 1 与 Agent 3 的 prompt，而 Agent 1 恰是 token 大头（61%）。Agent 1 有 recall 循环已够用，不需要原始对话检索。

**修正**：`_make_internal_registry(include_history_search=False)`——Agent 1 注册表只含 recall/remember；Agent 3 三处调用点（_run_agent3/handle_proactive/handle_explore）传 True。两份注册表分别缓存。Agent 1 prompt 净瘦身现在真正生效（约 -20%），Agent 3 保留按需查历史能力。

**验证**：
- 新增 `test_history_search_only_in_agent3_registry`；`test_internal_registry_isolation` 期望改为 {recall, remember}。
- 真库冒烟：keyword/批量/最新/未命中 全部正确；`get_recent_turns` 已含 turn_number。
- 全量 **841 passed + 2 skipped** 全绿。
