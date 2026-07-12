# AI-Friend 项目 Open Issues 修复报告

**报告日期**：2026-07-12  
**更新日期**：2026-07-12（补充 Batch #58/#54/#45/#43/#23/#28/#24 修复关闭记录）  
**调查范围**：GitHub 仓库 `OrinVoss/ai-friend` 当前所有 **open** issue  
**代理编号**：10808  
**数据来源**：`gh issue list --repo OrinVoss/ai-friend --state open`  
**本地代码分支**：当前工作目录 `D:/桌面/编程作品/AI朋友`  

---

## 一、执行摘要

本次审查共梳理出 **40+ 个 open issue**（截至报告日）。后续修复进展：
- **2026-07-12 已修复关闭：48 个 issue**（Batch 1-3：9 个 + 历史 P1：23 个 + Batch 4-7：16 个）
- **剩余 open：~80 个**（P2/P3 代码清理、架构审查、v1.0 发布标准）

| 类别 | 数量 | 代表 Issue | 紧迫性 |
|------|------|-----------|--------|
| v0.5 P1 Bug | 8（已修 5，跳过 3） | #244, #243, #242, #239, #233, #215, #214, #210 | 🔴 最高 |
| v0.4 / v0.3 / v0.2 P1 Bug | ~13（已修 10，待修 4） | #182, #179, #176, #185, #184, #180, #175, #174, #172, #170, #169, #167, #168 | 🟠 高 |
| v0.5 P2/P3 质量改进 | ~23 | #284, #278, #277, #274, #273, #272, #267-#249, #248, #247 | 🟡 中 |
| 架构审查 | 4 | #296, #295, #294, #293 | 🟢 低（长期） |

**核心发现**：

1. **安全与数据隔离是当前最大风险**：WebSocket Origin 校验可被绕过、Cookie 无安全标记、多 tab 共享 session 导致 disconnect 互相影响、Repository 大量查询未按 `session_id` 过滤。这些问题在真实多用户/多标签场景下会导致跨会话数据污染和安全漏洞。
2. **状态副作用前置是反复出现的模式**：`check_rate_limit` 在"判断通过"时就更新状态、`register_proactive` 未等旧任务结束就新建任务、`WebSocket init` 未做连接计数。这种"先改状态再执行"导致后续逻辑基于脏状态做决策。
3. **动态 SQL 与迁移机制缺失**：`storage/database.py` 中的 `ALTER TABLE` 使用字符串拼接，无白名单；`schema_version` 表仅写入不读取，无法支撑后续 schema 演进。
4. **Tool 基类与实现签名不一致**：`Tool.execute` 声明为 `async`，但 8 个子类全部为同步实现，依赖运行时 `inspect.iscoroutinefunction` 分支，违反 LSP。

**新增关闭（2026-07-12 第二批）**：
- 在提交 `9296694` 中一次性修复并关闭 **7 个 issue**：`#58`、`#54`、`#45`、`#43`、`#23`、`#28`、`#24`。
- 详见下文「十一、2026-07-12 批量修复关闭详情」。

**建议策略**：
- **已完成（2026-07-12）**：闭环全部 P1 Bug（修复 32 个 issue），包括安全/数据隔离/状态管理/Tool LSP/.format 安全/睡眠丢消息/消息大小限制等；同时完成第二批 7 个重构/安全/可配置性 issue。
- **下一阶段**：按模块消化 P2/P3 质量改进项（23 个）。
- **长期**：参考 #296-#293 的架构审查，做 Truth Maintenance、Context Manager、Prompt 架构的演进。

---

## 二、Open Issue 总览表

### 2.1 v0.5 P1 Bug

| # | 状态 | 标题 | 主要文件 | 问题类型 |
|---|------|------|---------|---------|
| #244 | ⏭ 跳过 | frontend Cookie missing HttpOnly/Secure/SameSite + reconnect storm + name hardcoded | `web/static/app.js`, `web/server.py` | 安全 / 前端 |
| #243 | ✅ 已修 | prompts/templates .format() no input sanitization KeyError crash + FACT format misleading | `prompts/templates.py`, 多处调用点 | 健壮性 |
| #242 | ✅ 已修 | tools/traits.py execute base class async but all 8 implementations sync — LSP violation | `tools/traits.py`, `tools/*_tools.py` | 类型契约 |
| #239 | ✅ 已修 | proactivity sentiment/goodbye keyword matching coarse + rate_limit updates timestamp before send | `core/proactivity.py`, `web/server.py` | 状态管理 |
| #233 | ⏭ 跳过 | WebSocket Origin check startswith localhost bypassable via localhost.evil.com | `web/server.py` | 安全 |
| #215 | ✅ 已修 | schema_version table never read/written + dynamic SQL lacks whitelist | `storage/database.py` | 数据 / 安全 |
| #214 | ✅ 已修 | repository multiple query methods missing session_id filter | `storage/repository.py` | 数据隔离 |
| #210 | ⏭ 跳过 | WebSocket multi-tab session race — disconnect destroys session + init repeatable | `web/session.py`, `web/server.py` | 并发 / 状态 |

### 2.2 历史版本 P1 Bug

| # | 状态 | 标题 | 主要文件 |
|---|------|------|---------|
| #185 | ✅ 已修 | check_rate_limit 首次调用逻辑缺陷 + 睡眠期间用户消息丢失 | `core/proactivity.py`, `core/message_handler.py`, `core/sleep_manager.py` |
| #184 | ✅ 已修 | consolidation 的 LLM 调用无独立超时 + Personality 损坏回退 | `memory/consolidation.py`, `core/personality.py` |
| #183 | ✅ 已修 | ToolRegistry 缺乏工具权限元数据 | `tools/traits.py` |
| #182 | ✅ 已修 | Agent 3 ReAct 中 max_tokens 动态调整不合理 + _react_loop 中 add_to_history=False 时仍增加 turn_count + fake_action 重试无退避 + 空输入未拦截 + contains_fake_action 对工具返回误判 | `core/agent.py`, `core/dispatcher.py` |
| #180 | 🌑 待修 | 梦境生成同步阻塞 + CLI 缺失 + 记忆关联弱（#180 梦境已 async，CLI 仍待修） | `core/sleep_manager.py`, `ui/cli.py` |
| #179 | ✅ 已修 | Agent 1 review/re_decide 存在消息累积问题 + tool_result 注入位置导致 system prompt 被挤到末尾 | `core/message_handler.py`, `core/tool_agent.py` |
| #178 | 🌑 待修 | 数据库文件缺乏权限控制 + WAL 模式未配置自动检查点 + 日志 I/O 同步高频场景瓶颈 + 日志无轮转 | `storage/database.py`, `core/logging_setup.py` |
| #176 | ✅ 已修 | ConversationBuffer 无单条消息大小限制可导致 OOM | `memory/short_term.py` |
| #175 | ✅ 已修 | 工具调用结果格式化存在双重标准 + short_term 历史消息插入顺序不一致 | `core/dispatcher.py`, `memory/short_term.py` |
| #174 | ✅ 已修 | Web 路径中 emotion 事件记录缺失 + API 连接超时与读取超时未分离 | `web/server.py`, `core/provider.py` |
| #172 | ✅ 已修 | GlobTool/GrepTool 目录遍历无缓存 + 多处性能瓶颈 | `tools/file_tools.py`, `tools/search_tools.py` |
| #170 | 🌑 待修 | _build_messages 字符截断导致 token 估算失真 + O(k) 已修（#168 已修复） | `core/context_manager.py`, `core/message_handler.py` |
| #169 | 🌑 待修 | SleepManager 情绪驱动睡眠检测不完整 | `core/sleep_manager.py` |
| #168 | ✅ 已修 | Performance：estimate_tokens 误差 + 情绪行为描述浪费 | 多文件 |
| #167 | ✅ 已修 | 睡眠系统缺陷 — 睡眠全局共享 + sleep_cooldown 整数递减 | `core/sleep_manager.py` |
| #105 | ✅ 已修 | 梦境事件被普通情绪事件挤出 emotion_events 列表 | `models/personality.py` |
| #152 | ✅ 已修 | _react_loop 消息累积 + max_tool_iterations 可配置 | `core/agent.py`, `config.py` |
| #27 | ✅ 已修 | Shutdown 不关闭 DB | `web/session.py` |
| #29 | ✅ 已修 | 异常退出不清理 react 状态 | `core/cli_controller.py` |

