# 统一管线 P2：RuntimeDriver 时间驱动下沉

对应 `doc/refactor/systems/unified-pipeline.md` 的 P2（Runtime 下沉）。睡眠/唤醒/做梦/主动搭话/自由探索的时间循环从 `web/server.py` 抽出，CLI 与 Web 跑同一个节奏——「时间驱动属于引擎，不属于某个前端」。

## 改动

- `core/runtime_driver.py`（新建）
  - `RuntimeDriver(engine, fe)`：`run()` 协程逐行移植原 `_proactive_loop` 语义（睡眠转换 120 tick 冷却、睡眠消息 60 tick 冷却、主动后 12 tick 冷却、idle 30s 底线、chat 2/hr / explore 1/hr 频率限制、Agent 1 LLM 决策 chat/explore/silent）
  - 阻塞调用（decide/handle_proactive/handle_explore）一律走 `run_in_executor`，不冻结事件循环
  - `_emit()`：同步前端直接调用，异步回调（Web 的 WS 发送）自动 await
  - 两种宿主：Web 用 `asyncio.create_task(driver.run())`（取消即停）；CLI 用 `start_in_thread()` 守护线程 + `stop()`（事件通知 + join 3s）
  - tick 长度可实例化覆盖（测试用）
- `core/conversation_engine.py`
  - 新增 Runtime 支撑方法：`is_sleeping` / `idle_seconds` / `touch` / `calculate_proactivity` / `decide_proactive_action` / `check_rate_limit` / `record_rate_limit` / `persist_proactive_message` / `generate_dream`
  - `handle_proactive` / `handle_explore` 的 `fe` 变为可选——驱动传 `fe=None` 拿到文本后自己发事件（这样异步前端才能被 await）
- `web/server.py`
  - 删除 `_proactive_loop`（约 70 行），替换为 `RuntimeDriver` + `_WsProactiveFrontend`（异步 `on_proactive`，经 session 最近活跃的 WS 发 segment+done 帧，多标签页 latest-wins 行为不变）
  - init 处理器改为装配 `ConversationEngine(agent.agent)` + `RuntimeDriver` + `asyncio.create_task`
- `core/cli_controller.py`
  - `_run_shared_pipeline` 启动时 `driver.start_in_thread()`，退出时 `driver.stop()`——开关开启后 CLI 会困、会醒、会做梦、会主动搭话
- `tests/test_runtime_driver.py`（新建，9 用例）：
  - chat/explore 发 on_proactive 且记频率限制；silent 与限流阻塞不发事件
  - 睡眠转换：发消息 + 持久化（metadata sleep）+ 生成梦境；睡着跳过主动性
  - idle 低于底线不触发；异步前端回调被 await；stop 正常结束循环
- `doc/refactor/systems/unified-pipeline.md`：P2 打勾、验收 4 打勾、CLI 无睡眠循环标记已实现
- `README.md` / `doc/architecture.md`：core 18 → 19 模块；README 测试 444 用例 / 35 文件

## 行为说明

- Web 端语义逐行对齐原 `_proactive_loop`，无行为变化
- CLI 端的时间驱动随 `cli_shared_pipeline=true` 生效（与 P1 同一灰度开关）
- 线程安全模型与 Web 现状一致：用户消息与驱动 tick 可能并发进入引擎（Provider/记忆层本就在执行器线程池并发使用）

## 测试

- 新增 9 用例全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **444 passed, 2 skipped**（基线 435）

## 后续（P3 收尾）

- 删 CliController 旧状态机、Web `_split_segments`/`_calc_delay` 死代码（含一处预存 SyntaxWarning）
- 命令层评估统一（`/mood` 等提升为引擎级状态查询）
- `cli_shared_pipeline` 灰度验证后翻默认 true 并移除开关
