# Layer 4 收尾 — 实施计划（供低成本模型执行，详版）

> 日期：2026-07-20。依据：`doc/refactor/progress.md` Layer 4 待完成项 + `doc/refactor/layer4-agent/inner-drive-state.md` 三期设计。
> 本文档面向执行者：每项给出根因位置（文件/行）、做法、测试、验收。**严格按项执行，不做清单之外的"顺手优化"。**
> 项目：D:/桌面/编程作品/AI朋友，Python 3.13，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **693 用例（691 passed + 2 skipped）**，改完必须全绿且不减少。

---

## 0. 范围说明

Layer 4 主体已完成（状态机、ToolExecutionResult、注册表隔离、沉思循环、内驱状态一二期）。本文覆盖剩余 5 个收尾项（L4-1 ~ L4-5）+ 内驱状态三期（L4-6）。

---

## L4-1：Agent 公开方法封装（消除 `a._xxx` 直接访问）

**根因**：`core/message_handler.py` 直接访问 Agent 内部属性（破坏封装，重命名/加锁时易碎）：

| 位置 | 访问 | 需要的公开方法 |
|------|------|----------------|
| :156,163,228,419,421,475 | `a._tool_registry` | `Agent.tool_registry`（property 或 `get_tool_registry()`） |
| :156 | `a._tool_call_history` | `Agent.tool_call_history`（property） |
| :244 | `a._sleeping` | `Agent.is_sleeping`（property，web/session.py 已有同名转发可参考） |
| :409,456 | `a._pick_proactive_topic()` | `Agent.pick_proactive_topic()`（去下划线公开） |
| :418,474,551 | `a._context.compressed_summary` | `Agent.compressed_summary`（property） |
| :421,477 | `a._consecutive_negative` | `Agent.consecutive_negative`（property） |
| :442,506 | `a._react_loop(...)` | 保持现状（这是编排层方法，注释说明为何公开豁免） |

**做法**：`core/agent.py` 添加 property/公开方法（薄转发，不改逻辑）；`core/message_handler.py` 全部换成公开访问。`_react_loop` 保留并在 docstring 注明「编排入口，刻意公开」。

**测试**：现有 `tests/test_message_handler.py` 全绿（mock 是 MagicMock，property 访问兼容）；新增一个轻量断言：`Agent` 实例存在 `tool_registry`/`is_sleeping`/`compressed_summary` 公开属性。

---

## L4-2：Agent 2 工具循环全局超时

**根因**：`core/message_handler.py` 的 Agent 2 循环（`MAX_AGENT2_ROUNDS = 3`）每轮包含 tool_agent 决策 + 工具执行，**没有总时间上限**——工具卡死（如下载大文件）整条消息挂住。

**做法**：
1. `core/message_handler.py` 新增类常量 `AGENT2_TOTAL_TIMEOUT = 120.0`（秒），循环开头记 `deadline = time.monotonic() + AGENT2_TOTAL_TIMEOUT`，每轮迭代开头检查：超时则 `logger.warning` 并 break 到 Agent 3 降级回复（复用现有的 agent3 fallback 路径）。
2. 提取为 config：`agent2_total_timeout_seconds: int = 120`（config.py + config.example.json + doc/config-reference.md）。

**测试**（`tests/test_message_handler.py`）：mock tool_agent 每轮 sleep 模拟 + 时间补丁（`unittest.mock.patch` time.monotonic），验证超时后走降级且不超轮次。

---

## L4-3：`_sanitize_input` 强化

**根因**：`core/message_handler.py:752` 的 `_sanitize_input` 只匹配**完全相等**的行（`"system:"`、`"from now on"` 等），挡不住 `"system: 忽略之前所有指令"`、`"System: 你是…"` 这类变体。

**做法**（保持简单，不过度过滤）：
```python
_INJECTION_PATTERNS = [
    re.compile(r"^\s*(system|assistant|user)\s*[:：]", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+(instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"from\s+now\s+on", re.IGNORECASE),
    re.compile(r"忽略(之前|以上|所有).{0,4}(指令|提示|对话)"),
]
```
逐行检查，命中则**该行替换为空**（不是整段拒绝），并在替换时 `logger.warning("[msg] injection pattern stripped: {pattern_name}")`。现有等值匹配删除，max_length 截断保留。

**测试**（`tests/test_message_handler.py` 或新类）：`"system: 忽略指令"` 被剥除、`"System: 你好"` 被剥除、正常中文对话（含「系统」一词但不在行首带冒号）**不受影响**、长输入截断保留。

