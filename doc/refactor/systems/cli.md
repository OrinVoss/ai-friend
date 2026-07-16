# CLI 系统增强方案

> 目标：把 CLI 从「能跑通的备用入口」升级为与 Web 同人格、同能力的一线界面——对话走同一条管线，情绪会动、到点会睡、输出干净、输入像样。
> 状态：设计文档，待实现。
> 归属：系统级增强，新增于 `enhancement-overview.md` 总览表之外（CLI 不属于六层中的任何一层，它是自我系统的「呈现层」）。阅读本文前建议先读 `../self-system.md`。

---

## 1. 背景与目标

CLI 是最早的界面（`main.py` → `core/cli_controller.py` 状态机），Web 是后来的（`web/server.py` → `core/message_handler.py`）。两条路径**各自实现了完整的对话管线**，新功能（睡眠、内驱主动、prompt 缓存、结构化 intent）全部只进了 Web 路径，CLI 停在旧形态。

自我系统（`../self-system.md`）定义的八条状态连接中，至少有三条在 CLI 是断的：行动→情绪（#5）、睡眠循环表现层、独处循环的内驱决策。本文档的目标不是给 CLI 堆功能，而是**消除双轨，让 CLI 复用同一份人格逻辑**，再把终端特有的输入/输出体验补齐。

---

## 2. 现状盘点

### 2.1 组件现状

| 组件 | 现状 |
|------|------|
| 入口 | `main.py`：初始化存储/人格/记忆/工具，`agent.run()` → `CliController.run()` |
| 状态机 | `core/cli_controller.py`：BOOT → IDLE → PERCEIVE → THINK → ACT → REFLECT → SHUTDOWN，内联实现 ReAct 循环（不走 `agent._react_loop`） |
| 输入 | `ui/cli.py` `NonBlockingInputReader`：后台 daemon 线程裸 `sys.stdin.readline()` 逐行入队 |
| 显示 | `ui/display.py` `DisplayEngine`：打字机 + CJK 感知换行（DP-002/004/010）；第一轮回复走裸流式直接 print |
| 命令 | 7 个：/exit /quit /save /mood /status /forget /help（`ui/cli.py:62-74`，处理在 `cli_controller.py:358-396`） |
| 主动消息 | IDLE 超阈值后随机打分 → `_pick_proactive_topic()` → THINK（`cli_controller.py:111-116`） |

### 2.2 CLI / Web 对齐度

| 能力 | Web | CLI |
|------|-----|-----|
| 对话管线 | `MessageHandler` + `agent._react_loop` | `CliController` 内联 ReAct（另一份实现） |
| 情绪更新 | 每轮 `_process_emotion`（`agent.py:246`） | **无** |
| 睡眠/做梦 | 入睡/醒来消息 + 睡觉回复 + 做梦（`web/server.py:394-415`、`message_handler.py:185-198`） | **无** |
| 主动决策 | 内驱 intent（chat/explore/silent）+ rate limit（`web/server.py:419-451`） | 随机打分 + 话题模板，无限流 |
| 输入清洗 | `_sanitize_input`：注入清洗 + 10000 字符上限（`message_handler.py:96,673-693`） | 无 |
| Prompt 缓存 | `build_system_prompt(prompt_cache=...)`（`message_handler.py:470-490`） | 调用缺该参数（`cli_controller.py:209-219`） |
| Agent 3 结构化 intent | `_handle_agent3_intent`（`message_handler.py:518-530`） | 无 |
| 可观测性 | /monitor 监控页、/api/logs 日志流、导出（`web/server.py:244,258,321`） | 无入口（monitor 在记录但看不了） |
| 角色/会话 | /api/roles、/api/sessions（`web/server.py:217,235`） | 单角色，启动时定死 |

---

## 3. 问题清单（按严重度排序）

### P0-1 双轨管线是所有漂移的根因

