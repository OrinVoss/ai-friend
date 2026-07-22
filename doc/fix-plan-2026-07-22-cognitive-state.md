# 设计方案：统一运行时状态（CognitiveState / World State）

> 目标：把"四个 Agent 各自重新理解世界"改为"每轮构建一次统一状态，所有模块消费同一份"——即 Review 所说的 Blackboard / Think Once, Use Everywhere。
> 面向执行者：分两个阶段实施，**Phase 1 行为完全不变（纯重构），Phase 2 才改变数据流**。严格按阶段执行与验收。
> 项目：D:/桌面/编程作品/AI朋友，Python 3.12，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **810 passed**，每阶段完成后必须全绿。
> **前置协调**：本方案与 `doc/fix-plan-2026-07-22-reasoning-and-prompt.md`（R1-R5）有少量文件交集（`core/message_handler.py`、`prompts/system.py`）。**先让 R1-R5 落地合并后再开工**，或确认两边改动行不重叠。

---

## 现状与根因

每条用户消息当前的世界理解分散在多处：

| 模块 | 各自做了什么 |
|------|-------------|
| `core/inner_drive.py::assess()` | 检索记忆（`_context_summary_for`，可能走 memory_agent）、推理、决策 |
| `core/message_handler.py::_run_agent3()` | 从 `drive_result.context_summary` 拿记忆摘要（Agent 1 的产出），但情绪/关系/历史自己再读一遍 |
| `prompts/system.py::build_system_prompt()` | 各 block 直读活 `EmotionalState`（M-07 后无快照），慢变块从 cache 或 context_summary |
| `core/agent.py::_process_emotion()` | 又做一次 sentiment 分析（独立 LLM 调用） |
| `memory/consolidation.py` | 批末再做事实/体验/洞察分析 |

已有的雏形（本方案在其上构建，**不是从零开始**）：
- `drive_result.context_summary`——Agent 1 检索一次、Agent 3 复用（#160），这就是"think once"的雏形。
- `EmotionalState.to_prompt_summary()` 仍存在（`models/personality.py`），可直接用。
- `core/inner_drive_state.py`（挂念清单）、`relationship_metrics`、proactivity/sleep 状态文件——各类状态已各有归属，缺的是**每轮消息级别的统一装配点**。

---

## Phase 1：CognitiveState 骨架（行为不变的纯重构）

### 目标

定义统一状态对象并在 `handle_message` 装配，各模块**改从状态读取、但读取的内容与今天完全一致**——用 prompt 等价测试证明零行为变化。

### 改动

**1. 新建 `core/cognitive_state.py`**（约 80 行）：

```python
"""每轮消息的统一运行时状态（World State / Blackboard 雏形）。

每轮用户输入装配一次，Agent 1/2/3 与后处理消费同一份，
不再各自重新检索/理解（Think Once, Use Everywhere）。
"""
from dataclasses import dataclass, field


@dataclass
class CognitiveState:
    # 身份（引用，不拷贝）
    personality_name: str
    # 情绪：轮次开始的快照（dict，来自 EmotionalState.to_prompt_summary()）
    emotion_summary: dict
    # 关系四维
    relationship: dict
    # 记忆：Agent 1 检索一次产出的摘要文本（context_summary），
    # 及 memory_agent 置信度（未走 memory_agent 时为 None）
    memory_summary: str = ""
    memory_confidence: float | None = None
    # 挂念清单浮现（可为空）
    care_surface: list[str] = field(default_factory=list)
    # 决策槽：Agent 1 决策后写入（needs_tools/action/summary）
    pending: dict = field(default_factory=dict)
    # 元信息
    turn_count: int = 0
    idle_seconds: float = 0.0
    is_sleeping: bool = False
```

**2. `core/message_handler.py`**：

- `handle_message` 在 Agent 1 assess **之后**（Phase 1 不动检索位置）装配：

```python
state = CognitiveState(
    personality_name=a.personality.config.name,
    emotion_summary=a.personality.emotion.to_prompt_summary(),
    relationship=a.ltm.get_relationship(),
    memory_summary=drive_result.context_summary or "",
    memory_confidence=getattr(drive_result, "memory_confidence", None),
    care_surface=[...],  # 复用 inner_drive 已有的 surface 结果；没有则空
    turn_count=a.turn_count,
    idle_seconds=...,
    is_sleeping=False,
)
```

- `_run_agent3(...)` 增加可选参数 `state: CognitiveState | None = None`；`memory_summary` 优先从 `state.memory_summary` 取（内容与 `drive_result.context_summary` 相同，仅改数据源）。
- Agent 1 决策结果回写：`state.pending = {"needs_tools": ..., "summary": ...}`，`_run_agent3` 的 `inner_drive_summary` 参数改从 `state.pending` 取。
- 每条消息结束打一行 debug 日志：`[state] mem_chars=N confidence=X care=N pending=...`（可观测性，后续调 Budget 的数据基础）。