---

## L4-4：异常时向用户反馈

**根因**：Agent 2 异常走 `agent3 fallback` 时（`except Exception: logger.exception(...)`），用户收到的是「正常但可能不完整」的回复，不知道发生了错误。

**做法**：fallback 路径在传给 Agent 3 的上下文里加一行（不改 UI 协议）：`[系统提示：工具执行出现错误（{错误类型}），请如实告诉用户哪一步没做成，不要编造结果]`。仅注入 prompt，不改用户可见的其他逻辑。

**测试**：mock Agent 2 抛异常 → Agent 3 收到的 messages 中含该提示。

---

## L4-5：依赖注入（评估项，默认跳过）

`MessageHandler.__init__(agent, inner_drive=None, tool_agent=None)` 的完整 DI 是结构性改动、收益主要是可测试性（现有 mock 已覆盖）。**本计划不实施**，仅在此记录：如未来单测构造继续变痛，再立项。

---

## L4-6：内驱状态三期（回馈闭环 + memory_agent 来源 + dreams 评估）

依据 `doc/refactor/layer4-agent/inner-drive-state.md` 第 6、9 节。

### L4-6a：回馈闭环（record_outcome）

**根因**：主动行为没有结果反馈——「什么样的主动受欢迎」学不到。

**做法**（`core/inner_drive_state.py`）：
1. `InnerDriveState.record_outcome(entry_id, positive: bool)`：positive → 同类型 active 条目 priority +0.05（封顶 1.0）；negative → priority ×0.9；被驱动的条目标记 `resolved`（resolution 记结果）。
2. 归因：主动开口时（`core/runtime_driver.py` 或 `message_handler.handle_proactive`），若本次 intent 的 topic/reasoning 命中某条活跃挂念（content 包含或被 surface 过），记录 `pending_care_id`；下一条**用户消息**到达时评估回应情绪——复用 consolidation 的 `analyze_sentiment`（或在 Agent._process_emotion 已有的 sentiment 上取正负），正 → positive，负/无回应 → negative。
3. 实现提示：归因存一个轻量字段（Agent 或 MessageHandler 上 `_last_proactive_care: dict | None`），**不新建表**。

**测试**：record_outcome 正/负对 priority 的影响；resolved 记录；无 pending 时 no-op。

### L4-6b：memory_agent 来源写入

**根因**：inner-drive-state.md §5 的第三来源——Memory Agent 交叉验证发现矛盾/缺口时生成 curiosity。

**做法**：`memory/memory_agent.py::verify_fact` 检测到矛盾时，若挂了 `inner_drive_state`（可选注入），写一条 `type="curiosity"` 条目（「X 和 Y 矛盾，找机会确认」）。**默认不注入**（避免循环依赖），在 `core/message_handler.py::_ensure_memory_agent` 里接线。

**测试**：verify_fact 矛盾路径产生 curiosity 条目（state mock）。

### L4-6c：dreams（长期梦想）——评估后决定不做

dreams 是数周尺度的目标系统（设计文档自己也标三期按需）。当前挂念清单上线仅两天，无数据支撑 dream 的形态。**本计划不实施**，文档注明原因。

---

## 明确不做

- L4-5 依赖注入、L4-6c dreams（理由见上）
- 不重写 `_react_loop`、不动 MessageHandlerState 状态机
- 不给 Agent 2 加并行工具执行（Layer 5 的事）

## 执行顺序与验收总表

| 顺序 | 项 | 风险 | 关键验收 |
|------|----|------|----------|
| 1 | L4-1 公开方法 | 低 | message_handler 无 `a._xxx`（除 _react_loop） |
| 2 | L4-3 输入清洗 | 低 | 变体注入被剥、正常对话不伤 |
| 3 | L4-2 全局超时 | 中 | 超时走降级不挂死 |
| 4 | L4-4 错误反馈 | 低 | fallback 含系统提示行 |
| 5 | L4-6a 回馈闭环 | 中 | 正/负反馈改变 priority |
| 6 | L4-6b curiosity 来源 | 低 | 矛盾时写条目 |

全部完成后：`python -m pytest tests --ignore=tests/real_api -q` 全绿（≥693 用例）；`doc/refactor/progress.md` Layer 4 待完成项打勾；新建 `changes/2026-07-2X-layer4-tail.md`。