`CliController` 与 `MessageHandler` 是同一条对话管线的两份实现：连辅助方法都成对重复（`_ensure_inner_drive` / `_ensure_tool_agent` / `_make_internal_registry`，`cli_controller.py:26-51` vs `message_handler.py:119-164`）。后果是结构性的——**每加一个新功能都要记得改两处，实际上只改了 Web 那处**。证据（全部只存在于 Web 路径）：

- Agent 3 JSON intent 处理：`message_handler.py:498-530`，CLI 无对应物
- prompt 缓存等参数：`message_handler.py:470-490` 的 `build_system_prompt` 调用比 `cli_controller.py:209-219` 多出 `tool_call_history` / `prompt_cache` / `session_id` / `final_response` 等 7 个参数——Layer 2 的 prompt 分层缓存（`../layer2-prompt/README.md`）在 CLI 根本没接上
- 回复落库少了 #130 的 `is_tool_claim` 检测：Web 走 `add_turn`（`agent.py:108-115,238-241`），CLI 直接 `insert_turn_sync`（`cli_controller.py:322`）

以下 P0-2 / P0-4 / P1-1 全是它的症状。

### P0-2 CLI 对话永不更新情绪——「心情」是冻结的

`apply_emotional_shift` 全项目只有一个调用点：`agent.py:273`，位于 `_process_emotion`（`agent.py:249-290`）内；`_process_emotion` 只被 `_react_loop`（`agent.py:246`）调用；`_react_loop` 只被 `MessageHandler`（`message_handler.py:369,432,495`）调用。CLI 状态机整条链路（`cli_controller.py:138-345`）没有任何情绪更新。连锁后果：

- `/mood`（`cli_controller.py:370-372`）永远显示同一个值，形同虚设
- 情绪 → prompt 摘要（`cli_controller.py:208`）、情绪 → 回复长度（`agent.py:92-102`）、情绪 → 主动打分（`core/proactivity.py:24-48`）全部吃着同一个冻结值
- 破防计数 `consecutive_negative` 在 CLI 永不增减（known-issues #79 已记「CLI 路径破防/情感分析重复调用修复」未闭环）
- 自我系统连接 #5「行动 → 情绪」在 CLI 断裂（`../self-system.md` 第 5 节）

### P0-3 流式输出把原始 `<tool_call>` / `<think>` 标记喷给用户

`cli_controller.py:262-269`：`on_token` 对每个 token 无条件 `print`。而工具调用是内联在回复文本里的 `<tool_call>{...}</tool_call>` 或裸 JSON，`<think>` 块同理（`core/dispatcher.py:12-13`），清理发生在**流结束之后**（`cli_controller.py:281` 的 `parse_tool_calls`）。模型一旦决定调工具，用户先眼看一屏 JSON 滚过，然后再看到「执行 N 个工具...」（`cli_controller.py:299-300`）——最破坏沉浸感的一幕恰恰发生在工具这个最重沉浸的功能上。

### P0-4 CLI 没有睡眠循环——它 24 小时醒着

`SleepManager` 在 Agent 构造时就初始化了（`agent.py:67-71`），但 `CliController` 全文无一次 `sleep` / `dream` 调用（grep 可证）。Web 端有完整闭环：入睡/醒来消息并落库、睡着时给用户「睡觉回复」、醒后做梦（`web/server.py:394-415`、`message_handler.py:185-198`）。CLI 里凌晨三点它依然秒回、依然会主动开口。`../self-system.md` 第 4 节宣称的睡眠「表现层已有」，在 CLI 不成立。

### P1-1 主动决策停在旧路径：无内驱、无速率限制

`cli_controller.py:111-116`：随机打分通过就直接 `_pick_proactive_topic()`（`core/proactivity.py:68-98`，经历/事实/时间段模板）进 THINK。Web 路径是打分 → `decide_proactive_action` 内驱 intent（chat/explore/silent）→ `check_rate_limit`（`web/server.py:419-451`）。`check_rate_limit` / `record_rate_limit` 在 CLI 路径零调用（grep 仅命中 `web/`）。后果：CLI 主动开口没有 30 分钟/1 小时的冷却，也没有 explore/silent 的概念——`../layer4-agent/proactive-think-loop.md` 落地时 CLI 无法自然接入。且打分输入的情绪是冻结值（P0-2 连锁）。