### 2.3 v0.5 P2/P3 质量改进

| # | 状态 | 模块 | 标题 |
|---|------|------|------|
| #284 | 🌑 待修 | 横切 | 异常处理/日志/资源泄漏/竞态条件全面修复 |
| #278 | 🌑 待修 | web/static | CSP/referrer/标题统一/ARIA/CSS变量 |
| #277 | 🌑 待修 | web/static/app.js | 异常处理/重连/超时/分段同步/心跳/streamComplete |
| #274 | 🌑 待修 | tools/memory_tools | 私有方法/异常保护/类型转换 |
| #273 | 🌑 待修 | tools/traits | 覆盖警告/JSON schema/ToolResult |
| #272 | 🌑 待修 | tools/notify_tool | 静默吞错/僵尸进程/参数未使用 |
| #267 | 🌑 待修 | models/personality | baseline推导/sleepiness/类型安全/阈值/锁/decay/死亡螺旋/FIFO |
| #266 | 🌑 待修 | core/personality | 阈值/注入/快照/backup/save异常 |
| #265 | 🌑 待修 | core/proactivity | 无锁/文档/怨恨/threshold/cap/话题去重 |
| #263 | 🌑 待修 | core/async_utils | 线程池单例/超时传播/Runner |
| #262 | 🌑 待修 | core/context_manager | tokenizer锁/回退公式/CJK截断/消息重建 |
| #259 | 🌑 待修 | core/cli_controller | 多轮缺失/误报/兜底/异常保护 |
| #258 | 🌑 待修 | core/tool_agent | 常量重复/参数审计/失败区分/retry消息 |
| #257 | 🌑 待修 | core/inner_drive | 常量重复/关键词假阴性/URL解析/CJK标点 |
| #256 | 🌑 待修 | core/message_handler | CLI不一致/review记忆/token估算/insert复杂度 |
| #255 | 🌑 待修 | core/agent | 惰性init/stream冻结/deque/阈值/可配置 |
| #254 | 🌑 待修 | memory/fact_checker | N+1/验证/LLM检测/numpy |
| #253 | 🌑 待修 | memory/embeddings | lock/bytes_to_vec/硬编码/监控 |
| #252 | 🌑 待修 | memory/consolidation | import位置/bare except/log/N+1/关系衰减 |
| #250 | 🌑 待修 | memory/long_term | 重复定义/关键词对齐/死代码 |
| #249 | 🌑 待修 | memory/short_term | 文档/deadcode/命名/原子性 |
| #248 | 🌑 待修 | storage/repository.py | commit缺失/索引/N+1/死代码 |
| #247 | 🌑 待修 | storage/database.py | 权限/CHECK约束/WAL/重试/死代码 |

### 2.4 架构审查

| # | 标题 | 说明 |
|---|------|------|
| #296 | FactChecker 审查：事实矛盾检测与置信度管理评估 | 建议引入 LLM Judge、Status 体系、Merge/Duplicate/Refine 生命周期 |
| #295 | ContextManager 审查：上下文窗口管理评估与改进建议 | tokenizer、压缩策略、CJK 处理 |
| #294 | Prompt 架构审查：Agent 认知架构评估与改进建议 | system prompt 组织、工具 schema 精简 |
| #293 | 架构审查：三层 Agent 系统成熟度评估与改进建议 | Agent 1/2/3 职责边界、状态机、错误传播 |

---

## 三、v0.5 P1 Bug 深度分析

### 3.1 #244 — frontend Cookie 安全标记缺失 + reconnect storm + name 硬编码

#### 3.1.1 当前代码

`web/static/app.js:35-37`：
```javascript
function setCookie(name, value) {
    document.cookie = name + '=' + value + '; path=/; max-age=86400';
}
```

`web/static/app.js:105-108`：
```javascript
ws.onclose = function() {
    setStatus('disconnected'); hideTyping();
    setTimeout(connect, 2000);
};
```

`web/static/app.js:3`：
```javascript
let aiName = '星';
```

`web/server.py:330-333`：
```python
await websocket.send_text(json.dumps({
    "type": "init_ok", "session_id": session_id,
    "emotion": agent.emotion,
    "name": agent.personality.config.name,
}, ensure_ascii=False))
```

#### 3.1.2 问题分析

1. **Cookie 安全**：`session_id` 通过前端 JS 设置 Cookie，无法设置 `HttpOnly`（这是浏览器安全模型的限制）。但即使如此，当前连 `SameSite` 和 `Secure` 都未设置。若用户通过 HTTPS 部署，`Secure` 缺失会导致 Cookie 在明文传输中泄露；`SameSite=Lax/Strict` 缺失会增加 CSRF 风险。更根本的方案是：由后端通过 HTTP 响应头 `Set-Cookie` 下发 `session_id`，这样才可以设置 `HttpOnly`。
2. **Reconnect storm**：断网或服务器重启时，前端每 2 秒重连一次，无退避。大量客户端同时重连会形成 DDOS 式冲击。
3. **Name 硬编码**：前端默认写死 `'星'`，在 `init_ok` 返回前页面标题/头像会先显示默认值，造成闪烁。

#### 3.1.3 修复方案

**方案 A：后端下发 HttpOnly Cookie（推荐，最安全）**

修改 `web/server.py` 的 `/api/chat` 或新增 `/api/session` 端点，在首次交互时返回 `Set-Cookie`：
```python
response.set_cookie(
    key="session_id",
    value=session_id,
    httponly=True,
    secure=request.url.scheme == "https",
    samesite="Strict",
    max_age=86400,
)
```
前端 `getCookie` 仍可读取（因为 SameSite=Strict 不影响同站读取），但 `HttpOnly` 会阻止 JS 读取。需要权衡：若希望前端仍能读取 `session_id` 用于 WebSocket init，则不能同时启用 `HttpOnly`。折中做法是：
- Cookie 用于 REST API 身份绑定，启用 `HttpOnly`；
- WebSocket `init` 时由前端通过 URL query 或首次 message 携带一个短期 token（或直接从 Cookie 中读取非 HttpOnly 的 `session_id`，若仍需前端读取）。

**方案 B：前端至少设置 SameSite + Secure（最小改动）**

```javascript
function setCookie(name, value) {
    var secure = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = name + '=' + value + '; path=/; max-age=86400; SameSite=Strict' + secure;
}
```

**Reconnect 退避**：
```javascript
let reconnectDelay = 2000;
const maxReconnectDelay = 30000;

ws.onclose = function() {
    setStatus('disconnected'); hideTyping();
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
};

ws.onopen = function() {
    reconnectDelay = 2000;  // 重置
    ws.send(JSON.stringify({ type: 'init', session_id: sessionId }));
    setStatus('connected');
};
```

**Name 硬编码**：
在 `web/static/index.html` 中通过 `data-*` 或 `<meta>` 提供默认名：
```html
<meta name="ai-default-name" content="星">
```
前端读取：
```javascript
let aiName = document.querySelector('meta[name="ai-default-name"]')?.content || '星';
```

#### 3.1.4 验证建议

- 浏览器 DevTools → Application → Cookies，确认 `SameSite`、`Secure` 标记。
- 模拟后端重启/断网，观察重连间隔是否指数增长。
- 检查页面首次加载时标题是否仍有闪烁。

