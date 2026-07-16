# Prompt 工程参考

> 所有提示词模板的位置、用途和变量说明。

---

## 目录

1. [System Prompt 组装](#1-system-prompt-组装)
2. [Agent 1 InnerDrive Prompt](#2-agent-1-innerdrive-prompt)
3. [Agent 2 ToolAgent Prompt](#3-agent-2-toolagent-prompt)
4. [Agent 3 Roleplay Prompt](#4-agent-3-roleplay-prompt)
5. [记忆相关模板](#5-记忆相关模板)
6. [其他模板](#6-其他模板)

---

## 1. System Prompt 组装

**文件**: `prompts/system.py`

所有区块的拼接入口。自 #160 起区块按静态 / 慢变 / 动态三层拆分，静态与慢变块由
`core/prompt_cache.py` 的 `PromptCache` 缓存。完整 prompt 由以下区块组成：

```
=== Block 0: 当前时间 ===
=== Block 1: Agent 2 工具结果 ===    # tool_records（需要时）
=== Block 1b: Agent 1 内驱判断 ===   # inner_drive_summary（需要时）
=== Block 2: 身份核心 ===            # personalities/{role_id}.json（静态缓存，无 TTL）
=== Block 3: 对话风格示例 ===        # config.conversation_examples，仅前 N 轮（#28 可配置）
=== Block 4: 当前情绪状态 ===        # EmotionalState.dominant_emotion + valence/arousal
=== Block 4b: 怨恨状态 ===           # resentment > 0.2 时注入，> 0.5 升级为"记仇"
=== Block 4c: 情绪事件记忆 ===       # 最近未解决情绪事件
=== Block 5: 关系指标 ===            # trust/familiarity/intimacy/playfulness（慢变缓存）
=== Block 6: 长期记忆 ===            # facts + experiences + reflections（慢变缓存）
=== Block 6a: 梦境 ===               # 最近的梦 / 刚睡醒提示（需要时）
=== Block 6b: 对话压缩摘要 ===       # compressed_summary（需要时）
=== Block 7: 内部工具列表 ===        # ToolRegistry.format_for_prompt() 仅 recall/remember
=== Block 8: 工具调用记录 ===        # 当前会话最近 5 条工具调用
=== Block 9: 最近对话 ===            # 当前短期记忆
=== Block 10: 破防状态指令 ===       # consecutive_negative 累计时注入（1/3/5 条三档）
=== Block 11: 行为指令 ===           # 普通 / proactive / explore 模式
=== Block 12: 输出规则 ===           # final_response 汇报规则 / 默认文本 + 可选 JSON intent
```

注：静态块（Block 2）无 TTL，personality 文件变更（mtime/size）即自动失效；慢变块
（Block 5/6）按 `config.prompt_cache_ttl_seconds`（默认 60 秒）缓存。当 Agent 1 的
`drive_result.context_summary` 可用时，Block 5+6 直接复用该摘要，不再重复检索。

### 变量来源

| 区块 | 数据来源 | 说明 |
|------|----------|------|
| Block 0 | `datetime.now()` | 当前时间，格式 `YYYY-MM-DD HH:mm Weekday` |
| Block 1 | `tool_records` | Agent 2 外部工具执行结果 |
| Block 1b | `inner_drive_summary` | Agent 1 自主推理摘要 |
| Block 2 | `personalities/{role_id}.json → PersonalityConfig` | 人格核心定义（静态缓存） |
| Block 3 | `config.conversation_examples` | 可配置对话风格示例（#28），仅前 `conversation_examples_max_turns` 轮（默认 3）注入 |
| Block 4 | `EmotionalState` | VAD + 8 Plutchik + history |
| Block 4b | `EmotionalState.resentment` | 怨恨值 > 0.2 时注入，> 0.5 升级为"记仇"强指令 |
| Block 4c | `EmotionalState.emotion_events` | 最近 3 条未解决情绪事件 |
| Block 5 | `LongTermMemory.get_relationship()` | 关系四维指标（慢变缓存） |
| Block 6 | `MemoryRetriever.retrieve_for_query()` | 三层检索结果（慢变缓存） |
| Block 6a | `_build_dreams_block()` | 情绪事件中含"梦"的记录；idle > 10 分钟时给"刚睡醒"提示 |
| Block 6b | `ContextManager.compress()` | 超出上下文阈值时生成 |
| Block 7 | `ToolRegistry` | 仅 `recall`/`remember` 两个内部工具 |
| Block 8 | `tool_call_history` | 当前会话最近 5 条调用记录 |
| Block 9 | `ConversationBuffer` | 最近对话历史 |
| Block 10 | `consecutive_negative` | 连续负面交互破防指令 |
| Block 11 | `prompts/instructions.py` | 根据模式（普通/proactive/explore）注入不同指令 |
| Block 12 | `prompts/instructions.py` | `final_response` 时为汇报规则；否则默认文本 + 可选 JSON intent |

### 特殊注入

- **情绪事件**：最近的 3 条未解决情绪事件
- **梦境**：最近的梦境记录（情绪事件中 trigger 含"梦"的条目）
- **工具调用记录**：最近 5 条工具调用历史
- **怨恨状态**：resentment > 0.2 时注入，> 0.5 时升级为"记仇"强指令

---

## 2. Agent 1 InnerDrive Prompt

**文件**: `prompts/system.py` → `build_inner_drive_prompt()`

```
当前时间：YYYY-MM-DD HH:mm Weekday

=== 你对自己的认知 ===
你是{name}，一个 AI 朋友。
你的核心特质：{traits}

你现在的情绪：{emotion}（效价 {v:+.2f}，唤醒度 {a:.2f}）
你和用户的关系：信任 {trust:.1f}，熟悉度 {familiarity:.1f}

=== 你了解的关于用户的事情 ===
（top 8 facts）

=== 你们的共同回忆 ===
（top 3 experiences）

=== 内驱推理 ===
（检查清单 + 决策原则 + 工具触发规则 + JSON 输出格式）

=== 你最近的工具调用 ===
（最近 5 条，需要时）

=== 可用工具 ===
（可用工具列表 + 可读取目录说明）

=== 最近对话 ===
（最近的对话历史）
```

该 prompt 同样按静态/慢变/动态分层缓存（身份/指令/工具为静态，关系/记忆为慢变，见第 1 节）。
指令文本集中在 `prompts/instructions.py`，工具触发规则由 `prompts/tools_description.py` 按注册表生成。
短输入（默认 < 20 字符，`agent1_short_input_threshold`）且无工具关键词、最近无成功工具调用时，
跳过 Agent 1 的 LLM 调用，直接判定"不需要外部工具"。

### 决策输出格式

由 `INNER_DRIVE_SCHEMA` 强制的 JSON 对象（`response_format`）：

```json
{
  "needs_external_tools": true/false,
  "reasoning": "推理过程和情绪表达（Agent 3 会看到）",
  "summary": "传给 Agent 3 的简洁结论",
  "recall_query": "需先回忆用户信息时的查询内容，否则留空",
  "tool_requests": [
    {"description": "需要做什么", "suggested_tool": "工具名（可选）", "params_hint": {"参数名": "参数值"}}
  ]
}
```

`recall_query` 非空时先执行内部 `recall` 并把结果喂回，进入下一轮决策迭代。
Agent 1 同时把格式化好的关系/记忆摘要（`context_summary`）交给 Agent 3 复用。

---

## 3. Agent 2 ToolAgent Prompt

**文件**: `prompts/system.py` → `build_tool_agent_prompt()`（由 `core/tool_agent.py` 调用）

精简 prompt，无情绪/人格/记忆：

```
=== 工具调用代理 ===
（身份声明：纯工具调用代理，不闲聊、不回应）

可用工具：
（完整外部工具列表，含 JSON Schema）

输出格式（严格的 JSON）：
{"calls": [{"name": "工具名", "arguments": {...}}]}

规则：
（`prompts/tools_description.py` 按注册表生成的触发规则 + 通用规则）
```

任务由 user 消息携带：`run()` 时为 `用户输入：...`，`run_with_request()` 时为
`Agent 1 的内驱推理请求：...`。

关键特征：
- max_tokens = 1024，`response_format` 强制 JSON Schema
- **无** 情绪状态
- **无** 人格特质
- **无** 对话历史
- **无** 记忆
- 仅有工具列表 + 任务请求

---

## 4. Agent 3 Roleplay Prompt

**文件**: `prompts/system.py` → `build_system_prompt()`

完整人格 prompt，静态/慢变/动态分层区块拼接（见第 1 节）。

### 动态 max_tokens

回复长度随情绪动态调整（`core/agent.py`）：

| 情绪 | max_tokens |
|------|-----------|
| excited / joyful | 512 |
| surprised | 448 |
| engaged / content / trusting / anticipating / neutral | `config.max_tokens`（默认 512） |
| anxious / afraid / melancholy / sad / frustrated / angry / disgusted | 128 |
| 其他未列出情绪 | `config.max_tokens` |

### 对话历史注入策略

```
messages = [system_prompt, ..., recent_history, current_input]
```

- 从最新对话开始向前填充
- 估算 token 后塞到 80% 模型上限（deepseek-v4-flash = 1M 上下文，阈值 ~800K tokens）
- 超出时触发 `ContextManager` 压缩（见第 6 节）
- 舞台指示（`（调用`/`（前奏` 等括号开头）及带 `is_tool_claim` 元数据的表演型内容自动跳过（`#130`）

---

## 5. 记忆相关模板

以下模板均位于 `prompts/templates.py`，渲染统一走 `safe_format()`（格式化失败时原样返回并记 warning）。

### 事实抽取 — FACT_EXTRACTION_PROMPT

**位置**: `prompts/templates.py`

```
FACT|分类|关键词|值|置信度|重要性|fact_type
```

| 变量 | 说明 |
|------|------|
| `{text}` | 待处理的对话文本 |

分类：`preference` / `identity` / `event` / `relationship` / `routine`

### 体验总结 — EXPERIENCE_SUMMARIZATION_PROMPT

**位置**: `prompts/templates.py`

```
SUMMARY: <一行总结>
TONE: <情感色调>
SIGNIFICANCE: <0.0~1.0>
IMPORTANCE: <0.0~1.0>
TAGS: <逗号分隔>
```

| 变量 | 说明 |
|------|------|
| `{text}` | 待总结的对话文本 |

### L1 反思 — REFLECTION_PROMPT

**位置**: `prompts/templates.py`

```
TYPE: <insight_type>
CONTENT: <反思内容>
SIGNIFICANCE: <0.0~1.0>
RELATED_EXPERIENCES: <ID列表>
```

| 变量 | 说明 |
|------|------|
| `{experiences}` | 最近 5 条体验 |
| `{reflections}` | 最近 3 条反思 |
| `{facts}` | 最近 10 条活跃事实 |
| `{current_emotion}` | 当前情绪标签 |
| `{relationship}` | 关系四维指标 |

### L2 模式识别 — REFLECTION_L2_PROMPT

**位置**: `prompts/templates.py`

跨多次对话寻找反复出现的行为模式。

| 变量 | 说明 |
|------|------|
| `{facts}` | 最近 15 条活跃事实 |
| `{experiences}` | 最近 10 条体验 |

### L3 深度洞察 — REFLECTION_L3_PROMPT

**位置**: `prompts/templates.py`

心理学级别的深度分析。每 10 次 consolidation 触发一次。

| 变量 | 说明 |
|------|------|
| `{relationship}` | 关系指标 |
| `{current_emotion}` | 当前情绪 |
| `{patterns}` | 最近 5 条 L2 模式 |
| `{facts}` | 最近 20 条事实 |
| `{experiences}` | 最近 20 条体验 |

### 情感分析 — EMOTION_ANALYSIS_PROMPT

**位置**: `prompts/templates.py`

```json
{"sentiment": <float>, "personal_sharing": <bool>, "topic_energy": <float>}
```

| 变量 | 说明 |
|------|------|
| `{text}` | 用户消息原文 |

### 记忆重排序 — MEMORY_RERANK_PROMPT

**位置**: `prompts/templates.py`

候选 > 15 条时触发，极小 LLM 调用，从候选（最多展示 30 条）中选出最相关的若干条（上限 15 条）。

| 变量 | 说明 |
|------|------|
| `{query}` | 用户查询 |
| `{candidates}` | 候选记忆列表 |

---

## 6. 其他模板

### 上下文压缩 — CONTEXT_COMPRESS_PROMPT

**位置**: `prompts/system.py`

当对话历史超过模型上下文 80%（1M 上下文，阈值 ~800K tokens）时触发。生成 2000-2500 字摘要，压缩后清除 ConversationBuffer。

```
请将以下对话压缩为一段对话历史摘要。
保留重要信息：用户的关键事实、讨论过的话题、情感变化。
摘要在2000-2500字之间，用第三人称。
```

### 梦境生成

**位置**: `core/sleep_manager.py` → `generate_dream()`（`core/agent.py` 的 `_generate_dream()` 仅转发）

不依赖固定 prompt 模板，直接拼接 LLM 调用：基于最近 5 条活跃事实 + 最近 3 条体验 +
当前情绪，生成 1-2 句碎片化梦境（第一人称、碎片化诗意，max_tokens=100）。梦境会记录为
情绪事件（trigger 前缀 `梦:`）并保存为 `tags=["dream"]` 的体验，之后经 Block 6a 注入 prompt。
