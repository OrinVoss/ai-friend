# 启动流程

> 从 `python web_main.py` 到 AI 开始聊天的每一步代码发生了什么。
> CLI 模式的启动流程与此基本一致，差异见文末对照。

---

## 整体框图

```
python web_main.py
       │
       ├── 1. setup_logging("INFO") → load_config()（随 web.server 导入触发）
       │      → setup_logging(config.log_level) ── logs/YYYY-MM-DD.log
       ├── 2. auto_start_embedding() ── llama.cpp 嵌入服务
       │
       └── 3. uvicorn.run("web.server:app")
                │
                ├── 3a. FastAPI 模块加载（静态）
                │   ├── 中间件链（鉴权 → 安全头 → CORS → RateLimit）
                │   ├── 路由表注册（/api/*、/ws、/static/*）
                │   └── SessionManager、RateLimiter 实例化
                │
                ├── 3b. lifespan() 异步启动
                │   ├── 日志重初始化
                │   ├── session_manager.open() 打开数据库（自动迁移 schema）
                │   └── 后台 session 清理协程（5min 间隔）
                │
                └── 3c. Uvicorn 监听 0.0.0.0:8000 ── 等待请求
```

---

## 逐步骤详解

### Step 1: 配置加载 — `config.py`

```python
# web_main.py:19 — 导入即触发 web.server 模块级唯一的 load_config()（全进程单例，L-10/L-12）
from web.server import config
```

`Config` dataclass 从三个来源合并：
1. **默认值**（定义在 `config.py` 的 dataclass 字段默认值）
2. **`config.json`**（JSON 文件，覆盖默认值）
3. **环境变量**（`DEEPSEEK_API_KEY` 等，优先级最高）

关键字段：
- `api_key` / `api_endpoint` / `api_model` — LLM 调用
- `embedding_endpoint` / `embedding_dim` — 语义搜索
- `personality_file` — **模板**角色文件，仅新建角色时用
- `allowed_origins` — HTTP CORS + WebSocket Origin 白名单
- `allowed_read_paths` — 工具（glob/read_file）可访问的目录

### Step 2: 日志初始化 — `core/logging_setup.py`

```python
# web_main.py:16 先以 INFO 初始化（避免丢失 load_config 的启动日志，M-19）
# web_main.py:20 配置就绪后按 log_level 重设
setup_logging(config.log_level)
```

- 日志文件：`logs/YYYY-MM-DD.log`
- 日志级别：默认 `INFO`，`DEBUG` 可查看工具调用细节
- 同时输出到 stderr（uvicorn 终端）

### Step 3: 嵌入服务启动 — `core/embedding_server.py`

```python
# web_main.py:23（H-04：传入配置的 endpoint，启动端口与连接端口一致）
auto_start_embedding(logger, config.embedding_endpoint)
```

| 条件 | 行为 |
|------|------|
| `embedding_endpoint`（默认 `http://localhost:8080/v1/embeddings`，可用环境变量 `AI_FRIEND_EMBEDDING_ENDPOINT` 覆盖）已有响应 | 跳过 |
| `memory/Qwen3.5-0.8B-Q6_K.gguf` 模型文件存在 | 先清理残留 llama-server 进程，再优先运行 `start_embedding_server.bat`；不存在则 `subprocess.Popen` 直接启动 `memory/llama-bin/llama-server.exe`（端口从 endpoint 派生，解析失败兜底 8080） |
| 模型文件不存在 | 仅记录 info，**不阻塞启动** |

就绪等待在后台守护线程进行（每秒轮询，最多 90 秒），不阻塞主启动流程；
完成后日志输出 `[embed] server ready`，然后看门狗从 `_watch_then_guard` 接管生命周期（每 30 秒探活，3 次失败自动 kill+重启）。
CLI 与 Web 入口共用 `core/embedding_server.py`。
不可用时自动降级为纯关键词搜索，不影响对话。

### Step 3a: FastAPI 模块加载（静态）

uvicorn 导入 `web.server:app` 时触发模块级代码：

```python
# web/server.py — 模块级
config = load_config()                         # 读配置
session_manager = SessionManager(config)       # 会话管理器实例
rate_limiter = RateLimiter()                   # 限流器实例
_ws_connections = []                           # WS 连接跟踪
_ws_allowed_hosts = {"localhost", "127.0.0.1"} # 从 config 追加 Origin
```

然后构造 `FastAPI` 实例，注册：

**中间件链（请求穿过顺序）：**

```
请求进入
    │
    ▼
[0] _token_auth                  ← /api/* token 校验（未配置 web_access_token 时直通）
    │
    ▼
[1] _add_security_headers        ← 添 CSP/X-Frame-Options 头（响应路径）
    │
    ▼
[2] CORSMiddleware               ← 检查/设置 CORS 头
    │
    ▼
[3] RateLimitMiddleware          ← 滑动窗口限流
    │
    ▼
路由分发（/ → FileResponse, /api/* → JSON, /ws → WebSocket）
```

**路由表：**

