# 修复 #294 剩余 Prompt 架构问题

## 问题

`#294` 对 Prompt 架构的审查中，前两次修复（#160 缓存、MessageHandler 重构）已覆盖 P1-1 / P1-2。剩余未修复项：

- **P1-3**：Instruction 分散在 `prompts/system.py` 十几处 builder 函数中。
- **P2-4**：Prompt 与 Runtime 耦合，工具名（`web_fetch`/`music_play` 等）硬编码在 prompt 文本里。
- **P2-5**：Emotion/Memory 应交给 Runtime State，prompt 逐渐变轻。
- **P3-6/7/8**：模板引擎、版本管理、Token Budget。

本次修复 P1-3、P2-4，并对 P2-5 做一小步；P3 因涉及新增依赖和较大架构改动，仍作为后续工作。

## 改动

### 1. 集中管理 Instruction 文本

- 新建 `prompts/instructions.py`：
  - `INNER_DRIVE_INTRO` / `INNER_DRIVE_CHECKLIST` / `INNER_DRIVE_DECISION_PRINCIPLES` / `INNER_DRIVE_TOOL_RULES_HEADER` / `INNER_DRIVE_USER_PRIORITY_RULES` / `INNER_DRIVE_OUTPUT_FORMAT`
  - `TOOL_AGENT_IDENTITY` / `TOOL_AGENT_OUTPUT_FORMAT` / `TOOL_AGENT_RULES`
  - `AGENT3_BASE_INSTRUCTIONS` / `AGENT3_PROACTIVE_INSTRUCTIONS` / `AGENT3_EXPLORE_INSTRUCTIONS`
  - `OUTPUT_RULES_FINAL` / `OUTPUT_RULES_DEFAULT_HEADER` / `OUTPUT_RULES_JSON_EXAMPLE` / `OUTPUT_RULES_INTENT_HEADER` / `OUTPUT_RULES_FOOTER`
- `prompts/system.py` 中的 `_build_inner_drive_instructions_block`、`build_tool_agent_prompt`、`_build_instructions_block`、`_build_output_rules_block` 改为引用上述常量。

### 2. 从 ToolRegistry 动态生成工具规则

- 新建 `prompts/tools_description.py`：
  - `_TOOL_RULES`：工具名 → 中文触发规则映射。
  - `_TOOL_INTENT_ALIASES`：工具名 → Agent 3 主动意图别名映射。
  - `format_tool_rules(registry)`：遍历 registry 生成规则列表。
  - `format_intent_options(registry)`：生成 Agent 3 输出规则中的可选 intent 列表。
- `prompts/system.py`：
  - `_build_inner_drive_instructions_block` 和 `build_tool_agent_prompt` 调用 `format_tool_rules()`。
  - `_build_output_rules_block` 调用 `format_intent_options()`，不再硬编码 `send_notify` / `search_web` 等旧别名。

### 3. 情绪状态摘要化

- `models/personality.py`：
  - `EmotionalState.to_prompt_summary()` 返回 `{dominant_emotion, mood, primary_hint, valence_desc, arousal_desc, behavior}`，将情绪格式化逻辑下沉到 model 层。
- `prompts/system.py`：
  - `_build_emotion_block` 改为调用 `emotion.to_prompt_summary()` 并渲染摘要，保持 prompt 内容不变。

### 4. 测试

- 新建 `tests/test_prompt_instructions.py`：
  - 验证 instructions 常量被正确使用。
  - 验证 `_build_output_rules_block` 不再出现硬编码别名。
  - 验证 `format_tool_rules` / `format_intent_options` 正确过滤未知工具。
  - 验证 `_build_inner_drive_instructions_block` 根据 registry 动态生成规则。
  - 验证 `EmotionalState.to_prompt_summary()` 结构。

### 5. 文档

- `doc/known-issues.md`：在 `#294` 小节添加后续修复记录，标记 P1-3/P2-4 已修复、P2-5 部分修复、P3 仍待处理。

## 验证

```bash
python -m pytest tests/test_prompt_instructions.py tests/test_conversation_examples.py tests/test_prompt_cache.py -v
# 16 passed

python -m pytest tests --ignore=tests/real_api -q
# 386 passed, 2 skipped
```

## 相关文件

- `prompts/instructions.py`（新建）
- `prompts/tools_description.py`（新建）
- `prompts/system.py`
- `models/personality.py`
- `tests/test_prompt_instructions.py`（新建）
- `doc/known-issues.md`
- `changes/2026-07-14-fix-294-prompt-architecture-remaining.md`
