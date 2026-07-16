# Web 系统增强方案

> 目标：把 Web 层从「单人本机假设下的演示前端」升级为「安全、不阻塞、生命周期正确的服务入口」——能暴露到局域网而不被读记忆/投毒，慢 LLM 调用不冻结全服务，会话与连接各司其职。
> 状态：设计文档，待实现。
> 归属：Web 服务层（`web/`），六层体系之外的基础设施；对上承接 [Layer 6 角色绑定](../layer6-personality/README.md)，对下承接 [Layer 4 独处循环](../layer4-agent/proactive-think-loop.md) 的投递通道。总索引见 `../enhancement-overview.md`。

---

## 1. 现状盘点

| 组件 | 现状 |
|------|------|
| 入口 | FastAPI 单应用（`web/server.py`），REST + WebSocket `/ws` + SSE `/api/logs`；默认绑定 `0.0.0.0:8000`（`config.py:61`） |
| 推送方式 | **WebSocket 是唯一业务推送通道**（分段回复、主动搭话、睡眠消息）；SSE 仅用于服务日志；无轮询推送。REST `/api/chat` 是纯请求-响应降级 |
| 会话 | `SessionManager` 单例（`web/session.py`），`session_id = role_id` 强制绑定（`session.py:291-297`），一角色一会话；Provider/Embedding 共享（SN-005/006），TTL 24h + 上限 50（`session.py:360`） |
| 数据访问 | 一个全局共享 `Repository` 实例（`session.py:273`），`session_id` 是它的**可变字段**（`session.py:43`、`storage/repository.py:17`） |
| 校验 | REST 有 Pydantic（`web/schemas.py`，4 个模型）；WebSocket 消息裸 `dict.get`，无 schema |
| 限流 | 内存滑动窗口 per-IP（`web/rate_limit.py`），覆盖 3 条路径；WS message 复用 `/api/chat` 窗口（`server.py:522`，api.md 已文档化为有意设计） |
| 前端 | 新建响应式浅色 UI（`web/static/index.html` + `app.js`），marked.js 渲染 Markdown，指数退避重连；旧版备份在 `web/backups/`（3 个 `.bak`，已被 git 跟踪） |
| 监控 | `/monitor` 页 + `/api/monitor`（内存 deque，`core/monitor.py:38`），有 JSON/Markdown 导出，CSP 问题已修 |
| 安全 | CSP/XFO/nosniff 响应头（`server.py:116-124`）、WS Origin 白名单（`server.py:461-469`）、100KB 帧上限（`server.py:495`）、CORS localhost 默认——**但全系统零鉴权** |

---

## 2. 问题清单（按严重度排序）

### P0-1 零访问控制 + 默认监听 `0.0.0.0`：局域网内可读历史、可注入记忆

`config.py:61` `web_host: str = "0.0.0.0"`。CORS/CSP/Origin 只约束浏览器跨站行为，对直接 HTTP 客户端（curl）完全不设防：

- `GET /api/chat/history?session_id=小星`（`server.py:244-255`）——任意 session_id 直接拖走聊天记录，无所有权校验
- `POST /api/chat`（`server.py:145-157`）——冒用任意 session_id 写入对话，turns → consolidation → facts，**等于向它的长期记忆投毒**
- `GET /api/monitor/clear`（`server.py:313-318`）——任何人清空 LLM 监控缓冲
- `GET /api/logs`（`server.py:258-290`）——日志全文 SSE，含 session 名、消息摘要
- `GET /api/sessions` / `/api/roles`（`server.py:217-241`）——角色与 session 可枚举

api.md 9.7 自知「#155 Session ID 客户端可控：低（单人）」——但 `0.0.0.0` 默认绑定打破了「单人本机」这个前提。

### P0-2 `role_id` 未净化 → 路径穿越写文件

`server.py:503` `role_id = data.get("role_id")` 原样取自 WS init 消息 → `session.py:143` `os.path.join("personalities", f"{role_id}.json")`。`role_id="../../x"` 时 `shutil.copy(template, path)`（`session.py:147`）向工作目录外任意位置写 `.json` 文件。与 P0-1 叠加：局域网内无需任何凭证即可触发。

### P0-3 共享 `Repository.session_id` 竞态 → 跨角色记忆写串