| 路径 | 方法 | 函数 | 说明 |
|------|------|------|------|
| `/` | GET | `index()` | 返回 `web/static/index.html` |
| `/api/chat` | POST | `chat_api()` | REST 聊天（非流式） |
| `/api/status` | GET | `status_api()` | 关系指标 + 情绪历史 |
| `/api/roles` | GET | `roles_api()` | 列出可选角色 |
| `/api/chat/history` | GET | `chat_history_api()` | 对话历史 |
| `/api/logs` | GET | `logs_api()` | SSE 实时日志流 |
| `/api/sessions` | GET | `sessions_api()` | 列出某角色已有的 session |
| `/api/monitor` | GET | `monitor_api()` | LLM 调用监控记录（JSON） |
| `/api/monitor/clear` | GET | `monitor_clear()` | 清空监控缓冲 |
| `/api/tools/metrics` | GET | `tools_metrics_api()` | 各工具成功率/延迟/重试指标 |
| `/monitor` | GET | `monitor_page()` | 监控页面 |
| `/favicon.ico` | GET/HEAD | `favicon()` | 204，静默浏览器 404 |
| `/ws` | WebSocket | `websocket_endpoint()` | 主聊天接口 |
| `/static/*` | — | StaticFiles | 静态资源（app.js, style.css, theme.css） |

### Step 3b: lifespan() 异步启动

```python
# web/server.py:60-86
@asynccontextmanager
async def lifespan(app):
```

执行的顺序：

1. **日志重初始化** — uvicorn 可能重置了 root handler，重新 setup
2. **`await session_manager.open()`**
   - 打开 SQLite 数据库（`data/ai_friend.db`，WAL 模式）
   - 自动迁移表结构（schema v6，共 9 张表，含 Layer 1 记忆新增的
     `observations` / `facts_v2` / `insights_v2`；列级 ALTER 有白名单校验）
   - 创建索引
   - 构建共享的 `DeepSeekProvider`（HTTP 连接池复用）
   - 构建共享的 `EmbeddingEngine`（本地嵌入服务客户端）
3. **启动后台清理协程** — 每 5 分钟调用 `session_manager.cleanup_old()`，
   关闭超时 24 小时的 session

`yield` 后服务开始接受请求。

### Step 3c: Uvicorn 监听

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

- `web_host` 默认 `0.0.0.0`（局域网可访问）
- `web_port` 默认 `8000`

---

## 第一次 WebSocket 握手 → 聊天就绪

### 5. 浏览器加载页面

```
HTTP GET /
  → server.py:index()
  → FileResponse("web/static/index.html")
```

页面加载后自动执行 `app.js:connect()`：

### 6. WebSocket 连接

```javascript
// app.js:213
ws = new WebSocket(proto + '//' + location.host + '/ws');
```

### 7. 服务端 WebSocket 端点

```python
# web/server.py
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
```

**握手阶段（服务端）：**

```
WS Upgrade 请求进入
    │
    ▼
7a. Origin 校验
    ├── hostname ∈ _ws_allowed_hosts? → 继续
    └── 否则 → close(4003, "origin rejected")
    │
    ▼
7b. 连接数限制
    ├── 同一 IP ≤ 5 条？→ 继续
    ├── 全局 ≤ 100 条？→ 继续
    └── 否则 → close(4004, "too many connections")
    │
    ▼
7c. await websocket.accept()
    │
    ▼
7d. 加入 _ws_connections 追踪列表
```

**通信阶段（双方）：**

```
CLIENT → 发送 init JSON        SERVER
                              │
                              ▼
                          7e. 收到 init 消息
                              │
                              ├── session_manager.get_or_create()
                              │       │
                              │       ├── 缓存命中 → 恢复 session
                              │       └── 未命中 → 创建新的 WebAgent
                              │              ├── load personality JSON
                              │              ├── 创建 LTM / short_term
                              │              ├── 从 DB 恢复最近 30 轮
                              │              └── InnerDriveAgent + ToolAgent（惰性，首次用到时创建）
                              │
                              ├── 启动 RuntimeDriver 后台协程
                              │   （每 15 秒检查空闲/睡眠/主动）
                              │
                              └── 发送 init_ok（含 session_id, role_id, emotion, name）
    ◀── 收到 init_ok
    │
    ├── 设置 session_id cookie
    ├── 显示情绪状态
    ├── 加载历史消息
    └── 加载关系状态
    │
    ▼
用户输入消息 →
    ─── {type: "message", content: "你好"} ───→  7g. 收到消息
                                                   │
                                                   ├── 速率限制检查
                                                   ├── MessageHandler.process_message()
                                                   │    ├── Agent 1: InnerDrive
                                                   │    ├── Agent 2: ToolAgent（或跳过）
                                                   │    └── Agent 3: Roleplay
                                                   │
                                                   ├── _send_segments() 分段推送
                                                   └── 发送 done（含 emotion）
    ◀── segment: "你好呀！" ───
    ◀── done ───
```

### WebAgent 创建细节（Step 7e 内部）

```python
# web/session.py
session_manager.get_or_create(session_id, role_id)
```

