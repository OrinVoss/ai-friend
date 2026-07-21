# Layer 2: Prompt 分层与静态化 — 进度

## 状态

大部分已完成。

## 已完成

- [x] `core/prompt_cache.py`：分层 Prompt Cache
  - 静态块无 TTL
  - 慢变块 TTL 可配置
  - 动态块不缓存
- [x] `prompts/system.py` 拆分为独立 block
  - `_build_identity_block`
  - `_build_examples_block`
  - `_build_emotion_block`
  - `_build_relationship_block`
  - `_build_memory_block`
  - `_build_tool_history_block`
  - `_build_inner_*_block` 等
- [x] ~~Agent 1 短输入跳过 LLM~~（`_should_skip_llm` 已于 2026-07-16 整体移除：API 成本低，关键词误判不值得；配置 `agent1_short_input_threshold` 同步删除）
- [x] Agent 1 向 Agent 3 传递 `context_summary`
  - `InnerDriveResult.context_summary`
  - `_run_agent3()` 复用该摘要
- [x] 静态对话示例限制
  - 配置 `conversation_examples_max_turns`
  - `_build_examples_block()` 超过阈值后省略
- [x] 指令集中化
  - `prompts/instructions.py`
  - Agent 1/2/3 的指令统一从这里引用
- [x] 工具规则动态生成
  - `prompts/tools_description.py`
  - `format_tool_rules()` / `format_intent_options()`
- [x] 情绪摘要化
  - `EmotionalState.to_prompt_summary()`
  - Runtime 调用方传 `emotion_summary` 字典给 prompt builder
- [x] Tool Agent Prompt 精简
  - 不包含人格/情绪/关系/回忆

## 待完成

- [x] 监控实际 token 节省与缓存命中率（PC-002：见 `core/prompt_cache.py` stats）
- [x] 进一步评估 Agent 3 Prompt 中梦境、共同回忆等块的必要性（L2-3 评估完成，结论见下）
- [x] 缓存版本 key 优化（减少 `load_config()` 调用）（CF-010：见 `config.py` 进程级缓存）

## L2-3：Agent 3 Prompt 块级必要性评估

> 评估日期：2026-07-21。样本：基于 `personalities/default.json` + 典型 5 facts / 5 experiences / 2 reflections / 3 轮对话历史，用 `prompts/system.py::build_system_prompt` 静态生成。结论为**只评估、不改代码**，后续压缩需人工确认后立项。

### 各块占比（代表性样本，总长约 2100 chars）

| 块 | 分类 | 长度 | 占比 | 决策 | 理由 |
|----|------|------|------|------|------|
| identity（人格/背景） | static | ~340 | 16.2% | **保留** | 人格核心，已静态缓存且无 TTL，成本低。 |
| internal_tools（可用工具规则） | static-ish | ~325 | 15.5% | **保留** | 已由 registry 动态生成，Agent 3 需知道可用内部工具。 |
| memory（事实/共同回忆/反思） | slow | ~302 | 14.4% | **保留** | slow TTL 缓存，命中率高；是长期记忆体现。 |
| instructions（Agent 3 指令） | dynamic | ~188 | 8.9% | **保留** | 行为约束核心，不可缺。 |
| emotion（情绪状态） | dynamic | ~93 | 4.4% | **保留** | 已摘要化，成本低，直接影响语气。 |
| output_rules（输出规则） | dynamic | ~67 | 3.2% | **保留** | 格式约束必要。 |
| examples（对话示例） | static | ~65 | 3.1% | **保留** | 已限制前 N 轮，早期引导作用明显。 |
| emotion_events（未解决情绪事件） | dynamic | ~64 | 3.0% | **保留** | 只在有未解决事件时出现，有情节连贯价值。 |
| relationship（关系维度） | slow | ~64 | 3.0% | **保留** | 简短，已缓存，关系感基础。 |
| conversation（最近对话） | dynamic | ~63 | 3.0% | **保留** | 上下文核心。 |
| tool_history（工具调用记录） | dynamic | ~38 | 1.8% | **保留** | 只在调用后出现，帮助理解 tool results。 |
| dreams（梦境） | dynamic | 0 | 0.0% | **保留** | R4 已做条件过滤（idle≤600 不注入），触发概率低。 |
| resentment（怨恨） | dynamic | 0 | 0.0% | **保留** | resentment>0.2 才出现，有情绪叙事价值。 |
| consecutive_negative（破防） | dynamic | 0 | 0.0% | **保留** | ≥1 才出现，破防机制必要。 |

### memory 块内部分解

在样本中 memory 块约 302 chars，占整个 Agent 3 prompt 的 14.4%：

- facts：92 chars（memory 块内 30.5%，总 prompt 约 4.4%）
- **experiences（共同回忆）**：142 chars（memory 块内 47.0%，总 prompt 约 6.8%）
- reflections：66 chars（memory 块内 21.9%，总 prompt 约 3.2%）

### 评估结论

- **experiences（共同回忆）**：**保留，维持当前上限 5 条**。它是 memory 块中最大的组成部分，但提供了“共同经历”的叙事连续性；删除会让 AI 朋友失去“记得我们一起做过的事”的感觉。若未来 token 紧张，可优先压缩到 3 条或按情感显著度/时间衰减排序，**不在本计划内修改**。
- **facts**：**保留，上限 10 条合理**。用户事实是 Agent 3 个性化回复的基础（名字、职业、宠物等），不应删除。
- **reflections**：**保留，上限 3 条合理**。数量已很少，提供高层洞察，删除对长度收益不大但会损失深度。
- **dreams**：**保留**。R4 已实现 idle≤600 不注入 + sleep 轮过滤，只在“睡醒”场景出现，平时无成本。
- **其余块**：均为必要块，保留。

### 后续可立项方向（本次不改）

1. 若监控显示 prompt 总长持续接近或超过模型上下文限制，可优先压缩 `experiences` 上限或按 `significance` 排序截断。
2. 可考虑将 `reflections` 与 `experiences` 合并为“洞察与回忆”一块，但需评估对角色感的影响。
3. 进一步观察生产日志 `chars_in` 与 `prompt_cache` stats，用真实分布验证以上静态样本结论。

## 关键文件

- `core/prompt_cache.py`
- `prompts/system.py`
- `prompts/instructions.py`
- `prompts/tools_description.py`
- `core/inner_drive.py`
- `core/message_handler.py`
- `config.py`

## 阻塞项

无。
