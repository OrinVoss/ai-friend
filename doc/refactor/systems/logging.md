# 日志系统增强方案

> 目标：让日志从「按天堆文件」升级为「可关联、有生命周期、跨进程职责清晰」的观测基础设施。
> 状态：设计文档，待实现。
> 归属：不属于六层中的任何一层——日志是三个生命循环（见 `../self-system.md`）共享的基础设施，本方案只改观测管线，不动自我状态。

---

## 1. 现状盘点

| 组件 | 现状 |
|------|------|
| 主日志 | `core/logging_setup.py`：root logger + `logs/YYYY-MM-DD.log` 文件 handler（UTF-8）+ stderr 控制台 handler（无编码处理），启动时调用一次 |
| 入口 | CLI `main.py:33`、Web `web_main.py:17` 各调一次 `setup_logging()`；uvicorn 会重置 root handlers，`web/server.py:59-64` 在 lifespan 里重调一次打补丁 |
| embedding 子进程日志 | `core/embedding_server.py:166`：llama-server 的 stdout/stderr 直接追加到 `logs/embedding_server.log`，与主日志分离 |
| LLM 调用监控 | `core/monitor.py`：200 条内存环形缓冲，记录完整 messages/response；Web `/api/monitor` 面板 + JSON/Markdown 导出（`changes/2026-07-14-monitor-export.md`） |
| 日志查看 | Web `/api/logs`（`web/server.py:258-290`）：SSE 推送当日日志文件尾部 |
| logs/ 目录实际内容 | 10 个日期文件 + `embedding_server.log`（3.7 MB，一天多长出）。**`server.log`/`web_service.log` 当前并不存在**——代码里没有任何地方产出它们，`web_service.log` 只在 `changes/2026-07-14-monitor-buffer-source-switch.md:66` 作为手工 nohup 命令出现过 |
| 测试覆盖 | `tests/` 下没有任何 logging / monitor 相关测试 |

日志埋点前缀分布（真实代码）：`[ws]`/`[rest]`（web.server）→ `[msg]`（message_handler）/ `[cli]`（cli_controller，CLI 走 `Agent.run() → self._cli.run()`，`core/agent.py:294-295`）→ `[inner_drive]`（Agent 1）→ `[tool]`（dispatcher，Agent 2）→ `[api]`（provider）→ `[db]`（repository）→ `[session]`（web.session）。

---

## 2. 问题清单（按严重度排序）

### P0-1 跨天不切换：日期文件名在启动时算死

`core/logging_setup.py:14-15` —— `today` 在 `setup_logging()` 调用时计算一次，`FileHandler` 打开后不再切换。进程跨过午夜后，新一天的日志继续写进**昨天**的文件。证据就在 logs/ 目录里：

- **不存在 `2026-06-12.log`**，而 `2026-06-11.log` 的最后写入时间是 06-13 00:19——06-12 全天和 06-13 凌晨的日志都在名为 06-11 的文件里
- `2026-06-13.log` 同样写到了 06-14 02:16

连带后果：`/api/logs` 按「今天」拼文件名（`web/server.py:264-265`），跨天后 Web 控制台显示 `[no log file]`，而应用其实还在正常写日志——观测窗口直接黑屏。

### P0-2 重设日志时旧 FileHandler 不关闭，句柄泄漏

`core/logging_setup.py:26` —— `root.handlers.clear()` 只摘除列表引用，**不调用 `close()`**。Web 模式下 `setup_logging()` 至少被调两次（`web_main.py:17` + `web/server.py:62` 的 lifespan 重设），每次泄漏一个对当日日志文件的打开句柄；uvicorn reload 或多次重设会累积，Windows 上被占用的文件还会影响轮转和清理。

### P0-3 Windows 控制台中文乱码

`core/logging_setup.py:29` 文件 handler 显式 `encoding="utf-8"`，但 `:38` 控制台 handler 直接 `StreamHandler(sys.stderr)` 不做任何编码处理——两个 handler 编码策略不对称。`doc/known-issues.md` 第 2 节已记录现象（session 名「小星」显示为 `С��`），建议栏写着「统一日志编码为 UTF-8」，一直没有落实。

### P1-1 无请求级关联 ID，跨模块调试靠肉眼对齐时间戳

一条用户消息的日志横跨至少 6 个模块、5 种前缀，只有入口处带 `session=`：