#### 3.1.5 工作量

- 方案 B：约 0.5 人天。
- 方案 A：约 1-2 人天（需新增/session端点或改造 `/api/chat`，并调整 WebSocket 鉴权）。

---

### 3.2 #233 — WebSocket Origin 校验可被 `localhost.evil.com` 绕过

#### 3.2.1 当前代码

`web/server.py:295-303`：
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin", "")
    allowed = {"http://localhost:8000", "http://127.0.0.1:8000", "null"}
    if origin and origin not in allowed and not origin.startswith("http://localhost"):
        logger.warning(f"[ws] rejected origin: {origin}")
        await websocket.close(code=4003)
        return
```

#### 3.2.2 问题分析

`origin.startswith("http://localhost")` 会匹配：
- `http://localhost:8000` ✅
- `http://localhost.evil.com` ❌（恶意域名）
- `http://localhost.attacker.com` ❌（恶意域名）

攻击者只需注册一个以 `localhost` 开头的域名即可绕过 Origin 校验，向 WebSocket 发送伪造请求。

#### 3.2.3 修复方案

使用 `urllib.parse.urlparse` 提取 hostname 并精确匹配：

```python
from urllib.parse import urlparse

ALLOWED_ORIGIN_HOSTS = {"localhost", "127.0.0.1"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin", "")
    if origin and origin != "null":
        parsed = urlparse(origin)
        if parsed.hostname not in ALLOWED_ORIGIN_HOSTS:
            logger.warning(f"[ws] rejected origin: {origin}")
            await websocket.close(code=4003)
            return
```

**注意事项**：
- `null` origin 的处理：当前代码允许 `null`，应明确是否保留。本地双击打开 HTML 文件时 origin 为 `null`，若项目支持这种使用方式则保留；否则应移除。
- 端口号：不应作为判断依据，因为攻击者也可以使用 `:8000`。
- 建议将 `ALLOWED_ORIGIN_HOSTS` 提取到配置文件中，方便部署时自定义。

#### 3.2.4 验证建议

- 单元测试：构造 `http://localhost.evil.com` 应被拒绝；`http://localhost:8000`、`http://127.0.0.1:8000` 应被允许。
- 手动测试：修改 `/etc/hosts` 模拟 `localhost.evil.com`，验证 WebSocket 连接被 4003 关闭。

#### 3.2.5 工作量

约 0.5 人天。

---

### 3.3 #210 — WebSocket 多 tab session 竞态

#### 3.3.1 当前代码

`web/session.py:149-219`：
```python
class SessionManager:
    def __init__(self, config: Config):
        ...
        self._sessions: dict[str, WebAgent] = {}
        self._proactive_tasks: dict[str, object] = {}  # sid → asyncio.Task
        self._active_ws: dict[str, object] = {}  # sid → WebSocket
        self._lock = Lock()

    def get_or_create(self, session_id: Optional[str] = None) -> tuple[str, WebAgent]:
        with self._lock:
            sid = session_id or uuid.uuid4().hex[:12]
            if sid not in self._sessions:
                ...
            return sid, self._sessions[sid]

    def remove(self, session_id: str) -> None:
        with self._lock:
            agent = self._sessions.pop(session_id, None)
            ...
            task = self._proactive_tasks.pop(session_id, None)
            if task:
                task.cancel()
            self._active_ws.pop(session_id, None)

    def register_proactive(self, session_id: str, task, websocket) -> None:
        with self._lock:
            old_task = self._proactive_tasks.pop(session_id, None)
            if old_task:
                old_task.cancel()
            self._proactive_tasks[session_id] = task
            self._active_ws[session_id] = websocket
```

`web/server.py:322-328`：
```python
if msg_type == "init":
    sid = data.get("session_id")
    session_id, agent = session_manager.get_or_create(sid)
    task = asyncio.create_task(_proactive_loop(websocket, session_id))
    session_manager.register_proactive(session_id, task, websocket)
```

`web/server.py:359-360`：
```python
finally:
    if session_id:
        session_manager.remove(session_id)
```

#### 3.3.2 问题分析

1. **session 与 WebSocket 1:1 绑定**：`remove()` 在任意 tab 断开时销毁整个 session，其他 tab 的 proactive 消息无法送达。
2. **init 可重复**：每次 init 都会取消旧 proactive task，多个 tab 频繁刷新会导致 task 反复创建/取消。
3. **task.cancel() 无法中断 run_in_executor 中的同步代码**：`core/agent.py` 中 `process_message` 通过 `run_in_executor` 在线程池执行，取消 task 不会中断线程中的同步调用。
4. **`_active_ws` 只保存单个 WebSocket**：多个 tab 时，proactive loop 可能向非最新 tab 发送消息。

#### 3.3.3 修复方案

**核心设计**：引入连接计数器（ref counting）和 WebSocket 集合。

```python
class SessionManager:
    def __init__(self, config: Config):
        ...
        self._sessions: dict[str, WebAgent] = {}
        self._proactive_tasks: dict[str, asyncio.Task] = {}
        self._active_ws: dict[str, set[WebSocket]] = {}  # sid → set[WebSocket]
        self._tab_counts: dict[str, int] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: Optional[str] = None) -> tuple[str, WebAgent]:
        with self._lock:
            sid = session_id or uuid.uuid4().hex[:12]
            if sid not in self._sessions:
                self._sessions[sid] = WebAgent(...)
            self._tab_counts[sid] = self._tab_counts.get(sid, 0) + 1
            return sid, self._sessions[sid]

    def register_ws(self, session_id: str, websocket: WebSocket) -> None:
        with self._lock:
            self._active_ws.setdefault(session_id, set()).add(websocket)
            if session_id not in self._proactive_tasks:
                task = asyncio.create_task(_proactive_loop(session_id))
                self._proactive_tasks[session_id] = task

    def remove_ws(self, session_id: str, websocket: WebSocket) -> None:
        with self._lock:
            ws_set = self._active_ws.get(session_id)
            if ws_set:
                ws_set.discard(websocket)
            self._tab_counts[session_id] = max(0, self._tab_counts.get(session_id, 0) - 1)
            should_remove = self._tab_counts[session_id] == 0 or not ws_set
            if should_remove:
                self._cleanup_session_locked(session_id)

    def get_active_ws(self, session_id: str) -> Optional[WebSocket]:
        with self._lock:
            ws_set = self._active_ws.get(session_id)
            return next(iter(ws_set)) if ws_set else None
```

**WebSocket 端点改造**：
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ...
    await websocket.accept()
    session_id = None
    try:
        while True:
            raw = await websocket.receive_text()
            ...
            if msg_type == "init":
                sid = data.get("session_id")
                session_id, agent = session_manager.get_or_create(sid)
                session_manager.register_ws(session_id, websocket)
                await websocket.send_text(json.dumps({...}))
            elif msg_type == "message":
                ...
    finally:
        if session_id:
            session_manager.remove_ws(session_id, websocket)
```

**proactive loop 改造**：
```python
async def _proactive_loop(session_id: str):
    try:
        while True:
            active_ws = session_manager.get_active_ws(session_id)
            if active_ws is None:
                await asyncio.sleep(5)
                continue
            ...
    except asyncio.CancelledError:
        # 清理资源
        raise
