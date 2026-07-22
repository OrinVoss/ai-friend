# 重构：core/ 同域小模块归并（proactive_outcome、memory_context_provider）

日期：2026-07-22

## 内容

上周 God Object 拆分产生的两个同域小模块归并回所属域：

1. **`core/proactive_outcome.py`（50 行）→ `core/proactivity.py`**：`match_active_care()` / `evaluate_proactive_outcome()`（L4-6a 主动行为回馈归因）与 ProactivityManager 同属"主动行为"域。`message_handler.py` 的委托改为从 `core.proactivity` 导入。
2. **`core/memory_context_provider.py`（68 行）→ `core/cognitive_state.py`**：`MemoryContextProvider` 正是往 `CognitiveState.memory_summary` 填内容的装配器，同属"轮次状态"域，合并后概念更完整。`core/inner_drive.py` 的 import 同步更新。

core/ 模块数 26 → 24（不含 `__init__.py` 口径 25 → 23）。

## 未合并（记录在案的决策）

- `message_builder.py` ↔ `context_manager.py`：构建消息 vs token 账本，分开说得过去（可选项 3，未拍板）。
- `personality_manager/validator` ↔ `personality.py`：职责标签不同（可选项 4，未拍板）。
- `session_factory` ↔ `agent_wiring`、`runtime_driver` ↔ `conversation_engine`、`embedding_server` ↔ `provider`：层次/域不同，分开是对的。

## 验证

- 全量：`pytest tests --ignore=tests/real_api -q` → **841 passed + 2 skipped** 全绿（薄委托全部未动，无测试修改）。