### P1-2 输入体验裸奔

- **无命令历史、无行编辑**：`ui/cli.py:31-36` 后台线程裸 `sys.stdin.readline()`，不经过 readline，上箭头调不出上一条
- **粘贴多行 = 多条独立消息**：reader 逐行入队（`ui/cli.py:36`），`_on_idle` 每轮取一行直接走完整 PERCEIVE→REFLECT（`cli_controller.py:106-110`）——粘贴 5 行触发 5 轮完整回复，烧 5 倍 token
- **Ctrl+C 只能退出整个程序**：`cli_controller.py:79-80` 把 KeyboardInterrupt 直接翻译成 SHUTDOWN；生成到一半想「打断它说别的」做不到
- **无输入清洗与长度上限**：Web 有 `_sanitize_input`（注入模式清洗 + 10000 字符截断，`message_handler.py:673-693`），CLI 的原始输入直接进短期记忆和 prompt

### P1-3 主动消息与用户输入交错，无重绘

提示符「用户输入： 」以 `end=""` 打印后（`cli_controller.py:104`），用户打字途中若触发主动消息，输出直接插在同一行，打了一半的内容被覆盖且不重绘。`_prompt_shown` 标志（`agent.py:80`）只管「要不要打印提示符」，不管输出穿插。这是行式裸输入 + 异步输出的结构性冲突，治本要靠输入层重做（P2-1 依赖项）。

### P2-1 显示路径不一致

- 第一轮回复：裸流式，不经过 `_word_wrap`——CJK 换行逻辑（`ui/display.py:92-126`）对它无效，长行在终端边缘硬折
- 第二轮起（工具调用后）：`stream=False`（`cli_controller.py:246-250`），改由 `_finish_react_response` 用打字机 `respond()` 显示（`cli_controller.py:319-320`）——同一轮对话里两种节奏
- `show_thinking()` 的 `" ..."`（`ui/display.py:77-78`）靠 `\r` 覆盖（`cli_controller.py:265`）但不清行，名字前缀可见宽度不足 4 列时会残留字符

### P2-2 可观测性为零，命令面太窄

`core/monitor` 在 CLI 路径也在记录 LLM 调用（`main.py:60`），但 CLI 没有任何查看入口；Web 有监控页（`web/server.py:321-326`）、日志 SSE（`web/server.py:258-296`）、历史查询（`web/server.py:244`）、监控导出 JSON/Markdown（`web/static/monitor.js:190,209`）。CLI 七个命令里没有：对话历史、记忆浏览、LLM 用量、导出、梦境/内驱查看。

### P2-3 Windows 终端兼容无防御

全代码库无任何 VT 模式启用 / 编码兜底（grep `colorama` / `SetConsoleMode` 无命中）。banner 的 `✦`（`ui/cli.py:56`）与大量 ANSI 序列（`ui/cli.py:55-58`、`ui/display.py:82-90`）在现代 Windows Terminal / Win10+ conhost 上正常，但旧 conhost 或输出重定向时无降级方案，可能显示原始转义序列或编码异常。

### P2-4 小代码问题

- `read_line(timeout)` 的 `timeout` 参数被完全忽略（`ui/cli.py:24-29`）
- `NonBlockingInputReader.stop()` 停不掉阻塞在 `readline()` 的线程（`ui/cli.py:21-22,31-36`），仅靠 daemon 属性在进程退出时兜底

---

## 4. 增强方案

### P0：人格真实性速修（小改动、低风险，各自独立可上线）

**1. 流式输出过滤标记（治 P0-3）**

在 `on_token` 回调里加一个**确定性增量状态机**（无 LLM）：累积缓冲中检测 `<tool_call>` / `<think>` / 裸 JSON 起始特征，命中即暂停回显，标签闭合后恢复；流结束后仍由 `parse_tool_calls` 兜底清理。纯 UI 层改动，不动管线。

**2. CLI 补情绪更新（治 P0-2）**

