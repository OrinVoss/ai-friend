# 统一管线 P3：收尾——删死代码、开关移除、文档对齐

对应 `doc/refactor/systems/unified-pipeline.md` 的 P3。统一管线四期至此全部完成：CLI 与 Web 是同一个引擎的两个前端，新管线成为唯一路径。

## 改动

- `core/cli_controller.py`（重写，396 → 230 行）
  - 删除旧内联 ReAct 状态机（`_on_idle/_on_perceive/_on_think/_on_act/_finish_react_response/_on_reflect` 及配套的 `_ensure_inner_drive`/`_ensure_tool_agent`/`_make_internal_registry`/`_tool_records`/`_inner_drive_result`）
  - `run()` 即统一管线输入循环（原 `_run_shared_pipeline`），不再分支
  - 保留：`_on_boot` / `_on_shutdown` / `_handle_command` / `_CliFrontend`
  - **补 `_CliFrontend.on_proactive`**：P2 接入 RuntimeDriver 时漏了它，睡眠/主动/梦境消息在 CLI 会被基类 no-op 吞掉——本次修复
- `web/server.py`
  - 删除死代码 `_split_segments`（6 级分段）与 `_calc_delay`（含一处预存 SyntaxWarning，随之清除）；分段推送若要回归，git 历史可查
  - 清理随之不再使用的 `import random` / `import re`
- `config.py` / `config.example.json` / `doc/config-reference.md`
  - 移除 `cli_shared_pipeline` 开关（P1 的灰度通道完成使命）
- `tests/test_segmentation.py`（删除，18 用例——只覆盖被删的死代码）
- `tests/test_unified_pipeline.py`：删除 `TestCliSharedPipelineSwitch`（2 用例——开关已不存在）
- `tests/test_cli_controller.py`：保持不变（命令/启动/reset 测试与新控制器兼容，全部通过）
- 文档对齐：`README.md`（驱动/输出行、424 用例 34 文件、cli_controller 描述、统一管线特性条）、`doc/architecture.md`（状态机图替换为统一管线图）、`doc/message-flow.md`（编排器、引擎与编排状态节、CLI/Web 对比表、§5 描述）、`doc/startup-flow.md`（CLI/Web 对比表）、`doc/refactor/systems/unified-pipeline.md`（P3 打勾、状态行、开关移除注记）、`doc/refactor/systems/cli.md`（开关相关计划标注已落地）

## 命令层评估结论（P3 任务项）

`/mood` `/status` 等状态查询命令保持 CLI 本地实现；引擎侧已提供 `get_emotion_summary()` / `get_relationship()`（P1），Web 端或其他前端需要状态查询时直接调引擎，无需再把 CLI 命令提升为引擎命令。

## 测试

- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **424 passed, 2 skipped**（基线 444 − 18 分段 − 2 开关）
- `py_compile` 与 import 冒烟通过；原 `web/server.py` 死代码 SyntaxWarning 已清除

## 统一管线最终状态

| 期 | 内容 | 状态 |
|----|------|------|
| P0 | SessionFactory 共享装配、per-session Repository | ✅ |
| P1 | ConversationEngine + Frontend 事件接口 | ✅ |
| P2 | RuntimeDriver 时间驱动共享 | ✅ |
| P3 | 死代码清理、开关移除、文档对齐 | ✅ |

## 后续建议

- 日常使用 CLI + Web 几天，观察情绪/睡眠/主动行为两端一致性（统一管线后的首次全量实战）
- 下一大件：Memory Agent P0（`doc/refactor/layer1-memory/memory-agent.md`）
