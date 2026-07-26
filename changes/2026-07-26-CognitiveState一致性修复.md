# CognitiveState 一致性修复

## 修改文件

- `core/cognitive_state.py`
- `core/inner_drive.py`
- `core/message_handler.py`
- `tests/test_cognitive_state.py`

## 修改原因

同一轮消息中，`CognitiveState.memory_summary` 在 Agent 1 评估后被改写，导致 Agent 1 与 Agent 3 消费同一字段的不同语义；Agent 3 在 `_run_agent3` 中即使已有摘要仍会发起冗余记忆检索；`inner_drive.py` 与 `message_handler.py` 各自实现了 Agent 3 轻量渲染回退逻辑，存在漂移风险。

## 修改内容摘要

1. `core/cognitive_state.py`：
   - 为 `CognitiveState` 增加 docstring，明确"装配后不再修改 memory_summary / memory_confidence / memory_answer"的约定。
   - 新增 `render_memory_light(memory_answer, fallback)` helper，统一封装 `ContextBuilder().build("agent3", ma)` + 空值回退。

2. `core/inner_drive.py`：
   - Agent 1 评估路径改用 `render_memory_light(...)`，删除重复内联渲染逻辑。

3. `core/message_handler.py`：
   - 删除 `state.memory_summary` / `state.memory_confidence` 的改写（原 `message_handler.py:313-314`）。
   - `_run_agent3` 改用 `render_memory_light(state.memory_answer, fallback=state.memory_summary)`；无 `memory_answer` 时回退到 `drive_result.context_summary`。
   - 当 `memory_summary` 非空时，`mem_ctx` 直接取 `a.current_memory_context`，不再调用 `retrieve_for_query`；仅在无摘要时才检索兜底。

4. `tests/test_cognitive_state.py`：
   - 新增 `test_run_agent3_uses_light_render_from_memory_answer`：验证 Agent 3 从 `memory_answer` 渲染轻量视图且 `state.memory_summary` 不被改写。
   - 新增 `test_run_agent3_no_redundant_retrieval_when_summary_present`：验证有摘要时不再二次检索。

## 验证

- `python -m pytest tests/test_cognitive_state.py -q` → 13 passed。