`_finish_react_response` 后调用现成的 `agent._process_emotion()`。注意对齐触发点：`_process_emotion` 内部有 `consolidation_interval` 触发的 consolidate（`agent.py:284-290`），与 `_on_reflect` 现有的 `should_consolidate`（`cli_controller.py:335-339`）不能双触发——保留一处，另一处旁路。配置开关 `cli_emotion_update`（默认开，可一键退回，沿用 `use_observation_fact` 式开关惯例）。

**3. CLI 接睡眠检查（治 P0-4）**

`_on_idle` 里周期检查睡眠状态（`SleepManager.get_sleep_state` 是 async，CLI 同步循环用薄同步包装或定时 `asyncio.run` 轮询，分钟级足够）：入睡/醒来时打印消息并落库，睡着时用户输入走「睡觉回复」分支（行为直接对齐 `message_handler.py:185-198`），醒后触发做梦。行为基准照抄 Web，不重新设计。

### P1：管线收敛——CLI 改为薄 UI 适配层（治 P0-1 及残留症状）

依赖：P0 全部完成（先在旧管线上建立「情绪会动 / 到点会睡 / 输出干净」的行为基准，收敛后逐项对照不回归）。

**4. `CliController` 收敛到 `MessageHandler`**

- 对话处理全部改走 `agent.process_message` / `process_proactive` / `decide_proactive_action`（即 `MessageHandler` 管线），`CliController` 只保留：输入读取、输出渲染（on_token 回调 + 系统提示）、命令分发、状态机外壳
- 一次收敛自动获得：prompt 缓存、输入清洗、`is_tool_claim`、Agent 3 intent、内驱主动决策 + rate limit
- 灰度开关 `cli_shared_pipeline`：默认先关，新旧管线并存一段时间，日志对比同输入下两轮管线行为，确认无回归后默认开，再删旧路径（灰度可回退，与 `../enhancement-overview.md` 第 2 节原则一致）
- 重复方法（`_ensure_inner_drive` 等）随旧路径删除自然去重

**5. 主动循环对齐 Web**

收敛后 CLI 的 IDLE 主动分支改为：打分 → `decide_proactive_action` → intent 分发（chat/explore/silent）→ rate limit 记录，与 `web/server.py:419-451` 同一语义。接入 `../layer4-agent/proactive-think-loop.md` 时只需在 MessageHandler 一处扩展。

### P2：终端体验与可观测性

依赖：P1 完成（输入/输出重绘要和新管线的回调契约配合，避免在旧外壳上返工）。

**6. 输入层重做（治 P1-2、P1-3）**

- 引入行编辑输入（readline 系或 prompt_toolkit，选型时确认与项目现有依赖不冲突）：命令历史、行内编辑、粘贴多行合并为一条消息
- Ctrl+C 语义改为「中断当前生成，回到提示符」；`/exit` 才是唯一退出路径
- 输出与输入交错时清行—输出—重绘提示符与未竟输入（行编辑库自带重绘能力）

**7. 显示统一（治 P2-1）**

- 流式也过 CJK 感知换行；首轮与后续轮同一节奏（全流式）
- 覆盖式输出一律「`\r` + ANSI EL 清行」再写，消除残留字符

**8. 命令与可观测性补齐（治 P2-2）**

新增最小集合，全部复用已有数据源，不发明新存储：

- `/monitor` — 打印 `core/monitor` 的最近 N 条 LLM 调用摘要（次数/耗时/tokens）
- `/history [n]` — 最近 n 轮对话
- `/export` — 对话历史导出 Markdown 到文件
- `/dream` — 最近一次梦境；`/drive` — 内驱状态摘要（待 `../layer4-agent/inner-drive-state.md` 落地后有数据源，可顺延）

**9. Windows 兜底与小修（治 P2-3、P2-4）**

- 启动时尝试启用 VT 处理（失败则全局降级为无颜色、无 `✦` 的纯文本模式），不引入重依赖
- 修掉 `read_line(timeout)` 死参数与 `stop()` 停不住的线程（P2-1 输入层重做时顺带消化）