```
web/server.py:529   [ws] message session=小星 len=3        ← 唯一带 session 的一行
message_handler.py:200  [msg] turn=... len=...
inner_drive.py:145  [inner_drive] start len=...
dispatcher.py:155   [tool] executed N tools ...
provider.py:173     [api] model=... duration=...
repository          [db] insert_turn: ...
```

formatter（`core/logging_setup.py:17-20`）只有时间/级别/模块名，全库 grep 不到 `request_id`/`contextvars`/`LoggerAdapter` 的任何使用。多 session 并发 + 状态轮询时日志交错（实证：`logs/2026-07-14.log` 10:02:11 的消息处理与 10:02:12 的 status 轮询交替出现），想还原一条消息的完整链路只能按时间戳肉眼对齐。monitor 记录（`core/monitor.py:116`）的时间戳甚至只有 `%H:%M:%S` 没有日期，跨天连肉眼对齐都对不上。

### P1-2 embedding_server.log 无生命周期，无限增长

`core/embedding_server.py:81-100` 把子进程 stdout/stderr 追加写入固定文件，`:166` 拼路径——没有任何轮转、截断、清理。实测一天多长到 3.7 MB（llama.cpp 的启动 banner + 每次请求日志都往里写），长期运行无界。违反「万物有生命周期」原则。

### P1-3 monitor 与日志职责重叠，且两个观测面互不关联

同一次 LLM 调用被记两份，信息割裂：

- monitor 存完整 messages/response（`core/provider.py:111-120`），但**只记成功调用**——重试耗尽走异常路径（`provider.py:152-153`）的调用在监控面板里完全不可见
- 日志只记一行摘要（`provider.py:173-177`）和失败告警（`provider.py:152`），成功调用的 prompt 内容看不到
- monitor 记录无日期时间戳（`core/monitor.py:116`）、无请求关联字段，和日志之间没有任何可以对齐的键

另外 `MonitorBuffer.is_enabled()`（`core/monitor.py:76-80`）全库无调用方，是死代码；实际开关走的是模块级全局 `_monitor_enabled`（`monitor.py:85-99`），由 `DeepSeekProvider.__init__` 在构造时翻转（`provider.py:66-67`）——实例构造改全局状态，两套开关并存。

### P2-1 uvicorn 自身日志不进文件，重设补丁静默失败

`web_main.py:31-37` 用 uvicorn 默认 log config——uvicorn 的 `uvicorn`/`uvicorn.access` logger 带私有 handler 且不 propagate 到 root，启动横幅、访问日志只出现在控制台，文件里查不到（实证：`logs/2026-07-14.log` 开头没有任何 uvicorn 行）。lifespan 的重设补丁（`web/server.py:59-64`）只救应用 logger，且 `except Exception: pass`（`:63-64`）把文件日志重建失败整个吞掉——失败时只剩控制台输出，无人知晓。

### P2-2 配置重复加载产生重复日志

`load_config()` 至少被调 3 次：`web_main.py:16`、`web/server.py:26`（模块级）、`web/server.py:62`（lifespan 里仅为取 `log_level` 又加载一次）。实证：`logs/2026-07-14.log` 10:01:53 同一秒出现两行一模一样的 `[config] loaded from: config.json`。

### P2-3 /api/logs SSE 实现的脆弱点

`web/server.py:271` 每次连接 `f.readlines()` 把整个日志文件读进内存（当前单日已到 600 KB 级）；`:264-265` 连接建立时算死当日文件名，跨天后一直 tail 旧文件。随 P0-1 的修复一并处理。

### P2-4 logs/ 目录无保留策略

日期文件只增不删，全库无任何清理代码。当前 5.6 MB 不算问题，但无界。

---

## 3. 增强方案

分期原则：P0 各项互不依赖可独立上线；所有行为变化都带配置开关，一键退回现状。

### P0：止血（确定性修复，纯 stdlib）

**1. TimedRotatingFileHandler 替换手写日期文件**（修 P0-1 + P2-4）

`logging.handlers.TimedRotatingFileHandler(logs/app.log, when="midnight", backupCount=14, encoding="utf-8")`——stdlib 确定性轮转，跨天自动切换，14 天保留自动清理，一次解决跨天张冠李戴和目录无界两个问题。配套修改 `web/server.py:264-265` 的 `/api/logs` 改为 tail 当前 `app.log`（同修 P2-3 的跨天 tail 旧文件问题）。

