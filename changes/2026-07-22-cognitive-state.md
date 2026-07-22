# 变更记录：统一运行时状态（CognitiveState / World State）

> 对应方案：`doc/fix-plan-2026-07-22-cognitive-state.md`
> 实施日期：2026-07-22
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 838 passed, 2 skipped

---

## 总览

把"四个 Agent 各自重新理解世界"改为"每轮用户消息构建一次统一状态，所有模块消费同一份"——即 Review 所说的 Blackboard / Think Once, Use Everywhere。

本次实施范围：

- Phase 1：引入 `CognitiveState` 骨架，行为完全不变的纯重构。
- Phase 2：记忆检索前移到状态装配处，情绪在轮次开始一次性快照，Agent 1/3 消费同一份状态。
- Phase 3：未实施（按方案留到后续）。

---

## Phase 1：CognitiveState 骨架（行为不变）

### 改动文件

1. **`core/cognitive_state.py`**（新建）
   - 定义 `CognitiveState` dataclass：
     - `personality_name` / `emotion_summary` / `relationship`
     - `memory_summary` / `memory_confidence` / `memory_answer`
     - `care_surface` / `pending` / `turn_count` / `idle_seconds` / `is_sleeping`
   - `memory_answer` 字段在方案之外额外加入：保留原始 `MemoryAnswer`，使 Agent 1 与 Agent 3 可以按不同 profile（full / light）渲染同一份证据，避免 prompt 失真。

2. **`core/message_handler.py`**
   - `handle_message` 在 Agent 1 `assess` 之后装配 `CognitiveState`。
   - `_run_agent3` 增加可选 `state` 参数：
     - `memory_context_summary` 优先从 `state.memory_summary` 读取。
     - `inner_drive_summary` 优先从当前 `drive_result.summary` 读取，无 `drive_result` 时回退 `state.pending["summary"]`。
   - 每条消息结束输出 `[state]` debug 日志，作为后续 ContextBudget / 可观测性的数据基础。
   - 新增辅助方法：`_idle_seconds()`、`_relationship_snapshot()`。

### 验收

- 全量测试：`python -m pytest tests --ignore=tests/real_api -q` → 834 passed（新增 7 个测试）。
- `py_compile` 全模块通过。
- Prompt 等价：
  - `tests/test_cognitive_state.py::TestRunAgent3StateDataSource::test_run_agent3_prompt_equivalence_state_vs_drive_result`
    验证同一组数据下，`state` 路径与旧 `drive_result.context_summary` 路径传入 `build_system_prompt` 的关键字段完全一致。

---

## Phase 2：检索前移（真正的 Think Once）

### 改动文件

1. **`core/message_handler.py`**
   - 新增 `_context_for_state(user_input)`：
     - 在 Agent 1 `assess` 之前调用，保证每条用户消息只检索一次记忆。
     - 返回 `(summary, confidence, raw_answer)`；`summary` 是 Agent 1 使用的完整形态，`raw_answer` 用于 Agent 3 轻量渲染。
   - `handle_message` 装配点前移到 `assess` 之前，把 `CognitiveState` 注入 `InnerDriveAgent.assess()`。
   - `assess` 结束后，把 `context_summary`（含挂念浮现等后处理）回写到 `state.memory_summary`。

2. **`core/inner_drive.py`**
   - `InnerDriveResult` 新增 `memory_confidence: float | None = None`。
   - `InnerDriveAgent.assess(user_input, cognitive_state=None)`：
     - 有 `state` 时跳过 `_context_summary_for`，直接用 `state.memory_summary`。
     - 情绪使用 `state.emotion_summary` 快照。
     - 仍保留无 `state` 时的旧路径，兼容 `review` / `re_decide` / `assess_proactive` / `assess_agent3_intent`。
   - 挂念浮现 `_surface_care_for` 仍由 Agent 1 处理（轻量向量操作，不新增 LLM 成本）。

3. **`prompts/system.py`**
   - `build_inner_drive_prompt` 增加可选 `emotion_summary` 参数；缺省时回退活 `EmotionalState`。
   - `build_system_prompt` 增加可选 `emotion_summary` 参数；主情绪块使用快照，怨恨/事件/梦境块仍读活对象（这些状态不在快照中）。
   - 新增 `_build_inner_emotion_block_from_summary` 与 `_build_emotion_block_from_summary`，缺失字段防御性回退，避免测试 mock 不完整时崩溃。

### 验收

- 全量测试：`python -m pytest tests --ignore=tests/real_api -q` → 838 passed, 2 skipped（新增 4 个 Phase 2 测试）。
- `py_compile` 全模块通过。
- 单检索断言：
  - `tests/test_cognitive_state.py::TestPhase2RetrievalFront::test_handle_message_retrieves_memory_once`
    验证 `handle_message` 中 `retriever.retrieve_for_query` 只被调用一次。
  - `tests/test_cognitive_state.py::TestPhase2RetrievalFront::test_assess_with_state_skips_internal_retrieval`
    验证注入 `state` 后 `assess` 不再调用 `_context_summary_for`。
- Prompt 等价：
  - Phase 1 的等价测试仍然通过。
  - `memory_answer` 机制保证 Agent 1 仍看到完整记忆块（含置信度标注），Agent 3 仍看到轻量块，原有 `test_context_summary_is_light_for_agent3` 等用例不降级。

---

## Prompt 等价验证方法

1. 在 `tests/test_cognitive_state.py` 中构造同样的记忆摘要与 inner_drive_summary。
2. 分别走两条路径调用 `MessageHandler._run_agent3`：
   - `state` 路径：`state.memory_summary = summary`，`state.pending["summary"] = inner_summary`。
   - 旧路径：`InnerDriveResult(context_summary=summary, summary=inner_summary)`，不传入 `state`。
3. Mock `build_system_prompt`，比较两次调用 kwargs 中的 `memory_context_summary` 与 `inner_drive_summary` 是否完全一致。
4. 生产环境可额外对比同一条消息改造前后 `build_system_prompt` 返回字符串的 diff。

---

## 生产观察点

- `handle_message` 单条消息内是否只出现一次 `[retrieval_pipeline] retrieve: ...`。
- `[state] mem_chars=... confidence=...` debug 日志是否稳定输出。
- Agent 1 reasoning 中是否不再出现因重复检索导致的上下文矛盾。

---

## 未做事项（按方案保留）

- Phase 3 的 proactive/explore idle 状态变体。
- `memory_confidence < 0.5` 时向 Agent 3 注入"记忆不确定"提示。
- 基于 `CognitiveState` 的 ContextBudget 块级 token 预算。
- 把 `_process_emotion` 的 sentiment 分析结果写入 state。