**3. 行为不变红线**：

- 不删 `drive_result.context_summary`（Phase 2 才迁移）；`build_system_prompt` 签名不动；prompt 文本逐字节等价。

### 测试（关键）

- **prompt 等价**：同一 mock 装配下，`handle_message` 改造前后 Agent 3 的 system prompt 逐字节一致（仿 M-07 验收时的反向补丁对比法，或直接 mock 两层断言 build_system_prompt 收到的每个参数值不变）。
- `tests/test_cognitive_state.py`（新建）：字段装配正确、pending 回写、`_run_agent3` 优先读 state。

---

## Phase 2：检索前移（真正的 Think Once）

### 目标

记忆检索从 Agent 1 内部前移到状态装配处：**每条用户消息只检索一次**，Agent 1 与 Agent 3 消费同一份；情绪从"各 block 读活对象"改为"轮次开始快照"。

### 改动

**1. 装配点前移**（`handle_message`，Agent 1 assess 之前）：

```python
memory_summary, memory_confidence = self._context_for_state(user_input)
state = CognitiveState(..., memory_summary=memory_summary, ...)
```

- `_context_for_state` 即现 `_context_summary_for`（`core/inner_drive.py:220-235`）的等价物，**上移为 MessageHandler 的方法**（或独立到 `core/cognitive_state.py` 的 builder 函数），内部逻辑不变（use_memory_agent → memory_agent.answer 取 confidence；否则 retriever）。
- `InnerDriveResult` 增加 `memory_confidence: float | None = None`（assess 从 state 透传）。

**2. `InnerDrive.assess(user_input, cognitive_state=None)`**：

- 有 state 时：跳过 `_context_summary_for`，直接用 `state.memory_summary` 喂 `build_inner_drive_prompt` 的 `memory_context_summary`；无 state 时保持现状（兼容旧调用方：review/re_decide/assess_proactive/assess_agent3_intent 本阶段不改）。
- `build_inner_drive_prompt` 的 emotion 输入改用 `state.emotion_summary`——即**重新引入摘要参数**（M-07 删掉的那个），但这次以 CognitiveState 为载体、在轮次开始一次性冻结，语义干净。`build_system_prompt` 同步加回可选 `emotion_summary`（缺省回退活对象，行为兼容）。

**3. 验收不变量**：

- 每条用户消息，`memory_agent.answer` / `retriever.retrieve_for_query` 只被调用一次（mock 计数断言）。
- Agent 1 prompt 与 Agent 3 prompt 中记忆/关系/情绪三块内容一致（同一数据源）。

### 测试

- `tests/test_cognitive_state.py`：单检索断言；state 注入后 assess 不再调 `_context_summary_for`；无 state 兼容路径。
- prompt 等价：同 Phase 1 方法，改造前后 prompt 逐字节一致（emotion 快照在同一时刻取值时）。
- 全量不降级。

---

## Phase 3（后续可选，先不实施）

- Proactive/explore 路径装配 idle 变体 CognitiveState。
- 置信度下传 prompt：`memory_confidence < 0.5` 时 Agent 3 记忆块加"（这些记忆不太确定）"提示。
- ContextBudget：以 state 为数据源做块级 token 预算（Layer 2 遗留项，此时水到渠成）。
- Observation 层：把 `_process_emotion` 的 sentiment 分析结果写入 state，consolidation 复用（消灭第四次分析）。

---

## 执行要求

1. **Phase 1 → 验收 → Phase 2 → 验收**，不要合并实施；Phase 3 不在本次范围。
2. 每阶段：相关测试 + 全量 `python -m pytest tests --ignore=tests/real_api -q` 全绿 + `py_compile` 全模块。
3. 注释跟随周边风格（中文+编号，如 `# WS-1:`）。
4. 完成后写 `changes/2026-07-22-cognitive-state.md`（两阶段分节，附 prompt 等价验证方法）。
5. **不要做的事**：
   - 不要改 `INNER_DRIVE_SCHEMA` / prompt 文案（R1-R5 方案管文案，本方案只管数据流）。
   - 不要动 Agent 2 / ToolAgent（它本就无状态，符合设计）。
   - 不要给 state 加 LLM 调用（装配只用已有数据源，零新增成本）。
   - 不要删除 `EmotionalState.to_prompt_summary()`（本方案依赖它）。
   - 不要碰 consolidation 内部流程（Phase 3 才涉及）。