灰度开关：`config.log_rotation: bool = True`，置 False 退回现有的「启动时拼日期文件名」逻辑。

**2. 重设前关闭旧 handler**（修 P0-2）

`root.handlers.clear()` 改为逐个 `close()` + `removeHandler()`，三行改动，无行为变化。

**3. 控制台 handler 显式 UTF-8**（修 P0-3，关闭 known-issues 第 2 节）

`sys.stderr.reconfigure(encoding="utf-8", errors="replace")`，`hasattr` 守卫 + try/except 兜底（管道、重定向、非 Windows 环境安全跳过）。`errors="replace"` 保证极端终端下不抛异常，文件 handler 不动。

### P1：关联与生命周期

**4. 请求级 request_id：ContextVar + logging.Filter**（修 P1-1，本方案核心）

- 模块级 `contextvars.ContextVar("request_id", default="")`；一个 `logging.Filter` 把它注入每条 record，formatter 增加 `%(request_id)s` 字段（为空时显示 `-`，不破坏现有行格式）
- 生成点（只在入口生成，短 id 如 `uuid4().hex[:8]`）：`chat_api`（`web/server.py:146`）、WebSocket 消息循环（`web/server.py:529`）、CLI 输入循环（`core/cli_controller.py` 的 perceive 入口）
- 线程边界：asyncio task 自动传播 context；但 ws 路径的 `run_in_executor`（`web/server.py:535`）切线程不传播，需 `contextvars.copy_context()` 包装 `agent.process_message`——这是唯一需要小心的地方
- 效果：`grep request_id` 一次捞出 `[ws]→[msg]→[inner_drive]→[tool]→[api]→[db]` 全链路；独处/睡眠循环的日志天然无 request_id（显示 `-`），与请求驱动日志自然区分，符合三个生命循环的边界

灰度开关：`config.log_context_enabled: bool = True`，置 False 时 formatter 回到现状格式。

**5. embedding_server.log 生命周期**（修 P1-2）

启动重定向前检查大小：>10 MB 则滚动为 `embedding_server.1.log`（覆盖旧的，只留两代）。确定性规则，零依赖，写在 `core/embedding_server.py:166` 拼路径处。

**6. monitor 接通 request_id + 完整时间戳**（修 P1-3 的关联断裂）

- `MonitorRecord` 增加可选字段 `request_id: str = ""`（`record_call` 从 ContextVar 读，未设置则为空，旧数据兼容）；`timestamp` 从 `%H:%M:%S` 改为含日期
- monitor 面板与导出透传新字段（前端只加一列，改动极小）
- 效果：监控面板看到一次慢调用 → 拿 request_id 去日志里捞全链路；两个观测面从「平行宇宙」变成「互为索引」

依赖：P1-4（ContextVar 落地后才有东西可读）。

### P2：整合与降噪

**7. uvicorn 日志接入管线**（修 P2-1）

`uvicorn.run()` 传自定义 log_config（或把 `uvicorn`/`uvicorn.access` logger 的 handler 清空并打开 propagate），启动横幅/访问日志进文件；lifespan 重设的 `except Exception: pass` 改为至少 `logger.warning` 一行——失败要可见。依赖：P0-1（handler 结构稳定后再接，避免和轮转打架）。

**8. 消除重复 load_config**（修 P2-2）

lifespan 复用 `web/server.py:26` 已有的模块级 `config`，删掉 `:62` 的第三次加载。顺手消掉重复日志行。

**9. monitor 职责归位**（修 P1-3 的重叠与死代码）

定位划清：**monitor = LLM 请求/响应全量观测台（含失败），日志 = 系统事件流**。具体三件事：删除无调用方的 `MonitorBuffer.is_enabled()`（`core/monitor.py:76-80`）；失败调用也写入 monitor（带 `error` 字段，异常路径在 `provider.py:152` 前补一记）；全局开关保留，文档化「provider 构造时设置」的现状语义。依赖：P1-6。

明确不做的：不引入 structlog/ELK 等外部组件，不做日志级别动态调整，不给每条日志强行结构化——当前规模用不上（不发明不需要的东西）。

---

## 4. 与现有设计的关系