`session.py:273` 全进程一个 `Repository`；`session.py:43` 每个 `WebAgent` 构造时 `repo.session_id = session_id` 改写这个共享字段；而 `repository.py` 的 SQL 全部经 `self.session_id` 过滤（全文件 84 行涉及 `session_id`，自 `repository.py:17` 这个可变字段读出）。场景：角色 A 的消息在 executor 线程处理中（多次 DB 读写，跨越多次 await），角色 B 此刻创建会话 → `repo.session_id` 被改写 → **A 后续的记忆写入全部落到 B 名下**。Layer 6 的隔离目标（其 README「数据隔离未完全验证」）被这层运行时共享状态击穿，schema 层的 `session_id` 过滤再严也没用。

### P0-4 REST `/api/chat` 在事件循环线程同步调 LLM

`server.py:150` `response = agent.process_message(req.message)`——同步阻塞调用，一次 LLM 请求最长 `api_timeout=180s`。期间事件循环整体冻结：WS 心跳、SSE、proactive 循环、其他所有请求全部停摆。对比 WS 路径用了 `run_in_executor`（`server.py:535`）——同一个处理函数，REST 路径独漏。连带：`status_api`/`chat_history_api` 触发会话创建时走 `run_async`（`session.py:107`），`async_utils.py:29-31` 在 loop 线程里 `future.result(timeout=60)` 同步等待，同样堵 loop。known-issues #166 记录了 provider 层同类问题，至今 open。

### P0-5 前端 segment 追加逻辑：主动/睡眠消息整段顶替上一轮回复

`app.js:104-118`：segment 到达时找 `.message.assistant:last-child .bubble`，找到就往里追加。而上一轮 `done` 已把气泡 Markdown 渲染并 `removeAttribute('data-raw')`（`app.js:124-131`）。于是典型的主动搭话场景（AI 说完 → 用户没回 → 空闲后 proactive 触发）：proactive segment 到达 → 选中的是**上一轮已渲染的气泡** → `data-raw` 为 null → `raw=''` → `textContent = proactive内容` → **上一轮回复被整段覆盖消失**（DB 未丢，刷新恢复，但界面数据丢失）。睡眠/唤醒消息走同一 `_send_segments`（`server.py:404`、`server.py:449`），同样触发。

### P1-1 会话生命周期绑死在 WS 连接上

`server.py:552-553` 连接 `finally` 里 `session_manager.remove(session_id)`：

- 任一标签页断开即销毁整个会话对象（多标签页场景另一个还连着也照杀，known-issues #210 已记录，open）
- proactive 任务随 `init` 创建（`server.py:507-508`）、随 `remove` 取消——**页面关着，主动行为和睡眠循环就完全停止**。独处循环的宿主是「连接」而不是「角色」，与 [self-system](../self-system.md) 「时间是刺激：用户不说话，循环也在转」直接冲突
- api.md:248 声称「断线后 session 保留（SessionManager 持有）」，与代码实际行为矛盾

### P1-2 WS 消息无输入校验：一条畸形消息摧毁整个会话

`server.py:498` `json.loads(raw)` 之后全部裸 `.get`。`server.py:517` `data.get("content", "").strip()`——`content` 为 list/数字时抛 `AttributeError` → 被外层 `except Exception` 捕获（`server.py:543`）→ `finally` 执行 `remove(session_id)`（`server.py:553`）。客户端发 `{"type":"message","content":[]}` 即可把自己的会话整段拆掉。`schemas.py` 只有 REST 模型，WS 协议侧无校验；init 的 `session_id`/`role_id` 类型同样不查（任意 JSON 类型可进 dict key 和文件路径，见 P0-2）。

### P1-3 `ensure_session()` 的 fallback 在它要保护的场景下必炸

`server.py:32-37`：lifespan 未跑时调 `asyncio.run(session_manager.open())`——但调用点全是 async 端点（`server.py:132/147/220/238`），loop 已在运行，`asyncio.run()` 必抛 `RuntimeError`。且防护不一致：`status_api`（`server.py:160`）、`chat_history_api`（`server.py:244`）、logs、monitor 端点根本没调——`db=None` 时直接 AttributeError 500。

### P1-4 REST chat 前端 15s abort ≪ 服务端 LLM 时长 → 幽灵消息

