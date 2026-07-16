# 睡眠持久化根因修复（int(None)）+ CLI 提示符刷屏

统一管线 P3 后的首次实战（CLI 夜间启动）抓到两个真 bug，其中一个还是 `#156` 睡眠消息持久化的真正根因。

## Bug 1：睡眠/醒来消息写不进数据库（#156 根因）

**现场**：启动日志 `insert_turn: turn=0 role=assistant len=16 claim=None` 后立刻 `tick error: int() argument must be ... not 'NoneType'`。

**根因链**：
1. `Agent.add_turn()` 计算 `is_tool_claim=metadata.get("is_tool_claim") if metadata else False`——`metadata={"sleep": True}` 这类**不带该键**的 metadata 使结果为 `None`
2. `repository.insert_turn` 先打日志（所以日志显示 `claim=None`）再执行 `int(is_tool_claim)` → `TypeError: int(None)`，**插入从未发生**
3. 睡眠/醒来消息、睡眠中的回复全部静默丢失；在 RuntimeDriver 里异常还炸掉整个 tick
4. 2026-07-14 的修复把写入路径统一到了 `add_turn()`，等于把所有睡眠持久化都接到了这个雷上——这就是用户报告「#156 好像还没解决」的原因

**修复**：`core/agent.py` 改为 `bool(metadata.get("is_tool_claim")) if metadata else False`。

**加固**：`core/runtime_driver.py` tick 错误日志加 `exc_info=True`——这次只有一行错误消息，靠全链路排查才定位；下次直接有 traceback。

## Bug 2：CLI 提示符刷屏

**现场**：`用户输入: ` 每 0.1 秒打印一次，刷屏数百行，并与打字机输出交错（`Luna: 夜深了.用户输入: ..我睡用户输入: 了，晚安[月亮]`）。

**根因**：P3 重写的输入循环每次轮询都打印提示符（旧状态机有 `_prompt_shown` 标志，只打一次）。

**修复**：恢复 `prompt_shown` 模式——每次等待输入只打一次提示符，收到输入后重置。

## 顺带修复：CLI turn_count 不恢复

现场日志 `turn=0`：CLI 每次启动 `turn_count` 从 0 开始（Web 端 #RS-001 有恢复），导致 `conversation_turns.turn_number` 重复、对话示例轮数计算错误。启动时从 `get_max_turn_number()` 恢复，与 Web 对齐。

## 涉及文件

- `core/agent.py`：is_tool_claim bool 强转
- `core/cli_controller.py`：prompt_shown + turn_count 恢复
- `core/runtime_driver.py`：tick 错误带 traceback
- `tests/test_add_turn_metadata.py`（新建，4 用例）：sleep metadata 不炸且强转为 False、显式 True、无 metadata
- `tests/test_unified_pipeline.py`：新增提示符只打印一次的回归测试
- `doc/known-issues.md`：条目 6 补充根因记录

## 测试

- 新增 5 用例全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **429 passed, 2 skipped**（基线 424）
