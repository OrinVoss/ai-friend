# Layer 2: Prompt 分层与静态化

## 目标

把系统提示拆成"静态块 / 慢变块 / 动态块"，只重建真正变化的部分；减少单次请求中重复构建系统提示的开销。

## 当前状态

**已完成大部分**：

- [x] 分层 Prompt Cache（`core/prompt_cache.py`）
- [x] `prompts/system.py` 拆分为独立 block 并接入缓存
- [x] Agent 1 短输入直接跳过 LLM（`agent1_short_input_threshold`）
- [x] Agent 1 把格式化后的记忆/关系摘要传给 Agent 3，避免重复检索
- [x] 静态对话示例仅前 N 轮注入（`conversation_examples_max_turns`）
- [x] 指令文本集中管理（`prompts/instructions.py`）
- [x] 工具触发规则从 ToolRegistry 动态生成（`prompts/tools_description.py`）
- [x] 情绪格式化下沉到 `EmotionalState.to_prompt_summary()`，Runtime 只传轻量摘要
- [x] Tool Agent Prompt 精简，不再包含人格/情绪/关系/回忆

## 关键提交

- `49a6fd4` — fix #160: hierarchical prompt cache + Agent 1 context summary + short input skip
- `255b259` — refactor(prompts): centralize instructions, derive tool rules from registry (#294)
- `ea4c617` — refactor(prompts/runtime): complete #294 P2-5 - pass emotion_summary from runtime

## 缓存分层

```
静态块（无 TTL，personality 文件变更时失效）：
  - identity
  - examples
  - inner_drive_instructions
  - inner_drive_tools

慢变块（TTL 60 秒，可配置）：
  - relationship
  - memory（facts / experiences / reflections）

动态块（不缓存）：
  - current time
  - tool records
  - recent conversation
  - current emotion
```

## 配置项

```json
{
  "prompt_cache_ttl_seconds": 60,
  "agent1_short_input_threshold": 20,
  "conversation_examples_max_turns": 3
}
```

## 剩余工作

- [ ] 监控 Prompt Cache 实际命中率与 token 节省效果
- [ ] 进一步压缩 Agent 3 Prompt（共同回忆、梦境等是否每轮都需要）
- [ ] 考虑把 `personality_file` 缓存版本逻辑移到配置层，避免 `load_config()` 反复调用

## 依赖

- Layer 1 Memory 生命周期：稳定的 Memory Context 摘要格式
- Layer 3 Retrieval：Context Builder 需要基于多阶段 Retrieval 的结果
