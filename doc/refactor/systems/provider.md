# 模型/Provider 系统增强方案

> 目标：把 LLM 调用层从「截断被当成功、失败不可见」升级到「行为明确、可观测」；把 embedding 子进程从「只生不养」升级为有完整生命周期的托管服务。
> 状态：设计文档，待实现。
> 归属：基础设施（横切）。不属于六层之一——三个生命循环（响应/独处/睡眠）的全部 LLM 与 embedding 调用都经过这里。

---

## 1. 现状盘点

| 组件 | 现状 |
|------|------|
| LLM 抽象 | `LLMProvider` ABC（`core/provider.py:19`），唯一实现 `DeepSeekProvider`（OpenAI 兼容协议） |
| HTTP | 同步 `requests.Session`，连接池 5/10（`provider.py:71`），`trust_env=False`，connect=10s/read=180s（`provider.py:164`） |
| 重试 | 3 次，`time.sleep(2**attempt)` 退避；429 解析 Retry-After（`provider.py:105-150`） |
| 流式 | SSE 逐行解析，1 MB 上限（`provider.py:16`），整体 deadline=timeout（`provider.py:182`） |
| token 预算 | 全局 `config.max_tokens=512`（`config.py:56`）+ 至少 7 处调用点硬编码覆盖 |
| Embedding | llama-server 独立子进程（`memory/llama-bin/` + GGUF），`core/embedding_server.py` 负责启动，后台线程等就绪（90s） |
| 监控 | `record_call()` 环形缓冲 200 条（`core/monitor.py`），`source` 字段目前所有生产调用点均已传值（曾经的空串问题已修复） |
| 异步 | Provider 全同步；Web/睡眠路径靠 `run_in_executor` 绕行（`web/server.py:427-437/535`、`core/sleep_manager.py:157-171`） |

---

## 2. 问题清单（按严重度排序）

### P0-1 流式截断被静默当作成功返回

`core/provider.py:183-186` —— 流超过 deadline 时 `break`；`provider.py:204-206` —— 超 1 MB 时 `break`。两条路径都只打 warning，然后把**半截内容当正常结果返回**，并且随即被 `record_call()` 记为一次成功调用（`provider.py:111-120`）。后果：

- `response_format` 场景（InnerDrive 全系列、`tool_agent`）拿到半截 JSON，下游解析失败被伪装成「模型输出格式错误」，触发的是**输出质量重试**而不是**网络重试**——重试方向错了（参见 `../layer5-tool/enhancement-plan.md` P0-2 的重试分层）
- monitor 里这条记录看起来完全正常，排查时无法定位「为什么这轮决策突然解析失败」

### P0-2 读超时不重试，退避 `time.sleep` 占住 executor 线程

- `provider.py:122-150` 的 catch 列表是 `ConnectionError / HTTPError / ChunkedEncodingError / StreamConsumedError`。**`ReadTimeout` 不在其中**（requests 里 `Timeout` 与 `ConnectionError` 是并列子类，`ConnectTimeout` 因多重继承被覆盖、读超时没有）。而 read=180s（`provider.py:164`）恰恰是 LLM 长生成最容易撞上的一种失败——一次读超时直接抛给调用方，零重试。
- 退避用 `time.sleep`（`provider.py:126/139/144/150`）。Web 路径所有 generate 都跑在默认 executor 线程池里（`web/server.py:427-437, 535`），429 时按 Retry-After 一次最多睡 60s+（`provider.py:131-140`）——一个线程被白白占住。默认线程池并发上限本就只有 8-16（known-issues #166 已记录），几个 429 就能把池子睡满，正常用户消息排队。
- 另外非流式路径 `resp.json()` 解析失败（`provider.py:169`）不在重试列表，服务端返回坏 JSON 时同样零重试。

### P0-3 embedding 子进程生命周期只有「生」，没有「养」和「死」

`core/embedding_server.py` 的缺口：

