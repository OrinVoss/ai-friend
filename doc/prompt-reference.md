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

所有区块的动态拼接入口。完整 prompt 由以下区块组成：

```
=== Block 0: 当前时间 ===
=== Block 1: Agent 2 工具结果 ===    # tool_records（需要时）
=== Block 1b: Agent 1 内驱判断 ===   # inner_drive_summary（需要时）
=== Block 2: 身份核心 ===            # personality.json 的 name/traits/speaking_style/backstory
=== Block 3: 对话风格示例 ===        # config.conversation_examples（#28 可配置）
=== Block 4: 当前情绪状态 ===        # EmotionalState.dominant_emotion + valence/arousal
=== Block 4b: 怨恨状态 ===           # resentment > 0.2 时注入
=== Block 4c: 情绪事件记忆 ===       # 最近未解决情绪事件
=== Block 5: 关系指标 ===            # trust/familiarity/intimacy/fun 实时值
=== Block 6: 长期记忆 ===            # facts + experiences + reflections + 梦境
=== Block 6b: 对话压缩摘要 ===       # compressed_summary（需要时）
=== Block 7: 内部工具列表 ===        # ToolRegistry.format_for_prompt() 仅 recall/remember
=== Block 8: 工具调用记录 ===        # 当前会话最近 5 条工具调用
=== Block 9: 最近对话 ===            # 当前短期记忆
=== Block 10: 破防状态指令 ===       # consecutive_negative 累计时注入
=== Block 11: 行为指令 ===           # 普通 / proactive / explore 模式
```

### 变量来源

| 区块 | 数据来源 | 说明 |
|------|----------|------|
| Block 0 | `datetime.now()` | 当前时间，格式 `YYYY-MM-DD HH:mm Weekday` |
| Block 1 | `tool_records` | Agent 2 外部工具执行结果 |
| Block 1b | `inner_drive_summary` | Agent 1 自主推理摘要 |
| Block 2 | `personality.json → PersonalityConfig` | 人格核心定义 |
| Block 3 | `config.conversation_examples` | 可配置对话风格示例（#28） |
| Block 4 | `EmotionalState` | VAD + 8 Plutchik + history |
| Block 4b | `EmotionalState.resentment` | 怨恨值 > 0.2 时注入 |
| Block 4c | `EmotionalState.emotion_events` | 最近 3 条未解决情绪事件 |
| Block 5 | `LongTermMemory.get_relationship()` | 关系四维指标 |
| Block 6 | `MemoryRetriever.retrieve_for_query()` | 三层检索结果 + 梦境 |
| Block 6b | `_compress_context()` | 超出上下文阈值时生成 |
| Block 7 | `ToolRegistry` | 仅 `recall`/`remember` 两个内部工具 |
| Block 8 | `tool_call_history` | 当前会话最近 5 条调用记录 |
| Block 9 | `ConversationBuffer` | 最近对话历史 |
| Block 10 | `consecutive_negative` | 连续负面交互破防指令 |
| Block 11 | 硬编码 | 根据模式（普通/proactive/explore）注入不同指令 |

### 特殊注入

- **情绪事件**：最近的 3 条未解决情绪事件
- **梦境**：最近的梦境记录
- **工具调用记录**：最近 20 条工具调用历史
- **怨恨状态**：resentment > 0.1 时额外注入

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
（推理指令 + 决策流程）

=== 可用工具 ===
（内部工具列表）

=== 最近对话 ===
（最近的对话历史）
```

### 决策输出格式

不需要外部工具时：
```
决策：不需要外部工具
理由：（一句话说明为什么不需要）
```

需要外部工具时：
```
决策：需要外部工具
理由：（为什么要获取这个信息）
工具请求：
  需要调用 [工具名] [具体描述]
  参数：[参数名] = [参数值]
```

---

## 3. Agent 2 ToolAgent Prompt

**文件**: `core/tool_agent.py` → `_build_prompt()`

精简 prompt，无情绪/人格/记忆：

```
当前时间：YYYY-MM-DD HH:mm Weekday