执行链：

```
get_or_create(sid, role_id)
  │
  ├── 锁定（线程安全）
  ├── 确定 role_id：角色 = session_id（一一对应）
  │
  ├── 缓存命中？
  │   └── 返回 (sid, self._sessions[sid])
  │
  └── 创建新 WebAgent：
      │
      ├── (a) 加载人格 JSON → personalities/{role_id}.json
      │   ├── name, traits, speaking_style, backstory
      │   └── emotional_state（从 JSON 恢复或系统维护）
      │
      ├── (b) 记忆系统初始化
      │   ├── LongTermMemory(repo)       — SQLite
      │   ├── ConversationBuffer(maxlen)  — 从 DB 恢复最近 30 轮
      │   └── MemoryConsolidator         — 内部装配 MemoryLifecycleManager
      │       （Observation → Fact 生命周期，已正式上线，无条件创建）
      │
      ├── (c) LLM Provider（共享实例）
      │   └── DeepSeekProvider(endpoint, api_key) — HTTP 连接池复用
      │
      ├── (d) EmbeddingEngine（共享实例）
      │   └── 通过 embedding_endpoint（默认 localhost:8080）做语义搜索
      │
      ├── (e) ToolRegistry 注册 9 个工具
      │   ├── Agent 1,3: recall, remember（内部工具）
      │   └── Agent 2: web_fetch, web_search, read_file, glob, grep,
      │                 music_play, notify（外部工具）
      │
      ├── (f) Retriever（三层检索器）
      │   ├── Hot Memory → Hybrid Search → On-Demand
      │   └── 混合评分（语义 0.6 + 关键词 0.4）
      │
      ├── (g) Agent 装配（SleepManager / ContextManager /
      │   ProactivityManager / MessageHandler）
      │   └── 睡眠状态恢复：data/.sleep_state.{session_id}
      │
      ├── (h) InnerDriveAgent（Agent 1，首次用到时惰性创建）
      │   ├── 使用 INNER_DRIVE_SCHEMA（JSON Schema 输出）
      │   └── 决策：needs_tools? → tool_requests / 跳过
      │
      ├── (i) ToolAgent（Agent 2，首次用到时惰性创建）
      │   ├── 无人格/无情绪，纯工具调用（沿用共享 provider）
      │   └── ToolAttemptTracker: 3 retries/round, 3 rounds max
      │
      └── (j) 缓存到 self._sessions[sid]
```

---

## 后台协程 — `RuntimeDriver`

WebSocket init 后，服务端创建一个后台协程（`web/server.py`）：

```python
# web/server.py:450
task = asyncio.create_task(driver.run())
```

它的生命周期绑定 session（标签页关闭 → WS 断开 → 协程取消）。实际运行的是 `RuntimeDriver` 统一驱动（替代原来的 `_proactive_loop`）：

```python
# core/runtime_driver.py
class RuntimeDriver:
    async def run(self):
        while True:
            1. 检查睡眠/唤醒 → 发消息 + 梦境
            2. 睡着？→ sleep 30s
            3. idle < 30s 或冷却中？→ sleep 5s
            4. ProactivityManager 评分（idle 低于情绪阈值时得 0 分）→ 命中？
            5. InnerDrive Agent 1 决策：
               ├─ chat（≤ 2/hr）→ process_proactive()
               ├─ explore（≤ 1/hr）→ process_explore()
               └─ silent → 记录连续沉默，退避冷却（F1）
            6. sleep 15s → 回到 1
```

---

## CLI 模式启动对比

| 步骤 | CLI（main.py） | Web（web_main.py） |
|------|---------------|-------------------|
| 配置 | `load_config()` | 同左 |
| 日志 | `setup_logging()` | 同左 |
| 嵌入 | `auto_start_embedding()` | 同左 |
| 框架 | 无 | `uvicorn.run("web.server:app")` |
| 启动后 | `Agent.run()` → CliController 输入循环（ConversationEngine） | FastAPI 监听 |
| 输入 | stdin → CliController 输入循环 | WebSocket |
| 输出 | 打字机效果 → stdout | 单条气泡 → WebSocket |
| 主动 | RuntimeDriver 守护线程 | RuntimeDriver asyncio task |
| Session | 单用户 | SessionManager |

---

## 相关文件

| 文件 | 作用 |
|------|------|
| `web_main.py` | Web 入口，组装并启动 uvicorn |
| `main.py` | CLI 入口，组装并启动 Agent |
| `config.py` | Config dataclass + 加载合并逻辑 |
| `web/server.py` | FastAPI 应用定义、路由、lifespan |
| `web/session.py` | SessionManager + WebAgent |
| `core/embedding_server.py` | llama.cpp 嵌入服务生命周期 |
| `core/logging_setup.py` | 日志配置 |

## 相关文档

- [消息流转](message-flow.md) — 三层 Agent 流水线详解
- [架构总览](architecture.md) — 项目架构与功能总览
- [API 文档](api.md) — WebSocket + REST API 接口规范
- [部署手册](deployment.md) — 生产环境部署