- **自我系统（`../self-system.md`）**：日志是三个生命循环共享的基础设施，本方案不新增模块、不动自我状态。request_id 让①响应循环全链路可观测；②独处循环、③睡眠循环的日志以空 request_id 与请求驱动日志自然区分，正好印证「哪些活动是时间驱动的」
- **工具系统增强（`../layer5-tool/enhancement-plan.md`）**：其 P2-1「工具指标挂到 monitor」依赖本文 P1-6——monitor 有了 request_id，per-tool 指标才能归属到具体请求；两份方案对 monitor 的增量无冲突
- **known-issues 第 2 节（`doc/known-issues.md`）**：P0-3 落地后该条目可关闭
- **历史补丁**：`changes/2026-06-10-logging-fix.md` 的 lifespan 重设是治标，P0-2 + P2-7 落地后该补丁变成正规军；`changes/2026-07-14-monitor-buffer-source-switch.md` 的 source 标签体系与 P1-6 的 request_id 互补（source 回答「哪个阶段」，request_id 回答「哪次请求」）
- 本文档应被 `../enhancement-overview.md` 的总览表索引（基础设施行）

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `core/logging_setup.py` | TimedRotatingFileHandler + 旧 handler 关闭 + 控制台 UTF-8 + ContextVar/Filter 注入 request_id | P0/P1 |
| `config.py` / `config.example.json` | `log_rotation`、`log_context_enabled` 开关 | P0/P1 |
| `web/server.py` | `/api/logs` 改 tail 当前文件 + 尾部读取；入口生成 request_id；executor 包装 copy_context；lifespan 复用 config、去静默 except | P0/P1/P2 |
| `core/embedding_server.py` | 启动前大小检查 + 两代滚动 | P1 |
| `core/monitor.py` | `MonitorRecord` 加 request_id/含日期时间戳；删死代码；失败记录 | P1/P2 |
| `core/provider.py` | record_call 传 request_id；异常路径补记失败 | P1/P2 |
| `web_main.py` | uvicorn log_config 接入 | P2 |
| `core/cli_controller.py` | CLI 入口生成 request_id | P1 |
| `web/static/monitor.html` / `monitor.js` | request_id 列透传 | P1 |
| `tests/test_logging_setup.py`（新增） | 轮转 / handler 关闭 / 编码 / request_id 注入 | 各期 |

---

## 6. 测试与验收

测试：

1. 轮转：TimedRotatingFileHandler 配置正确（when/backupCount/encoding）；`log_rotation=False` 时回到旧行为
2. 重复 `setup_logging()` N 次后，旧 handler 均已 `close()`，无句柄泄漏
3. 控制台 UTF-8 重配置被调用且异常环境静默跳过
4. 入口设置 ContextVar 后，下游日志 record 带 request_id；`copy_context` 包装后 executor 线程内仍可读；未设置时字段为 `-`
5. embedding log 滚动：预置 >10 MB 文件，启动后生成 `.1.log` 且只留两代
6. monitor：record_call 后记录含 request_id 与含日期时间戳；异常路径产生带 error 的记录
7. `/api/logs`：跨天后仍 tail 当前文件（tmp logs 目录集成测）

验收：

- 进程连续运行跨天，日志按天切分、文件名与实际日期一致，Web 控制台跨天后仍可见当日日志
- 一条 WebSocket 消息可用同一 request_id grep 出 `[ws]→[msg]→[inner_drive]→[api]→[db]` 全链路
- `embedding_server.log` 体积有上限
- Windows 控制台中文（如 session 名「小星」）正常显示
- monitor 面板可按 request_id 跳转日志排查
- 全量测试不降级（基线 366 passed，见 `changes/2026-07-14-monitor-buffer-source-switch.md`）

---

## 7. 相关文档

- `../self-system.md` — 三个生命循环：日志是共享基础设施，request_id 主要服务①响应循环
- `../enhancement-overview.md` — 系统增强总览（本文档待索引）
- `../layer5-tool/enhancement-plan.md` — 工具指标挂 monitor 依赖本文 P1-6
- `doc/known-issues.md` — 第 2 节「日志中文显示乱码」（P0-3 关闭）
- `doc/startup-flow.md` — 启动流程中的 setup_logging 调用点
- `changes/2026-06-10-logging-fix.md` — uvicorn 顶掉 FileHandler 的历史补丁（P0-2/P2-7 根治）
- `changes/2026-07-14-monitor-buffer-source-switch.md` — monitor source 标签体系（与 request_id 互补）
