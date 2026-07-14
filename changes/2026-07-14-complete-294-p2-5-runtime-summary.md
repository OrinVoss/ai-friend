# 彻底完成 #294 P2-5：Runtime 负责情绪摘要，Prompt Builder 只收轻量对象

## 问题

`#294` P2-5 要求"Emotion/Memory 应交给 Runtime State，Prompt 逐渐变轻"。

- Memory 部分：之前 #160 已实现 `memory_context_summary`，Agent 1 把格式化的关系/记忆摘要直接传给 Agent 3，基本符合 P2-5。
- Emotion 部分：前一次修改只把情绪格式化逻辑下沉到 `EmotionalState.to_prompt_summary()`，`build_system_prompt()` 的调用方仍传入完整 `EmotionalState` 对象，prompt builder 内部再自己转摘要，没有真正解耦。

本次彻底完成 P2-5 的 Emotion 部分。

## 改动

### 1. Runtime 调用方生成情绪摘要

`core/message_handler.py`、`core/cli_controller.py`、`core/inner_drive.py` 在调用 prompt builder 前，先调用 `emotion.to_prompt_summary()`，只把轻量摘要字典传进去：

- `MessageHandler.handle_proactive()`
- `MessageHandler.handle_explore()`
- `MessageHandler._run_agent3()`
- `CLIController._on_think()`
- `InnerDriveAgent.assess()`
- `InnerDriveAgent.review()`
- `InnerDriveAgent.re_decide()`
- `InnerDriveAgent.assess_agent3_intent()`
- `InnerDriveAgent.assess_proactive()`

### 2. Prompt builder 接收 `emotion_summary`

`prompts/system.py`：

- `build_system_prompt()` 新增 `emotion_summary: dict | None = None` 参数，`_build_emotion_block` 优先使用摘要，否则回退到 `emotion.to_prompt_summary()`。
- `build_inner_drive_prompt()` 新增 `emotion_summary` 参数，`_build_inner_emotion_block` 优先使用摘要。
- `build_inner_drive_proactive_prompt()` 新增 `emotion_summary` 参数，情绪状态描述改为从摘要读取。
- `_build_emotion_block` / `_build_inner_emotion_block` 签名改为接收 `(emotion_summary=None, emotion=None)`，保持向后兼容。

### 3. 摘要自包含

`models/personality.py`：

- `EmotionalState.to_prompt_summary()` 返回的字典补充 `valence` / `arousal` 数值维度，使内驱 prompt 也能完全基于摘要渲染，无需再访问完整 `EmotionalState` 对象。

### 4. 测试

- `tests/test_prompt_instructions.py`：
  - 验证 `build_system_prompt()` 传入 `emotion_summary` 与传入完整 `EmotionalState` 渲染结果一致。
  - 验证 `build_inner_drive_prompt()` 传入 `emotion_summary` 与传入完整 `EmotionalState` 渲染结果一致。
  - 验证 `_build_emotion_block()` 在缺少 emotion/summary 时抛出 `ValueError`。
  - 验证 `to_prompt_summary()` 返回结构包含 `valence` / `arousal`。
- `tests/test_inner_drive.py`：给 TestAssess / TestAssessProactive 的 mock emotion 补充 `to_prompt_summary.return_value`，修复因 Runtime 主动调用该方法导致的 `MagicMock.__format__` TypeError。

### 5. 文档

- `doc/known-issues.md`：更新 `#294` 小节，将 P2-5 标记为已完成。

## 验证

```bash
python -m pytest tests/test_prompt_instructions.py tests/test_conversation_examples.py tests/test_message_handler.py tests/test_inner_drive.py tests/test_agent_proactive.py -v
# 75 passed
```

> 注：全量测试时 `tests/test_repository.py` 会卡死，详见 `changes/2026-07-14-fix-test-repository-hang.md`。

## 相关文件

- `prompts/system.py`
- `models/personality.py`
- `core/message_handler.py`
- `core/cli_controller.py`
- `core/inner_drive.py`
- `tests/test_prompt_instructions.py`
- `tests/test_inner_drive.py`
- `doc/known-issues.md`
- `changes/2026-07-14-complete-294-p2-5-runtime-summary.md`