`app.js:399-400` REST fallback 的 fetch 15 秒 abort；服务端却会继续跑完 LLM 并把这一轮 `add_turn` 写入记忆。用户看到失败 → 重发 → **同一句话在它记忆里出现两遍**，它会觉得「你刚刚已经说过了」。WS 是主力通道，但一旦降级就踩中。

### P2-1 限流三处短板

- `rate_limit.py:62-69` 无条件信任 `X-Forwarded-For` 首段——客户端自填头即可换 IP 绕过（注释自称「trusted proxy」但无任何 proxy 校验）
- `rate_limit.py:14-18` 只覆盖 3 条路径：`/api/roles`、`/api/sessions`、`/api/logs`、`/api/monitor`、`/api/monitor/clear` 全部无限制
- `rate_limit.py:27` `_lock = False`——未完成的代码（布尔不是锁），当前靠「`is_allowed` 内无 await」侥幸安全

### P2-2 分段/情绪调速已是死代码，文档大面积漂移

`_send_segments` 里 `TODO: re-enable segmentation`（`server.py:377`），分段被禁用、全量单段发送。`_split_segments`（`server.py:327-373`）与 `_calc_delay`（`server.py:293-300`）生产路径无调用方，唯一调用方是 `tests/test_segmentation.py`——**测试在锁定死代码**。同时 api.md 仍把它们描述为现状：

- 第 4/5 节（api.md:415-492）整章描述服务端分段 + 情绪调速公式
- 3.1 节称 REST fallback 由前端 `splitSegments()` 分段——`app.js` 已无此函数，实际全量渲染（`app.js:401-419`）
- 9.1 节 Origin 校验代码片段是旧的 `startswith` 实现，与现行 hostname 白名单（`server.py:461-469`）不符
- 2.2 节 ping「每 30 秒」vs 实际 25 秒（`app.js:162-166`）；7.2 节断线行为见 P1-1

### P2-3 `/api/monitor/clear` 是 GET 写操作

`server.py:313` `@app.get("/api/monitor/clear")`——有副作用的动作用 GET，浏览器预取/爬虫即可触发；无鉴权（P0-1）、无限流（P2-1）。

### P2-4 CSP 双写已漂移

`index.html:7` 的 meta CSP 与 `server.py:43-51` 的 `CSP_HEADER` 各自维护，`connect-src` 列表已不一致（meta 多 `wss://` 条目）。两处取交集生效，改一处忘另一处就是监控页上次 CSP 事故的重演温床。CSP 应单源（响应头）。

### P2-5 前端小项

- `app.js:162-166` ping 的 `setInterval` 在每次 `connect()` 叠加，重连 N 次后 N 个心跳定时器并存，永不清理
- `app.js:128/365` `marked.parse` 结果直接 `innerHTML`，无消毒——目前靠 CSP `script-src 'self'` 兜底主向量，纵深不足（marked 官方已移除 sanitize，推荐 DOMPurify）
- Cookie 无 SameSite/Secure（`app.js:60-62`，known-issues #244 已记录，open）

### P2-6 杂项

- `server.py:189-193` `/api/status` 把 DB 时间戳硬编码 `+8h` 转北京时间（DB `CURRENT_TIMESTAMP` 是 UTC）——时区假设写死，非北京部署即错
- `server.py:263-265` `/api/logs` 连接时按当天日期打开一次文件，跨天后一直 tail 旧文件
- `web/backups/` 三个 `.bak` 被 git 跟踪（`git ls-files` 确认）——git 历史本身已是备份，目录内备份无生命周期

---

## 3. 增强方案

### 一期（对应 P0）：安全与正确性地基

**1. 访问控制最小版（灰度可回退）**

- 新增配置 `web_access_token: str = ""`——**默认空 = 不启用，行为与现状逐字节一致**，随时可退回
- 启用时：HTTP middleware 校验 `Authorization: Bearer <token>`（`/api/logs` 因 EventSource 不能自定义头，同时接受 `?token=`）；WS 在 init 消息加 `token` 字段，校验失败 `close(code=4001)`
- `web_host` 默认值 `0.0.0.0` → `127.0.0.1`；需要局域网访问时显式配置 + 强制要求同时设置 token
- `role_id`/`session_id` 白名单净化：`^[\w\u4e00-\u9fff-]{1,32}$`，非法直接拒绝——顺手消除 P0-2 路径穿越

**2. 消除事件循环阻塞**