- **误伤与跨平台失效**：`kill_existing_llama()`（`embedding_server.py:17-33`）用 `taskkill /F /IM llama-server.exe` 杀掉机器上**所有**同名进程——包括用户自己跑的、其他应用的 llama-server；且 tasklist/taskkill 是 Windows 专有命令，其他平台直接落进 `except` 静默跳过（`embedding_server.py:32-33`），清旧逻辑形同虚设。
- **配置漂移**：`auto_start_embedding(logger)` 在两个入口都不传 endpoint（`main.py:36`、`web_main.py:19`），探测和启动永远用默认 8080（`embedding_server.py:12, 94`）；而 `EmbeddingEngine` 用的是 `config.embedding_endpoint`（`main.py:75-78`）。用户改了配置端口后：auto_start 在 8080 起一个没人用的服务，真正的引擎连配置的端口连不上。
- **无关闭**：全代码库无任何 terminate/atexit 逻辑；Web lifespan 的优雅关闭（`web/server.py:74-78`）也不管它。进程在应用退出后残留，靠下次启动时「already running」复用（`embedding_server.py:150-152`）——这个设计意图没有文档化，所有权是一笔糊涂账。
- **无崩溃重启**：watcher 线程一旦就绪即退出（`embedding_server.py:112-114`），此后进程崩溃无人知晓。下游各自靠 `health_check()` 兜底退化为关键词检索（`memory/retrieval.py:40`、`memory/consolidation.py:522`、`memory/fact_checker.py:61`、`memory/lifecycle.py:173`）——检索质量悄悄降级，只有翻日志才能发现。

### P1-1 max_tokens 策略七处硬编码，互不知晓

- `core/agent.py:92-102`：情绪映射表硬编码（excited 512 / anxious 128……）；`agent.py:181` 第二轮起 `max(384, max_tok * 2 // 3)`
- `core/inner_drive.py:114-116`：构造函数默认值 1024/256/1024，生产构造点不传参（`core/cli_controller.py:30-34`）
- `core/tool_agent.py:100,180`：1024；`core/cli_controller.py:250`：384；`core/sleep_manager.py:161`：100
- `config.py:56` 只有全局 512，无任何 per-场景配置入口

改一次回复长度策略要改 N 处；且「情绪 → 回复长度」是**人格表现层**的决策，散落在基础设施调用参数里。另有小坑：`provider.py:92` 用 `max_tokens or self.max_tokens`，显式传 0 会静默落回默认值。

### P1-2 监控只记成功，失败与重试不可见

- `record_call()` 只在 `_do_request` 返回后调用（`provider.py:111-120`）；三次重试全失败只留一条 `logger.error`（`provider.py:152-153`）。monitor 面板看不到失败率、重试率、429 频次——和工具系统「无可观测性」（P2-1）是同一个坑的 LLM 侧。
- `set_monitor_enabled()` 在 `DeepSeekProvider.__init__` 里改全局状态（`provider.py:66-67`）——构造副作用，web 模式多处构造（`web/session.py:60-67, 275-281`），最后一个实例静默决定全局开关。

### P1-3 每条用户消息一次 embedding 健康探测

`memory/retrieval.py:40` —— `retrieve_for_query()` 每次都调 `health_check()`，先 GET /health（timeout=3）失败再 POST（timeout=5）（`memory/embeddings.py:141-153`）。注释写「RT-003: cache result」，但实际只在单次调用内复用，**跨调用不缓存**。服务器 hang 而不死时，每条用户消息最多多付 8s 阻塞（还在 executor 线程里）。探测没有统一的「健康状态」事实来源，四个调用点各自探、各自降级。

### P2-1 全同步架构与并发上限

known-issues #166 / #243 已详细记录（同步 requests 阻塞、默认线程池 8-16 并发、全面异步化愿景），本文不重复展开，只在 P2 给出与之一致的最小步骤。

### P2-2 单 Provider 实现

ABC 已有但只有 `DeepSeekProvider` 一个实现；多后端抽象（OpenAI/llama.cpp/OpenVINO）是 known-issues 中 QAgent 合并愿景的内容，等那边的产品决策，不提前建。