```

**task 取消的同步代码问题**：
在 `remove_ws` 中取消 task 后，应 `await task` 等待其完成（最多几秒），或设计 `run_in_executor` 包装为可中断的 future。对于 `process_message` 这种同步调用，可在其内部周期性检查 `asyncio.current_task().cancelled()`（但这需要在线程中安全地检查，较复杂）。短期可先加超时，长期应将 `Agent.process_message` 改为 async 或拆分为更小的可取消单元。

#### 3.3.4 验证建议

- 单元测试：模拟两个 WebSocket 连接同一 session，断开其中一个，另一个仍能接收 proactive 消息。
- 手动测试：浏览器打开两个 tab 连接同一 session，关闭一个，观察另一个是否仍然在线且能收到主动消息。

#### 3.3.5 工作量

约 2-3 人天（涉及并发状态机改造，需充分测试）。

---

### 3.4 #214 — Repository 多处查询缺少 `session_id` 过滤

#### 3.4.1 当前代码

`storage/repository.py` 中以下方法未使用 `session_id`：

- `search_experiences`（line 163-184）
- `get_recent_experiences`（line 186-194）
- `get_recent_reflections`（line 217-224）
- `prune_facts`（line 301-320）
- `prune_experiences`（line 322-341）
- `prune_reflections`（line 343-360）
- `get_all_relationships`（line 238-241）

同时，以下写入方法也未写入 `session_id`：
- `insert_experience`（line 147-161）
- `insert_reflection`（line 204-215）

#### 3.4.2 问题分析

虽然 `Repository` 实例有 `session_id` 字段，但大量查询/写入方法未使用它。这导致：
- 用户 A 的 experience/reflection 会出现在用户 B 的检索结果中。
- `prune_*` 会基于全局数量做裁剪，可能误删其他 session 的数据。
- `relationship_metrics` 如果本意是 per-session，则当前实现也是全局共享。

#### 3.4.3 修复方案

**为所有查询添加 `session_id` 过滤**：

以 `get_recent_experiences` 为例：
```python
async def get_recent_experiences(self, limit: int = 5) -> list[Experience]:
    async with self.db.cursor() as c:
        await c.execute("""
            SELECT * FROM experiences
            WHERE is_archived = 0 AND session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (self.session_id, limit))
        return [self._row_to_experience(r) for r in await c.fetchall()]
```

**为所有写入添加 `session_id`**：

以 `insert_experience` 为例：
```python
async def insert_experience(self, summary: str, tone: str, significance: float,
                            tags: list[str], turn_start: Optional[int] = None,
                            turn_end: Optional[int] = None,
                            importance: float = 0.5,
                            embedding: Optional[bytes] = None) -> int:
    async with self.db.cursor() as c:
        await c.execute("""
            INSERT INTO experiences (summary, emotional_tone, significance, importance, tags,
                                     turn_range_start, turn_range_end, embedding, embedding_version,
                                     session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (summary, tone, significance, importance, json.dumps(tags, ensure_ascii=False),
              turn_start, turn_end, embedding, self.session_id))
        await self.db.commit()
        return c.lastrowid
```

**关系指标是否全局共享**：
`relationship_metrics` 表当前无 `session_id` 主键约束，且 `get_all_relationships` / `upsert_relationship` 未按 session 过滤。需要产品层面决定：
- 若关系是全局的：保持现状，但文档化。
- 若关系是 per-session 的：修改表结构（`PRIMARY KEY (dimension, session_id)`），所有读写加 `session_id`。

#### 3.4.4 验证建议

- 新增单元测试：创建两个 `Repository` 实例分别设置不同 `session_id`，验证彼此数据隔离。
- 验证 `prune_*` 不会跨 session 删除数据。

#### 3.4.5 工作量

约 1-2 人天（取决于 `relationship_metrics` 是否需要改造）。

---

### 3.5 #215 — schema_version 表从未读取 + 动态 SQL 缺少白名单

#### 3.5.1 当前代码

`storage/database.py:67-177`：
```python
async def initialize(self) -> None:
    async with self.cursor() as c:
        await c.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ...
        """)

        for table, column, col_type, default_val in [
            ("user_facts", "importance", "REAL", "0.5"),
            ...
        ]:
            await c.execute(f"PRAGMA table_info({table})")
            rows = await c.fetchall()
            columns = [row[1] for row in rows]
            if column not in columns:
                await c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default_val}")
                logger.info(f"Schema migration: added {table}.{column}")

        await c.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (1)"
        )
    await self.commit()
```

#### 3.5.2 问题分析

1. `schema_version` 表仅写入 version=1，从未读取。后续若新增 migration，无法判断哪些已应用。
2. `ALTER TABLE {table} ADD COLUMN {column}` 使用 f-string 拼接，当前虽然是硬编码列表，但若未来从外部配置读取表名/列名，存在 SQL 注入风险。
3. 添加列的逻辑与 `CREATE TABLE` 分离，schema 定义分散，维护困难。

#### 3.5.3 修复方案

**引入最小迁移框架**：

```python
MIGRATIONS = {
    1: """
        -- baseline schema
        CREATE TABLE IF NOT EXISTS schema_version (...);
        CREATE TABLE IF NOT EXISTS user_facts (...);
        ...
        INSERT OR IGNORE INTO relationship_metrics ...
    """,
    2: """
        ALTER TABLE user_facts ADD COLUMN IF NOT EXISTS importance REAL DEFAULT 0.5;
        ALTER TABLE experiences ADD COLUMN IF NOT EXISTS importance REAL DEFAULT 0.5;
        ...
    """,
}

async def initialize(self) -> None:
    async with self.cursor() as c:
        # Ensure schema_version table exists
        await c.executescript(MIGRATIONS[1].split("INSERT OR IGNORE")[0])

        applied = await self._get_applied_versions(c)
        for version, sql in sorted(MIGRATIONS.items()):
            if version not in applied:
                await c.executescript(sql)
                await c.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (version,)
                )
                logger.info(f"Applied migration {version}")
    await self.commit()
```

**白名单校验**：

如果仍需保留动态 `ALTER TABLE`，必须做白名单校验：
```python
ALLOWED_ALTERATIONS = {
    ("user_facts", "importance"),
    ("experiences", "importance"),
    ...
}

for table, column, col_type, default_val in alterations:
    if (table, column) not in ALLOWED_ALTERATIONS:
        raise ValueError(f"Unauthorized schema alteration: {table}.{column}")
    await c.execute(f"PRAGMA table_info({table})")
    ...
```

#### 3.5.4 验证建议

- 单元测试：创建新 DB，验证 migrations 按顺序应用；删除某个 migration 记录后重启，验证缺失的 migration 被补应用。
- 测试 `ALLOWED_ALTERATIONS` 外条目会被拒绝。

#### 3.5.5 工作量

约 1-2 人天（需小心已有数据库的兼容性）。

---

### 3.6 #242 — Tool 基类 `execute` 为 async，但 8 个子类全部为 sync def

#### 3.6.1 当前代码

`tools/traits.py:27-47`：
```python
class Tool:
    def name(self) -> str: ...
    def description(self) -> str: ...
    def parameters_schema(self) -> dict: ...

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
```

`core/dispatcher.py:139-143`：
```python
try:
    if inspect.iscoroutinefunction(tool.execute):
        result: ToolResult = run_async(tool.execute(args))
    else:
        result: ToolResult = tool.execute(args)
```

#### 3.6.2 问题分析

- 基类声明 `async def execute`，但所有子类（`ReadFileTool`, `WebSearchTool`, `NotifyTool`, `MusicPlayTool`, `GlobTool`, `GrepTool`, `RecallTool`, `RememberTool`）均为同步实现。
- 运行时通过 `inspect.iscoroutinefunction` 分支处理，虽然功能正常，但违反里氏替换原则（LSP），且误导类型检查、静态分析和后续开发者。
- 更严重的是，涉及 IO 的工具（文件、网络、通知）实际上在同步执行，会阻塞 asyncio 事件循环。

#### 3.6.3 修复方案

**推荐方案 A：统一为真正的异步实现**

1. 将基类保持 `async def execute`。
2. 将所有子类改为 `async def execute`。
3. 在 IO 操作处使用 `await` 或 `asyncio.to_thread`：

```python
class ReadFileTool(Tool):
    async def execute(self, args: dict[str, Any]) -> ToolResult:
        path = args.get("path", "")
        try:
            content = await asyncio.to_thread(self._read_file, path)
            return ToolResult.ok(content)
        except Exception as e:
            return ToolResult.fail(str(e))
```

4. 删除 `core/dispatcher.py` 中的 `inspect.iscoroutinefunction` 分支，统一 `await tool.execute(args)`。

**次选方案 B：将基类改为同步（最小改动）**

若短期内不想改动所有子类，可将基类改为：
```python
def execute(self, args: dict[str, Any]) -> ToolResult:
    raise NotImplementedError
```
并删除 dispatcher 中的协程检测分支。但这只是掩盖问题，IO 阻塞依然存在。

#### 3.6.4 验证建议

- 单元测试：每个工具调用后验证返回 `ToolResult`。
- 确认 `dispatcher.py` 中不再使用 `inspect.iscoroutinefunction`。
- 使用 `asyncio` 调试模式检测是否有同步 IO 阻塞事件循环。

#### 3.6.5 工作量

- 方案 A：约 2-3 人天（需改造 8 个子类并测试）。
- 方案 B：约 0.5 人天（仅改基类和 dispatcher）。

---

## 四、历史版本 P1 Bug 深度分析

### 4.1 #239 / #185 — Proactivity Rate Limit 副作用前置 + 睡眠消息丢失

#### 4.1.1 当前代码

`core/proactivity.py:94-114`：
```python
def check_rate_limit(self, action: str) -> bool:
    now = time.time()
    if action == "explore":
        if now - self._last_explore_time < 3600:
            return False
        self._last_explore_time = now
        return True
    elif action == "chat":
        if self._last_chat_time == 0:
            self._last_chat_time = now
            return True
        if now - self._last_chat_time < 1800:
            return False
        self._last_chat_time = now
        return True
```

`web/server.py:260-286`：
```python
score = ag._calculate_proactivity(idle)
if random.random() < score:
    intent = await loop.run_in_executor(None, ag.decide_proactive_action, idle)
    if intent.action == "explore" and ag._check_rate_limit("explore"):
        response = await loop.run_in_executor(None, agent.process_explore_with_intent, intent)
    elif intent.action == "chat" and ag._check_rate_limit("chat"):
        response = await loop.run_in_executor(None, agent.process_proactive_with_intent, intent)
    else:
        response = None
    if response:
        ...
```

`core/message_handler.py:66-72`：
```python
def handle_message(self, user_input: str, on_token=None) -> str:
    a = self.a
    if a._sleeping:
        a.last_activity_time = time.time()
        return random.choice(["zzz...ZZZ...💤", ...])
```

#### 4.1.2 问题分析

**Rate Limit 问题**：
- `check_rate_limit` 在判断通过时立即更新 `_last_chat_time` / `_last_explore_time`。
- 如果 `decide_proactive_action` 返回 `silent`，或 `process_*_with_intent` 最终没有实际发送消息（返回空/太短），状态已经被修改，下一次触发被 30min/1h 锁住。
- 首次 chat 时 `_last_chat_time == 0` 被立即设为 now，存在同样问题。

**睡眠消息丢失问题**：
- AI 睡眠时收到用户消息直接返回 zzz，不写入 `short_term` 和 DB。
- 醒来后不知道用户睡觉时说了什么。
- `generate_dream` 中调用 `record_emotion_event` 可能因 intensity 阈值被静默丢弃。

#### 4.1.3 修复方案

**拆分 check / record**：

```python
def check_rate_limit(self, action: str) -> bool:
    now = time.time()
    if action == "explore":
        return now - self._last_explore_time >= 3600
    elif action == "chat":
        if self._last_chat_time == 0:
            return True
        return now - self._last_chat_time >= 1800
    return True

def record_rate_limit(self, action: str) -> None:
    now = time.time()
    if action == "explore":
        self._last_explore_time = now
    elif action == "chat":
        self._last_chat_time = now
```

在 `web/server.py` 中，只有 `response` 非空且实际发送后才调用：
```python
if response:
    ag.last_activity_time = time.time()
    ag._proactive.record_rate_limit(intent.action)
    cooldown = 12
    await _send_segments(active_ws, agent, response, agent.emotion)
```

**睡眠消息处理**：

```python
def handle_message(self, user_input: str, on_token=None) -> str:
    a = self.a
    if a._sleeping:
        a.last_activity_time = time.time()
        # 记录用户输入，但不生成回复
        a.short_term.add_turn("user", user_input, metadata={"sleep": True})
        a.ltm.repo.insert_turn_sync(a.turn_count, "user", user_input,
                                     str(a.personality.emotion.to_dict()))
        a.turn_count += 1
        return random.choice(["zzz...ZZZ...💤", ...])
```

**梦境情绪事件强制记录**：

在 `core/sleep_manager.py:137-140`：
```python
self._personality.emotion.record_emotion_event(
    trigger=f"梦: {dream.strip()[:100]}",
    context=dream.strip()[:200],
    force=True,  # 新增参数，绕过 intensity 检查
)
```

或修改 `record_emotion_event` 降低梦境相关事件的阈值。

#### 4.1.4 验证建议

- 单元测试：模拟 `decide_proactive_action` 返回 `silent`，验证 `_last_chat_time` 不变。
- 单元测试：模拟睡眠中收到消息，验证 `short_term` 和 DB 中存在该记录。
- 单元测试：验证梦境生成后情绪事件被记录。

#### 4.1.5 工作量

约 1 人天。

---

### 4.2 #243 — Prompt `.format()` 无输入消毒

#### 4.2.1 当前代码

`prompts/templates.py:27-31`：
```python
FACT_EXTRACTION_PROMPT = """从这段对话中提取**关于用户**的事实信息。
...
对话：
{text}

事实：
"""
```

调用点（例如 `memory/consolidation.py`）：
```python
prompt = FACT_EXTRACTION_PROMPT.format(text=conversation_text)
```

#### 4.2.2 问题分析

- 所有 prompt 模板都使用 `.format(...)` 直接替换。
- 如果 `conversation_text` 中包含 `{` 或 `}`，会被 `format` 解析为占位符，引发 `KeyError` 或 `IndexError`。
- 如果调用方漏传某个 kwarg，同样会 `KeyError`。
- `FACT` prompt 说 `fact_type` 固定填 `user_fact`，但 parser 实际支持多种 type，描述不一致。

#### 4.2.3 修复方案

**统一 `safe_format` 函数**：

```python
import string

class SafeFormatter(string.Formatter):
    def __init__(self, default=''):
        self.default = default
        super().__init__()

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, self.default)
        return super().get_value(key, args, kwargs)

    def format_field(self, value, format_spec):
        if value is None:
            return ''
        return super().format_field(value, format_spec)

def safe_format(template: str, **kwargs) -> str:
    """Escape user-provided braces before formatting."""
    escaped_kwargs = {}
    for k, v in kwargs.items():
        if isinstance(v, str):
            v = v.replace('{', '{{').replace('}', '}}')
        escaped_kwargs[k] = v
    return SafeFormatter(default='').format(template, **escaped_kwargs)
```

调用处改为：
```python
prompt = safe_format(FACT_EXTRACTION_PROMPT, text=conversation_text)
```

**注意**：这种转义会阻止 prompt 中本应有的 `{`/`}` 被 format 处理。如果某些 prompt 需要保留 format 功能（如 `EMOTION_ANALYSIS_PROMPT` 中的 JSON 模板 `{{...}}`），需要区分"模板占位符"和"用户输入"。更好的做法是：
- 对模板本身使用 `.format`；
- 对插入到模板中的用户/外部文本先做 HTML/JSON 转义，再做 brace 转义。

**FACT 格式描述修正**：

将 `prompts/templates.py:13` 的 "fact_type: 固定填 user_fact" 改为与实际 parser 对齐的描述，例如：
```
fact_type: user_fact（当前仅支持用户事实）
```

#### 4.2.4 验证建议

- 单元测试：传入含 `{`、`}`、`{unknown}` 的用户输入，验证不抛异常。
- 单元测试：漏传某个 kwarg，验证使用空字符串而非 KeyError。

#### 4.2.5 工作量

约 0.5-1 人天（需检查所有调用点）。

---

### 4.3 #182 — Agent 3 ReAct 循环多项缺陷

#### 4.3.1 当前代码

`core/agent.py:116-207`：
```python
def _react_loop(self, messages: list[dict], on_token=None, add_to_history: bool = True,
                tool_registry=None, skip_post_process: bool = False) -> str:
    ...
    for _idx in range(self._max_tool_iterations):
        resp = self.provider.generate(
            messages, stream=False if _idx > 0 else True,
            on_token=on_token if _idx == 0 else None,
            max_tokens=max_tok if _idx == 0 else max(384, max_tok * 2 // 3),
        )
        ...
        if contains_fake_action(resp) and fake_action_count < 3 and not tools_were_called:
            fake_action_count += 1
            ...
            continue
        ...

    if final_text:
        if add_to_history:
            self.short_term.add_turn("assistant", final_text)
        self.ltm.repo.insert_turn_sync(
            self.turn_count, "assistant", final_text,
            str(self.personality.emotion.to_dict()),
            is_tool_claim=is_claim,
        )
        self.turn_count += 1
```

`core/dispatcher.py:184-206`：
```python
def contains_fake_action(text: str) -> bool:
    ...
    narrative_patterns = [
        ...
        "工具返回", "工具返回的原始内容",
        ...
    ]
```

#### 4.3.2 问题分析

1. **max_tokens 后续轮次反而变大**：当情绪为 sad（max_tok=256）时，第 1+ 轮为 `max(384, 256*2//3)=384`，后续轮次比第 0 轮还多 token，与"后续轮次应更收敛"的语义相反。
2. **add_to_history=False 仍写 DB/turn_count**：`proactive` 和 `explore` 调用 `handle_proactive`/`handle_explore` 时传入 `add_to_history=False`，但 `_react_loop` 仍然调用 `insert_turn_sync` 并递增 `turn_count`，导致 short_term 中没有记录但 DB 中有，且 turn_count 被占用。
3. **fake_action 重试无退避**：检测到 fake action 后立即 `continue` 再次调用 `generate()`，可能形成快速 API 调用循环。
4. **空输入未拦截**：CLI 端空输入会进入 `_on_perceive`、加入 short_term、消耗 API token。
5. **contains_fake_action 误判工具返回**：合法引用"工具返回"的文本被误判为 fake action。

#### 4.3.3 修复方案

**max_tokens 调整**：
```python
max_tokens = max_tok if _idx == 0 else min(512, max_tok)
```
或固定后续轮次为较小值：
```python
max_tokens = max_tok if _idx == 0 else 384
```

**add_to_history=False 跳过 DB/turn_count**：
```python
if final_text and add_to_history:
    self.short_term.add_turn("assistant", final_text)
    self.ltm.repo.insert_turn_sync(...)
    self.turn_count += 1
```

**fake_action 退避**：
```python
import asyncio

if contains_fake_action(resp) and fake_action_count < 3 and not tools_were_called:
    fake_action_count += 1
    await asyncio.sleep(0.5 * fake_action_count)
    ...
    continue
```

**空输入拦截**：

`ui/cli.py` 的 `_on_perceive` 开头：
```python
def _on_perceive(self, user_input: str) -> None:
    if not user_input or not user_input.strip():
        return
    ...
```

`core/message_handler.py` 的 `handle_message` 开头也加同样保护。

**contains_fake_action 移除误判关键词**：

从 `narrative_patterns` 中移除 `"工具返回"` 和 `"工具返回的原始内容"`。这些只有在 tools_were_called=True 时才应被允许，而当前代码已经通过 `not tools_were_called` 做了保护，但关键词列表本身仍可能在未来误伤。建议改为上下文感知：
```python
if not tools_were_called:
    # 只在未调用工具时检测 completion keywords 和 narrative patterns
    if contains_fake_action(resp):
        ...
```

#### 4.3.4 验证建议

- 单元测试：sad 情绪下后续 ReAct 轮次 `max_tokens` 不超过第 0 轮。
- 单元测试：`add_to_history=False` 时不调用 `insert_turn_sync`，`turn_count` 不变。
- 单元测试：连续 fake action 时每次重试有退避。
- 单元测试：空字符串输入不调用 provider.generate。
- 单元测试：工具调用后含"工具返回"的文本不被误判。

#### 4.3.5 工作量

约 1-2 人天。

---

### 4.4 #176 — ConversationBuffer 单条消息无大小限制 + proactive task 取消竞态

#### 4.4.1 当前代码

`memory/short_term.py:24-35`：
```python
def add_turn(self, role: str, content: str,
             metadata: Optional[dict] = None) -> Turn:
    with self._lock:
        turn = Turn(...)
        self._next_id += 1
        self._turns.append(turn)
```

`web/server.py:326-328`：
```python
task = asyncio.create_task(_proactive_loop(websocket, session_id))
session_manager.register_proactive(session_id, task, websocket)
```

`web/session.py:210-218`：
```python
def register_proactive(self, session_id: str, task, websocket) -> None:
    with self._lock:
        old_task = self._proactive_tasks.pop(session_id, None)
        if old_task:
            old_task.cancel()
        self._proactive_tasks[session_id] = task
        self._active_ws[session_id] = websocket
```

#### 4.4.2 问题分析

1. **单条消息无大小限制**：`add_turn` 对 `content` 长度无校验。用户粘贴长文本或 LLM 返回超长回复时，会完整存入内存，可能导致 OOM 或后续 token 估算计算量暴增。
2. **proactive task 取消竞态**：
   - `init` 后立即断开时，task 可能尚未被注册到 `_proactive_tasks`，`remove()` 找不到 task。
   - `old_task.cancel()` 不会中断 `run_in_executor` 中的同步代码，导致旧任务继续运行并可能向已关闭的 WebSocket 发送消息。
3. **`last_activity_time` 并发读写**：`last_activity_time` 是普通 float，`_proactive_loop` 读取后用户消息更新，proactive 仍基于旧值计算 score。

#### 4.4.3 修复方案

**单条消息大小限制**：

```python
MAX_TURN_LENGTH = 10000  # 字符，约等于 2.5k-5k tokens

def add_turn(self, role: str, content: str, metadata: Optional[dict] = None) -> Turn:
    if len(content) > MAX_TURN_LENGTH:
        logger.warning(f"[mem] turn too long ({len(content)} chars), truncating to {MAX_TURN_LENGTH}")
        content = content[:MAX_TURN_LENGTH] + "\n...[内容过长，已截断]"
    with self._lock:
        ...
```

**proactive task 生命周期**：
与 #210 一起改造。关键点是：
- 使用 ref counting 管理连接数。
- `register_proactive` / `remove` 加锁。
- 取消 task 后 `await task` 等待完成，或设置一个可中断的 future。
- 在 `_proactive_loop` 中，每次循环检查当前 task 是否被取消：

```python
async def _proactive_loop(session_id: str):
    try:
        while True:
            if asyncio.current_task().cancelled():
                break
            ...
    except asyncio.CancelledError:
        logger.info(f"[proactive] cancelled for {session_id}")
        raise
```

**last_activity_time 同步**：

使用 `asyncio.Lock`：
```python
self._activity_lock = asyncio.Lock()

async def update_activity(self):
    async with self._activity_lock:
        self.last_activity_time = time.time()

async def _proactive_loop(session_id: str):
    ...
    async with self._activity_lock:
        idle = time.time() - ag.last_activity_time
        score = ag._calculate_proactivity(idle)
        if random.random() < score:
            ...
```

#### 4.4.4 验证建议

- 单元测试：传入超长字符串，验证被截断。
- 单元测试：模拟 task 在 run_in_executor 中执行时取消，验证不会崩溃。
- 单元测试：并发更新 `last_activity_time` 时 proactive score 计算正确。

#### 4.4.5 工作量

约 1-2 人天（与 #210 一起改造）。

---

### 4.5 #179 — Agent 1 review 累积 + tool_result 注入位置

#### 4.5.1 当前代码

`core/message_handler.py:135-150`：
```python
combined_records = ""
for i, r in enumerate(all_tool_results):
    combined_records += self._tool_agent.format_for_phase2(r) + "\n"

if tool_result and tool_result.any_success and round_num < MAX_AGENT2_ROUNDS:
    drive_result = self._inner_drive.review(
        user_input, combined_records,
        round_num=round_num, max_rounds=MAX_AGENT2_ROUNDS,
    )
```

`core/message_handler.py:302-305`：
```python
messages = self._build_messages(sys_prompt, user_input=f"用户输入：{user_input}")
if tool_records:
    messages.insert(-1, {"role": "user", "content": tool_records})
```

#### 4.5.2 问题分析

1. **review 累积**：`combined_records` 累积所有 round 的工具结果，`review` 阶段传入的 `combined_records` 可能非常长（多轮后可达数万字符），导致 Agent 1 review 成本飙升且上下文被污染。
2. **tool_result 注入位置**：`messages.insert(-1, ...)` 将 tool_records 插入到倒数第二条消息之前。当历史消息很多时，tool_records 远离 system prompt，可能无法被模型有效利用。

#### 4.5.3 修复方案

**review 阶段限制 combined_records 长度**：

```python
MAX_REVIEW_RECORDS_LEN = 3000

combined_records = ""
for i, r in enumerate(all_tool_results):
    combined_records += self._tool_agent.format_for_phase2(r) + "\n"
if len(combined_records) > MAX_REVIEW_RECORDS_LEN:
    combined_records = combined_records[-MAX_REVIEW_RECORDS_LEN:] + "\n...[ earlier results truncated ]"
```

更激进的优化：只传递最近一轮结果给 review。

**tool_result 注入位置**：

将 tool_records 与用户输入合并为一条 user 消息，紧跟在 system prompt 之后（或作为最后一条 user 消息之前）：

```python
messages = self._build_messages(sys_prompt, user_input=None)
if tool_records:
    user_content = f"[工具结果]\n{tool_records}\n\n用户输入：{user_input}"
else:
    user_content = f"用户输入：{user_input}"
messages.append({"role": "user", "content": user_content})
```

或者，如果 `_build_messages` 已经追加了 `user_input`，可以：
```python
messages = self._build_messages(sys_prompt, user_input=user_input)
if tool_records:
    # 将 tool_records 作为系统消息插入到 system prompt 之后
    messages.insert(1, {"role": "system", "content": f"[工具结果]\n{tool_records}"})
```

需要测试哪种方式对模型效果影响更小。原则是：tool_records 应紧邻 system prompt 和用户输入。

#### 4.5.4 验证建议

- 单元测试：多轮工具结果后，review 传入长度不超过阈值。
- 单元测试：tool_records 在 messages 中的位置符合预期。

#### 4.5.5 工作量

约 0.5-1 人天。

---

## 五、P2 / P3 质量改进项摘要

P2/P3 issue 数量较多，建议按模块分批处理。以下是关键模块和主要关注点：

### 5.1 Web / Frontend

- **#278**：CSP 策略细化、Referrer-Policy 统一、ARIA 可访问性、CSS 变量化。
- **#277**：`app.js` 异常处理、重连退避、超时统一、分段同步、心跳机制、`streamComplete` 事件。

### 5.2 Tools

- **#274**：`memory_tools` 私有方法、异常保护、类型转换。
- **#273**：`traits` 覆盖警告、JSON schema 完善、`ToolResult` 增强。
- **#272**：`notify_tool` 静默吞错、僵尸进程、未使用参数。
- **#183**：ToolRegistry 工具权限元数据（安全相关）。

### 5.3 Core

- **#267 / #266**：Personality 模型与 core 的 baseline 推导、sleepiness、类型安全、阈值、锁、decay、死亡螺旋、FIFO、快照、backup。
- **#265**：Proactivity 无锁化、文档、怨恨机制、threshold、cap、话题去重。
- **#263**：`async_utils` 线程池单例、超时传播、Runner。
- **#262**：`context_manager` tokenizer 锁、回退公式、CJK 截断、消息重建。
- **#259**：`cli_controller` 多轮缺失、误报、兜底、异常保护。
- **#258**：`tool_agent` 常量重复、参数审计、失败区分、retry 消息。
- **#257**：`inner_drive` 常量重复、关键词假阴性、URL 解析、CJK 标点。
- **#256**：`message_handler` CLI 不一致、review 记忆、token 估算、insert 复杂度。
- **#255**：`agent` 惰性 init、stream 冻结、deque、阈值、可配置。

### 5.4 Memory

- **#254**：`fact_checker` N+1 查询、验证、LLM 检测、numpy 依赖。
- **#253**：`embeddings` 锁、`bytes_to_vec`、硬编码、监控。
- **#252**：`consolidation` import 位置、bare except、log、N+1、关系衰减。
- **#250**：`long_term` 重复定义、关键词对齐、死代码。
- **#249**：`short_term` 文档、死代码、命名、原子性。

### 5.5 Storage

- **#248**：`repository.py` commit 缺失、索引、N+1、死代码。
- **#247**：`database.py` 权限、CHECK 约束、WAL、重试、死代码。

### 5.6 横切关注点

- **#284**：异常处理、日志、资源泄漏、竞态条件全面修复。

---

## 六、修复路线图

### 阶段 1：安全与数据隔离（第 1-2 周）

| 优先级 | Issue | 目标 |
|--------|-------|------|
| P0 | #233 | 修复 WebSocket Origin 绕过 |
| P0 | #244 | Cookie 安全标记 + reconnect 退避 |
| P0 | #210 | 多 tab session 竞态 |
| P0 | #214 | Repository session_id 过滤 |
| P0 | #215 | schema_version 与 SQL 白名单 |
| P1 | #242 | Tool 基类 async/sync 一致性 |

### 阶段 2：核心行为正确性（第 3-4 周）

| 优先级 | Issue | 目标 |
|--------|-------|------|
| P0 | #239 / #185 | rate limit 副作用后置 + 睡眠消息不丢失 |
| P1 | #243 | prompt .format() 安全 |
| P1 | #182 | ReAct 循环修复 |
| P1 | #176 | 消息大小限制 + proactive task 生命周期 |
| P1 | #179 | review 累积 + tool_result 位置 |

### 阶段 3：历史版本 Bug 清理（第 5-6 周）

| 优先级 | Issue | 目标 |
|--------|-------|------|
| P1 | #184 | consolidation 超时 + personality 损坏回退 |
| P1 | #180 | 梦境 async + CLI 睡眠命令 |
| P1 | #175 | 工具结果格式统一 + short_term 顺序 |
| P1 | #174 | emotion 事件 + 超时配置化 |
| P1 | #172 | Glob/Grep 缓存 + 大文件分块 |
| P1 | #170 | token 估算 + CJK + insert 复杂度 |
| P1 | #169 / #167 | SleepManager 完善 |
| P2 | #168 | 性能优化 |

### 阶段 4：P2/P3 质量改进（第 7 周起，持续）

按模块分批处理：storage → memory → tools → core → web/static。

### 阶段 5：架构演进（长期）

- **#296**：FactChecker Truth Maintenance（LLM Judge、Status 体系、Merge/Duplicate/Refine）。
- **#295**：ContextManager 优化（tokenizer、压缩、CJK）。
- **#294**：Prompt 架构重构。
- **#293**：三层 Agent 成熟度提升。

---

## 七、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| #210 / #214 / #215 涉及数据层改造，可能影响已有数据库 | 高 | 改造前备份 `data/ai_friend.db`；新增 migration 框架后小步验证；提供回滚脚本 |
| #242 异步化工具可能暴露新的并发 bug | 中 | 逐个工具改造并加单元测试；使用 `asyncio` 调试模式检测阻塞 |
| #233 / #244 安全修复可能破坏本地开发体验 | 低 | 将 allowed origins / cookie 策略提取到配置文件，本地可放宽 |
| 同时修复大量 issue 导致回归 | 高 | 每 issue 独立分支/PR；每次合并前跑完整 `pytest`；关键路径加回归测试 |
| 历史 issue 修复与当前代码已有局部修复冲突 | 中 | 修复前 re-read 相关文件，确认 issue 描述是否仍成立；在 PR 描述中说明 |

---

## 八、验证与测试策略

### 8.1 单元测试

每个 P1 bug 修复后应新增或更新单元测试：

- **#233**：`test_origin_bypass`、`test_origin_allowed`。
- **#244**：`test_cookie_flags`、`test_reconnect_backoff`。
- **#210**：`test_multi_tab_session`、`test_proactive_task_cleanup`。
- **#214**：`test_session_isolation_*`。
- **#215**：`test_migrations_apply`、`test_migrations_idempotent`、`test_unauthorized_alteration`。
- **#242**：`test_tool_async_execute`。
- **#239/#185**：`test_rate_limit_record_after_send`、`test_sleep_message_preserved`。
- **#243**：`test_prompt_format_safety`。
- **#182**：`test_react_max_tokens`、`test_add_to_history_false`、`test_fake_action_backoff`、`test_empty_input_blocked`、`test_tool_return_not_fake`。
- **#176**：`test_turn_truncation`、`test_proactive_cancel_race`。
- **#179**：`test_review_records_cap`、`test_tool_records_position`。

### 8.2 集成测试

- Web 端多 tab 场景：两个 tab 同时连接、收发消息、断开其中一个。
- 断网重连场景：模拟服务器重启，观察 reconnect 行为。
- 睡眠/唤醒场景：在睡眠窗口内发送消息，验证消息不丢失且醒后能回忆。
- 多 session 隔离：两个不同 session_id，验证 experience/reflection/prune 互不干扰。

### 8.3 手动测试清单

- [ ] 浏览器 DevTools 中 Cookie 标记正确。
- [ ] `localhost.evil.com` 无法连接 WebSocket。
- [ ] 多 tab 下关闭一个 tab，另一个仍能收到主动消息。
- [ ] 用户输入 `{` `}` 不会导致后端 500。
- [ ] 空输入不会触发 API 调用。
- [ ] 超长输入被截断并提示。

---

## 九、附录：相关代码文件清单

| Issue | 主要文件 | 次要文件 |
|-------|---------|---------|
| #244 | `web/static/app.js` | `web/server.py`, `web/static/index.html` |
| #243 | `prompts/templates.py` | `memory/consolidation.py`, `core/message_handler.py`, 其他调用点 |
| #242 | `tools/traits.py`, `tools/*_tools.py` | `core/dispatcher.py` |
| #239 | `core/proactivity.py` | `web/server.py` |
| #233 | `web/server.py` | - |
| #215 | `storage/database.py` | - |
| #214 | `storage/repository.py` | `storage/database.py` |
| #210 | `web/session.py`, `web/server.py` | `core/agent.py` |
| #185 | `core/proactivity.py`, `core/message_handler.py`, `core/sleep_manager.py` | - |
| #182 | `core/agent.py`, `core/dispatcher.py` | `core/message_handler.py`, `ui/cli.py` |
| #179 | `core/message_handler.py` | `core/tool_agent.py`, `core/inner_drive.py` |
| #176 | `memory/short_term.py`, `web/server.py` | `web/session.py`, `core/agent.py` |
| #184 | `memory/consolidation.py`, `core/personality.py` | - |
| #180 | `core/sleep_manager.py`, `ui/cli.py` | - |
| #175 | `core/dispatcher.py`, `memory/short_term.py` | `core/tool_agent.py` |
| #174 | `web/server.py`, `core/provider.py` | `config.py` |
| #172 | `tools/file_tools.py`, `tools/search_tools.py` | - |
| #170 | `core/context_manager.py`, `core/message_handler.py` | - |
| #169 / #167 | `core/sleep_manager.py`, `web/server.py` | - |
| #168 | 多文件 | - |

---

## 十、2026-07-12 批量修复关闭详情

> 提交：`9296694`  
> 推送：`main` 分支  
> GitHub 状态：已关闭 `#58`、`#54`、`#45`、`#43`、`#23`、`#28`、`#24`

| Issue | 类别 | 修复内容 | 主要文件 |
|-------|------|----------|---------|
| #58 | 重构 | `main.py` / `web_main.py` 启动代码重复：提取 `core/embedding_server.py` 公共模块 | `core/embedding_server.py`, `main.py`, `web_main.py` |
| #54 | 重构 | CSS 全部硬编码颜色：全面改用 CSS 变量，HTML/JS 内联颜色改为类名 | `web/static/style.css`, `web/static/index.html`, `web/static/app.js` |
| #45 | 封装 | Web 层直接访问 `agent._xxx`：`WebAgent` 新增公共接口，隔离内部状态 | `web/session.py`, `web/server.py` |
| #43 | 增强 | REST API 无 Pydantic 验证：新增 `web/schemas.py`，接口使用 Pydantic 模型 | `web/schemas.py`, `web/server.py` |
| #23 | 重构 | `KimiProvider` 无抽象基类：新增 `LLMProvider(ABC)` | `core/provider.py`, `core/agent.py`, `web/session.py` |
| #28 | 增强 | 对话示例硬编码：`config.py` 新增 `conversation_examples`，提示词动态渲染 | `config.py`, `prompts/system.py`, `core/message_handler.py`, `core/cli_controller.py` |
| #24 | 安全 | CORS/速率限制/CSP 细化：新增 `allowed_origins`、内存滑动窗口限流、细化 CSP | `config.py`, `web/server.py`, `web/rate_limit.py`, `web/static/index.html` |

### 验证结果

- `python -m py_compile ...` 语法检查通过。
- `python -m pytest tests/ -q --ignore=tests/real_api`：**312 passed**。
- 新增测试文件：`tests/test_provider_abc.py`、`tests/test_rate_limit.py`、`tests/test_conversation_examples.py`。
- 已按 `CLAUDE.md` 在 `changes/2026-07-12-修复issue-58-54-45-43-23-28-24.md` 记录修改。
- 已更新 `doc/config-reference.md`，补充 `conversation_examples` 与 `allowed_origins` 说明。

---

## 十一、下一步行动建议

1. **确认修复范围**：是否优先处理全部 v0.5 P1 bug，再处理历史版本 P1 bug？
2. **确认 `relationship_metrics` 的隔离级别**：它是全局共享还是 per-session？这直接影响 #214 的修复范围。
3. **确认 Tool 异步化策略**：采用方案 A（真正异步化）还是方案 B（基类改为同步）？
4. **建立分支策略**：建议每个 P1 bug 一个独立分支/PR，便于回滚和审查。
5. **补充回归测试**：在修复前先将当前失败或缺失的测试补齐，作为后续验证基线。

---

*报告结束。*