=== 可用的外部工具 ===
（完整外部工具列表，含 JSON Schema）

=== 工具调用格式 ===
<tool_call>[{"name": "xxx", "arguments": {...}}]</tool_call>

=== 任务 ===
{Agent 1 的自然语言工具请求}
```

关键特征：
- temperature = 0.3
- **无** 情绪状态
- **无** 人格特质
- **无** 对话历史
- **无** 记忆
- 仅有工具列表 + 当前时间

---

## 4. Agent 3 Roleplay Prompt

**文件**: `prompts/system.py` → `build_system_prompt()`

完整人格 prompt，7 区块拼接。

### 动态 max_tokens

回复长度随情绪动态调整（`core/agent.py`）：

| 情绪 | max_tokens |
|------|-----------|
| excited / joyful | 768 |
| surprised | 700 |
| engaged / content / neutral | 512 |
| anxious / afraid | 300 |
| melancholy / sad / frustrated / angry | 256 |

### 对话历史注入策略

```
messages = [system_prompt, ..., recent_history, current_input]
```

- 从最新对话开始向前填充
- 估算 token 后塞到 80% 模型上限（DeepSeek v4 = 180K 上下文）
- 超出时执行 `_build_messages` 压缩
- 舞台指示（括号开头的工具表演型内容）自动跳过（`#130`）

---

## 5. 记忆相关模板

### 事实抽取 — FACT_EXTRACTION_PROMPT

**位置**: `prompts/templates.py:2`

```
FACT|分类|关键词|值|置信度|重要性|fact_type
```

| 变量 | 说明 |
|------|------|
| `{text}` | 待处理的对话文本 |

分类：`preference` / `identity` / `event` / `relationship` / `routine`

### 体验总结 — EXPERIENCE_SUMMARIZATION_PROMPT

**位置**: `prompts/templates.py:35`

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

**位置**: `prompts/templates.py:51`

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

**位置**: `prompts/templates.py:86`

跨多次对话寻找反复出现的行为模式。

| 变量 | 说明 |
|------|------|
| `{facts}` | 最近 15 条活跃事实 |
| `{experiences}` | 最近 10 条体验 |

### L3 深度洞察 — REFLECTION_L3_PROMPT

**位置**: `prompts/templates.py:108`

心理学级别的深度分析。每 10 次 consolidation 触发一次。

| 变量 | 说明 |
|------|------|
| `{relationship}` | 关系指标 |
| `{current_emotion}` | 当前情绪 |
| `{patterns}` | 最近 5 条 L2 模式 |
| `{facts}` | 最近 20 条事实 |
| `{experiences}` | 最近 20 条体验 |

### 情感分析 — EMOTION_ANALYSIS_PROMPT

**位置**: `prompts/templates.py:138`

```json
{"sentiment": <float>, "personal_sharing": <bool>, "topic_energy": <float>}
```

| 变量 | 说明 |
|------|------|
| `{text}` | 用户消息原文 |

### 记忆重排序 — MEMORY_RERANK_PROMPT

**位置**: `prompts/templates.py:153`

候选 > 15 条时触发，极小 LLM 调用（10-20 tokens 输出），选出 3-8 条最相关。

| 变量 | 说明 |
|------|------|
| `{query}` | 用户查询 |
| `{candidates}` | 候选记忆列表 |

---

## 6. 其他模板

### 上下文压缩 — CONTEXT_COMPRESS_PROMPT

**位置**: `prompts/system.py:11`

当对话历史超过模型上下文 80%（~144K tokens）时触发。生成 100-150 字摘要，压缩后清除 ConversationBuffer。

```
请将以下对话压缩为一段简洁的对话历史摘要。
保留重要信息：用户的关键事实、讨论过的话题、情感变化。
摘要在100-150字之间，用第三人称。
```

### 梦境生成

**位置**: `core/agent.py` → `_generate_dream()`

不依赖固定 prompt 模板，直接使用 LLM 调用，基于当前情绪 + 记忆生成 1-2 句碎片化梦境。