---

## 3. 增强方案

### P0：行为正确 + 生命周期闭环

**1. 截断显式化**（依赖：无）

- `_do_request()` 截断时不再静默返回：第一步只把事实记下来——`record_call()` 增加 `truncated: bool` 与 `finish_reason` 字段（`MonitorRecord` 加带默认值的可选字段，旧记录兼容）
- 第二步：`response_format` 调用发生截断 → 视为可重试错误（等同网络错误走重试），重试耗尽后抛错而不是交半截 JSON；纯文本聊天路径保持现状（半截回复好于报错），仅记录
- 灰度：MonitorRecord 新字段纯增量，无开关也安全

**2. 重试补齐与失败可见**（依赖：无）

- catch 列表补 `requests.exceptions.Timeout`（覆盖 ReadTimeout）与非流式 `resp.json()` 的 `JSONDecodeError`
- 退避的 sleep 函数变为可注入参数（默认 `time.sleep`）——签名不变、行为不变，为 P2 异步化留口
- 重试耗尽/不可重试错误也 `record_call(status="error", source=source, error=...)`，monitor 从此能看到失败率和 429 频次

**3. embedding 子进程生命周期最小闭环**（依赖：无；不引入新依赖）

- `auto_start_embedding()` 接受 `endpoint` 参数，两个入口传入 `config.embedding_endpoint`——先修掉配置漂移
- 启动时记录**自己拉起的 PID**（内存 + `data/.embedding_server.pid`）；清理逻辑只杀这个 PID，不再全局 taskkill；非 Windows 平台跳过 taskkill 分支并记 warning（不再静默吞）
- 崩溃懒重启：`EmbeddingEngine.health_check()` 连续失败时触发一次带退避的重启（上限 3 次/小时，超过则保持关键词降级并打 error 日志），配置开关 `embedding_auto_restart`（默认开）可一键回退
- 关停：Web lifespan 与 CLI 退出路径调用 `stop_embedding()`，只停自己拉起的进程；「复用已在运行的服务」行为保留并写进 docstring

### P1：策略集中 + 可观测

**4. token 预算集中**（依赖：无）

- 新增一张「场景 → max_tokens」表（代码常量起步）：`reply`（按情绪查系数/档位）、`tool_agent`、`assess`、`proactive`、`review`、`dream`、`cli_react`……各调用点改为引用场景名
- 第一步只集中、不改任何数值（纯重构，行为 diff 为空）；第二步把情绪映射从 `Agent._max_tokens_for_emotion()` 搬进同一张表
- `config.json` 增加可选的 `max_tokens_overrides` 覆盖入口；顺手修掉 `provider.py:92` 的 `or` 语义（改 `is not None` 判断）

**5. 统一健康事实源 + 探测缓存**（依赖：P0-3）

- embedding 健康状态集中一处（带 10s TTL 的缓存探测 + 状态变更事件日志），`retrieval / consolidation / fact_checker / lifecycle` 四个调用点改为读这份状态，不再各自 probe
- 热路径每条消息省一次 HTTP 探测；状态翻转（可用↔降级）在日志里成为显式事件

### P2：结构演进（按需，不提前做）

**6. 异步化最小步骤**（依赖：P0-2 的 sleep 注入）

与 known-issues #243 对齐，但不直接重写 httpx：先把 executor 换成**专用命名线程池**（大小可配、池名进日志），让 LLM 调用的并发占用可见、可限流；评估后再决定是否上 `httpx.AsyncClient`。

**7. 多 Provider 抽象**

等 QAgent 合并决策（known-issues LLM 抽象层条目）。当前 ABC + 单实现够用，不提前建工厂。

---

## 4. 与现有设计的关系

