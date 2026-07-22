# 重构：MessageHandler God Object 拆分（990 → 838 行 + 3 个新模块）

日期：2026-07-22

## 背景

`core/message_handler.py` 长到 990 行、25+ 方法，塞着四种职责（#293 当年预警过，近两周又塞入 CognitiveState 装配、注册表变体、历史预算、care 回馈）。

## 拆分（纯机械搬移 + 薄委托，行为零变化）

| 新模块 | 内容 | 行数 |
|---|---|---|
| `core/agent_wiring.py` | `AgentWiring`：懒加载装配（InnerDrive/ToolAgent/MemoryAgent/两种 registry 及其缓存） | 145 |
| `core/message_builder.py` | `build_messages()`：prompt 消息数组构建（去重/is_tool_claim/sleep/error_fallback/舞台指示过滤 + 字符与 token 双预算） | 81 |
| `core/proactive_outcome.py` | `match_active_care()` / `evaluate_proactive_outcome()`（L4-6a 主动行为回馈归因） | 50 |
| `core/message_handler.py` | 只剩编排：handle_message/_run_agent2/handle_proactive/handle_explore/_run_agent3/意图回路 + 状态机 + ToolExecutionResult + 输入清洗 | 838 |

## 兼容策略（既有调用方与测试零改动）

- `handler._ensure_inner_drive()` / `_ensure_tool_agent()` / `_ensure_memory_agent()` / `_make_internal_registry()` / `_make_external_registry()` / `_build_messages()` / `_match_active_care()` / `_evaluate_proactive_outcome()` 全部保留为薄委托。
- `handler._inner_drive` / `_tool_agent` / `_memory_agent` 改为读写 property（getter/setter 均转发到 wiring）——测试中 `handler._inner_drive = MagicMock()` 的注入方式不受影响（首轮实现只有 getter，3 个测试暴露后补的 setter）。

## 验证

- 每一步迁移后跑相关测试（test_message_handler / test_agent_proactive / test_memory_agent_integration / test_inner_drive）。
- 全量：`pytest tests --ignore=tests/real_api -q` → **841 passed + 2 skipped** 全绿。

## 备注

主文件剩 838 行但已是单一职责（三层流水线编排）。再往下的可拆点是 `_run_agent2` 的多轮循环（~100 行），但它与 ToolExecutionResult/tracker 耦合紧、状态都在本类，拆出收益低，本次不勉强。
