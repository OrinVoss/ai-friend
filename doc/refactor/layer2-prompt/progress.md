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
- [x] Agent 1 短输入跳过 LLM
  - `InnerDriveAgent._should_skip_llm()`
  - 配置 `agent1_short_input_threshold`
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

- [ ] 监控实际 token 节省与缓存命中率
- [ ] 进一步评估 Agent 3 Prompt 中梦境、共同回忆等块的必要性
- [ ] 缓存版本 key 优化（减少 `load_config()` 调用）

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