- **[自我系统 `../self-system.md`]**：Provider 是三个生命循环共享的「神经通路」——响应循环（react/tool）、独处循环（proactive/explore）、睡眠循环（consolidation/dream/rerank）全部经过它；embedding 健康度直接决定「记忆 → 思考」连接（连接 #3）的质量。本方案不引入新模块，只把既有管道的错误语义和健康状态说清
- **[工具系统增强 `../layer5-tool/enhancement-plan.md`]**：P0-1/P0-2 与其「重试职责分层」一致——Provider 负责网络级重试，ToolAgent 负责输出质量重试；截断显式化后，两层重试不再互相误判（known-issues #159 的 81 次嵌套重试问题也因此可解）
- **[睡眠循环 `../layer1-memory/sleep-cycle.md`]**：睡眠工作层的整理/核查/做梦全是 provider 调用；P1-2 的失败记录让「昨夜 API 是否在抖」在核查时有据可查
- **[Layer 2 Prompt `../layer2-prompt/README.md`]**：token 预算集中后与 prompt 分层/缓存的预算治理同属一处，回复长度（输出端）与 prompt 拼装（输入端）可以一起算账
- **known-issues.md**：#166（同步阻塞）、#243（全面异步化）、#159（嵌套重试）、流式 JSONDecodeError 静默——本方案是其分期落地，不重复其内容

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `core/provider.py` | 截断显式化、Timeout/JSON 重试、sleep 注入、失败记录、`or`→`is not None` | P0 |
| `core/monitor.py` | `MonitorRecord` 加 `truncated/status/error` 可选字段 | P0 |
| `core/embedding_server.py` | endpoint 参数、PID 所有权、懒重启、`stop_embedding()` | P0 |
| `memory/embeddings.py` | 健康状态缓存与变更事件 | P1 |
| `main.py` / `web_main.py` / `web/server.py` | 传 `config.embedding_endpoint`、退出时 `stop_embedding()` | P0 |
| `config.py` | `embedding_auto_restart`、`max_tokens_overrides`（可选） | P0/P1 |
| `core/agent.py` / `core/inner_drive.py` / `core/tool_agent.py` / `core/cli_controller.py` / `core/sleep_manager.py` | 调用点改引场景化 token 预算表（先集中不改值） | P1 |
| `memory/retrieval.py` / `memory/consolidation.py` / `memory/fact_checker.py` / `memory/lifecycle.py` | 改读统一健康状态，删各自 probe | P1 |
| `tests/test_provider.py` / `tests/test_embeddings.py` | 新增覆盖 | 各期 |

---

## 6. 测试与验收

测试：

1. 流式 deadline/1MB 截断 → monitor 记录 `truncated=True`；`response_format` 调用截断 → 触发重试而非返回半截
2. `ReadTimeout` → 按退避重试；三次全失败 → monitor 有 `status="error"` 记录且 `source` 保留
3. 修改 `config.embedding_endpoint` 端口 → auto_start 探测与启动用同一端口
4. 杀掉自己拉起的 llama-server → 下次 health_check 失败后触发一次重启；`embedding_auto_restart=False` 时不重启、保持关键词降级
5. 清理逻辑只杀 PID 文件记录的进程（用另一个同名进程验证不误伤）
6. token 预算表集中前后，各调用点实际 max_tokens 完全一致（行为 diff 为空）

验收：

- 构造一次服务端中途断流，monitor 面板能直接看到截断记录，不再伪装成解析失败
- 断网 30s 后恢复，monitor 能看到失败记录与重试过程
- llama-server 崩溃后无需人工干预自动恢复（日志有明确事件）；embedding 降级/恢复在日志里是显式状态翻转
- 全量测试不降级

---

## 7. 相关文档

- `../self-system.md` — 三个生命循环是本系统的全部客户
- `../layer5-tool/enhancement-plan.md` — 重试职责分层与错误分类的姊妹方案
- `../layer1-memory/sleep-cycle.md` — 睡眠工作层是 provider 的批量调用方
- `../layer2-prompt/README.md` — 输入端 token 预算治理
- `doc/known-issues.md` — #166 / #159 / #243 与流式解析静默的原始记录