- REST `/api/chat` 改 `run_in_executor`，与 WS 路径对齐（一行级改动）
- `status`/`history` 端点整体移入 `run_in_executor`（最小方案：端点内 `await asyncio.to_thread(...)`），避免会话创建路径的 `run_async` 在 loop 线程同步等待

**3. Repository 会话隔离（消除共享可变状态）**

- 每个 `WebAgent` 持有私有 `Repository(db, session_id)`，session_id 构造时冻结、之后不可变；`session.py:43` 的运行时改写删除
- `SessionManager` 的共享 repo 只保留显式传参的无会话方法（`set_session_role`/`get_role_for_session`/`get_sessions_by_role`，均已是显式传参）
- 这正是 [Layer 6](../layer6-personality/README.md) Step 1「`Repository.session_id` 必须从 `RoleSession.role_id` 读取」的 web 侧落地——方案对齐，不另起炉灶
- 依赖：`storage/repository.py` 构造函数加参（现仅 `db` + 可变字段），波及 `tests/test_repository.py`，需全量测试

**4. 前端气泡归属修复**

- 当前分段已禁用、segment 恒为单条全量：前端改为 **segment 一律新建气泡**，done 只负责渲染最后一条——立即修复 P0-5
- 未来若恢复服务端分段，再引入 `msg_id` 归属（同 id 追加、新 id 新建），两段走不超前设计

### 二期（对应 P1）：生命周期与健壮性

**5. WS 消息 schema 校验**

- `schemas.py` 增加 `WSInitMessage` / `WSChatMessage` / `WSPing`（按 `type` 判别），解析失败回 `{"type":"error"}` 并 `continue`——消息级错误不再走「异常 → finally remove」的毁会话路径

**6. 会话与连接解耦**

- `remove()` 改宽限回收：连接断开不立即销毁，标记后由 `cleanup_old` 按短 TTL（如 10 分钟）回收；重连命中即取消标记——多标签页与网络抖动不再杀会话（收口 #210）
- proactive 循环的宿主从「连接」挪到「会话」；新增 `proactive_when_offline: bool = False`——**默认关 = 现状**，开启后页面全关循环照转，消息写 turns 待重连补发。彻底的后台独处循环是 Layer 4 的事，本方案只把挂钩点挪对
- 依赖：方案 3（离线循环写记忆必须会话隔离先行）

**7. `ensure_session` 清理**

- 删除 `asyncio.run` fallback，改为 `Depends(get_session_manager)` 依赖注入，lifespan 未跑 = 快速失败 503——全端点一致，删掉假防护

**8. REST chat 前后端对齐**

- 前端 REST fallback 的 abort 去掉或放宽到 > `api_timeout`；UI 上明示「降级模式较慢」

### 三期（对应 P2）：一致性清理

**9. 限流补齐**

- `X-Forwarded-For` 仅在 `trust_proxy=True`（新增配置，默认 False）时采纳
- 限流表补 `/api/logs`、`/api/monitor*`；`/api/monitor/clear` 改 POST（顺一期 token 校验）
- 删除 `_lock = False` 半成品

**10. 死代码决策（建议删除而非恢复）**

- 删 `_split_segments`/`_calc_delay` + `tests/test_segmentation.py`，api.md 第 4/5 节重写为现行「单气泡累积 + done 渲染」协议
- 理由：分段气泡与 Markdown 渲染的冲突正是当年禁用的根因（`server.py:377` TODO），现模式已稳定；恢复成本高、收益存疑。若产品决策要「打字机感」，用前端按字符流式渲染实现，不动协议
- 依赖：产品决策（分段体验要不要回来）

**11. 文档同步（随各期落地逐节改）**

api.md：9.1 Origin 现行实现、ping 25s、7.2 断连行为、3.1 REST 渲染方式、4/5 节按方案 10 处理。

**12. 小项包**

- CSP 单源化：删 `index.html:7` meta CSP，以响应头为唯一来源
- ping interval 句柄管理（`connect()` 前 `clearInterval`）
- marked 消毒：CSP 已兜底主向量，记录为可接受残余风险；引入 DOMPurify 标为可选，不发明需求
- `/api/status` 时间戳返回 UTC ISO，转换交给前端（`formatDateTime` 本就按本地时区渲染）
- `/api/logs` 跨天重开文件
- 删 `web/backups/`（git 历史即备份），收口 known-issues #244 的 cookie 项