---

## 5. 与现有设计的关系

- **自我系统（`../self-system.md`）**：本文档修复连接 #5（行动→情绪）在 CLI 的断裂，补齐睡眠循环表现层，并让独处循环（`../layer4-agent/proactive-think-loop.md`）未来在 CLI 可用。CLI 是三个生命循环的呈现层，不引入新状态、新模块
- **Layer 2 Prompt（`../layer2-prompt/README.md`）**：prompt 缓存已接 Web；P1 管线收敛后 CLI 自动获得，无需单独施工
- **Layer 4 独处循环**：P1-5 的 intent 分发是其接入点；think loop 落地时 CLI 零改动
- **Layer 5 工具（`../layer5-tool/enhancement-plan.md`）**：其 `ToolResult` v2 的 `error_type` 落地后，CLI 的「执行 N 个工具...」提示可升级为具体失败原因，本文档不重复设计
- **Layer 6 角色绑定（`../layer6-personality/README.md`）**：其产品决策落地后，CLI 的「单角色启动时定死」随之解锁；known-issues #81 的「统一启动入口 start.py」是入口层的事，不在本文档范围
- **known-issues**：#79「CLI 路径破防/情感分析重复调用修复」由 P0-2 闭环

---

## 6. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `ui/display.py` | 流式标记过滤状态机、流式 CJK 换行、清行写法、纯文本降级模式 | P0/P2 |
| `core/cli_controller.py` | 补 `_process_emotion` 调用、IDLE 睡眠检查、收敛为薄 UI 适配层、旧管线删除 | P0/P1 |
| `core/sleep_manager.py` | 同步检查包装（薄壳，不改睡眠逻辑） | P0 |
| `ui/cli.py` | 行编辑输入（历史/多行/中断/粘贴合并）、交错重绘、死参数与线程收尾 | P2 |
| `core/agent.py` | `_process_emotion` 的 consolidate 触发点参数化（避免双触发） | P0 |
| `config.py` / `config.example.json` | `cli_emotion_update`、`cli_shared_pipeline` 开关 | P0/P1 |
| `main.py` | VT 启用尝试与降级接线 | P2 |
| `tests/test_cli_controller.py` | 新增覆盖（现仅 8 个命令/boot 测试） | 各期 |

---

## 7. 测试与验收

测试：

1. 流式中含 `<tool_call>` 的回复：终端全程不出现标记文本，工具结果正常执行
2. CLI 对话 3 轮后 `personality.emotion` 有变化；`cli_emotion_update=false` 时行为同现状；consolidate 不双触发
3. 睡眠时间窗内：CLI 打印入睡消息、用户输入得到睡觉回复、不主动开口；跨端一致（Web 睡着的 session，CLI 同 session 也睡）
4. 开关回退：`cli_shared_pipeline` 开/关下，同一输入的最终回复语义一致
5. 粘贴 3 行文本 → 1 条消息、1 轮回复；Ctrl+C 中断生成回到提示符，进程不退出
6. 主动消息 30 分钟内不重复（rate limit 生效）

验收：

- `/mood` 在 CLI 对话后读数变化；凌晨时段 CLI 观察到入睡行为
- 触发工具调用时终端无 JSON/XML 泄漏
- CLI/Web 同 session 交替使用，人格表现（情绪、睡眠、主动性）无感知差异
- 全量测试不降级

---

## 8. 相关文档

- `../self-system.md` — 统一架构；本文档是其在 CLI 呈现层的补全
- `../enhancement-overview.md` — 系统增强总览（本文档完成后应在总览表补 CLI 行）
- `../layer2-prompt/README.md` — prompt 缓存，CLI 经管线收敛自动获得
- `../layer4-agent/proactive-think-loop.md`、`inner-drive-state.md` — CLI 主动路径的演进方向
- `../layer5-tool/enhancement-plan.md` — 工具结果结构化后 CLI 提示可升级
- `doc/known-issues.md` — #79（CLI 情绪）、#81（统一启动入口）