---

## 4. 与现有设计的关系

- **[自我系统](../self-system.md)**：web 层是响应循环的唯一入口；方案 6 把 proactive 宿主从连接挪到会话，是「时间是刺激」原则在 web 层成立的前提——否则用户合上页面，独处/睡眠循环就失去存在载体
- **[Layer 6 角色绑定](../layer6-personality/README.md)**：`session_id = role_id` 在 web 层已提前落地一半；方案 3 是其 Step 1 的 web 侧实现，其「数据隔离未完全验证」由方案 3 + 测试收口
- **[Layer 4 独处循环](../layer4-agent/proactive-think-loop.md)**：独处循环需要「页面不在也活着」的运行载体，方案 6 的挂钩点迁移与 `proactive_when_offline` 开关是它的 web 侧过渡形态，不重复其设计
- **[Layer 5 工具系统](../layer5-tool/enhancement-plan.md)**：其 P2 工具指标以 `/monitor` 为展示出口；本文档不动 monitor 数据面，只修它的访问控制（方案 1）与操作语义（方案 9）
- **[known-issues](../../known-issues.md)**：本方案是 #210（多标签竞态）、#166（同步阻塞）、#244（cookie/重连）、#263（async_utils）、api.md #155（session 可控）这些 open issue 的收口路径，不重复记录

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `config.py` | `web_access_token` / `trust_proxy` / `proactive_when_offline`；`web_host` 默认值 | 一/二/三 |
| `web/server.py` | token middleware、executor 化、输入净化调用、宽限回收、WS 校验接入、monitor/clear 改 POST、logs 跨天 | 一/二/三 |
| `web/session.py` | 私有 Repository、删 `repo.session_id` 改写、role_id 净化、宽限回收 | 一/二 |
| `web/schemas.py` | WS 消息模型 | 二 |
| `web/rate_limit.py` | trust_proxy 开关、补路径、删 `_lock` | 三 |
| `storage/repository.py` | 构造函数冻结 session_id | 一 |
| `web/static/app.js` | segment 新建气泡、ping 句柄、REST abort 对齐 | 一/二 |
| `web/static/index.html` | 删 meta CSP | 三 |
| `web/backups/` | 删除 | 三 |
| `doc/api.md` | 全量同步（分段章、安全章、会话章） | 三 |
| `tests/test_repository.py` / `test_session_manager.py` / `test_web_agent.py` / `test_rate_limit.py` | 适配 + 新增覆盖 | 各期 |
| `tests/test_segmentation.py` | 删除（随方案 10） | 三 |

---

## 6. 测试与验收

测试：

1. `role_id="../../x"` → 拒绝，`personalities/` 外无文件创建
2. token 启用：无凭证请求 401、WS close 4001；token 关闭：行为与现状一致（回退验证）
3. REST `/api/chat` 处理期间 WS ping 往返 < 1s（不冻结）
4. 两角色并发发消息，`conversation_turns` 各自落各自 `session_id`（P0-3 回归）
5. 上一轮 done 后收到 proactive segment → 上一轮气泡内容仍在（前端单测/jsdom）
6. WS 发 `{"type":"message","content":[]}` → 收到 error、连接存活、session 保留
7. `trust_proxy=False` 时伪造 XFF 不改变限流键；`/api/monitor/clear` 只接受 POST
8. 断连后 10 分钟内重连：会话对象未重建（proactive 任务未中断）

验收：

- 服务绑定 `0.0.0.0` + token 时，局域网另一台机器无凭证访问任何 `/api/*` 均 401
- 页面关闭后重开，聊天记录、情绪、proactive 节奏无感知断层
- api.md 每一节都能与代码逐行对上
- 全量测试不降级

---

## 7. 相关文档

- `../self-system.md` — 统一架构：本文档是响应循环入口与循环投递通道的加固
- `../layer6-personality/README.md` — 角色绑定：方案 3 是其 Step 1 的 web 侧落地
- `../layer4-agent/proactive-think-loop.md` — 独处循环：方案 6 为其提供正确的运行宿主
- `../layer5-tool/enhancement-plan.md` — 工具指标将挂在 monitor 出口
- `../../api.md` — 现行协议文档（多处漂移，随三期同步）
- `../../known-issues.md` — #155/#166/#210/#244/#263 的原始记录
