# AI 朋友 — API 文档

> WebSocket 双向通信协议 + REST API 参考。Web 端通信全部基于 `localhost`，所有消息 JSON 编码。

---

## 目录

1. [总览](#1-总览)
2. [WebSocket 协议](#2-websocket-协议)
3. [REST API](#3-rest-api)
4. [分段推送](#4-分段推送)
5. [情绪调速](#5-情绪调速)
6. [主动行为循环](#6-主动行为循环)
7. [会话管理](#7-会话管理)
8. [错误处理](#8-错误处理)
9. [安全](#9-安全)
10. [配置参考](#10-配置参考)

---

## 1. 总览

**Base URL**: `http://localhost:8000`

| 端点 | 类型 | 说明 |
|------|------|------|
| `/` | GET | 前端页面 (index.html) |
| `/favicon.ico` | GET | 204 空响应（抑制浏览器 favicon 404，WS-029） |
| `/ws` | WebSocket | 双向实时通信（主力通道） |
| `/api/chat` | POST | REST 聊天（WebSocket 降级备用） |
| `/api/status` | GET | 获取关系状态和统计 |
| `/api/chat/history` | GET | 获取最近对话轮次 |
| `/api/roles` | GET | 列出所有可用角色 |
| `/api/sessions` | GET | 列出某角色下的历史 session |
| `/api/logs` | GET | 实时服务日志（SSE） |
| `/api/monitor` | GET | LLM 调用监控记录（JSON） |
| `/api/monitor/clear` | GET | 清空监控缓冲 |
| `/monitor` | GET | 监控页面 (monitor.html) |
| `/static/*` | GET | 静态资源（CSS/JS） |

**数据格式**: 全部使用 `JSON` 编码，`ensure_ascii=False`（支持中文直出）。

---

## 2. WebSocket 协议

连接地址：

```
ws://localhost:8000/ws
wss://<生产域名>/ws
```

### 2.1 连接生命周期

```
客户端                          服务端
  │                               │
  ├── open WebSocket ──────────▶   │
  │                               ├── Origin 验证
  │                               ├── accept()
  │                               │
  ├── {"type":"init", ──────────▶  │
  │     "session_id":"xxx",         │
  │     "role_id":"小星"}           │
  │                               ├── get_or_create(session_id, role_id)
  │                               ├── create_task(_proactive_loop)
  │                               ├── {"type":"init_ok", ←─────────┐
  │                               │    "session_id":"xxx",          │
  │                               │    "role_id":"小星",            │
  │                               │    "emotion":"engaged",         │
  │                               │    "name":"小星"}               │
  │                               │                                 │
  ├── {"type":"message", ──────▶  │
  │     "content":"你好"}         │
  │                               ├── process_message("你好")
  │                               ├── {"type":"segment", ←─────────┤
  │                               │    "content":"嗨！今天心情不错呀"} │
  │                               │    （当前单段完整回复，见第 4 节）  │
  │                               ├── {"type":"done", ←────────────┤
  │                               │         "content":"嗨！今天心情不错呀",
  │                               │         "emotion":"engaged",
  │                               │         "turn":5}                │
  │                               │                                 │
  ├── {"type":"ping"} ──────────▶  │
  │                               ├── {"type":"pong"} ←────────────┤
  │                               │                                 │
  ├── 断开 ─────────────────────▶ │
  │                               ├── session_manager.remove()
  │                               ├── cancel proactive task
```

### 2.2 客户端 → 服务端消息

#### `init` — 初始化会话

```json
{
  "type": "init",
  "session_id": "a1b2c3d4e5f6",
  "role_id": "小星"
}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | ✓ | 固定 `"init"` |
| `session_id` | string | — | 已有 session_id 传此值恢复会话；省略且未传 `role_id` 时落入 `"default"` |
| `role_id` | string | — | 要绑定的角色 ID（如 `小星`）；一个角色一个 session，传了 `role_id` 时 session_id 直接取 `role_id` |

- 连接建立后**应先发 init**；未 init 直接发 `message` 会落入 `"default"` 会话
- `session_id` 与 `role_id` 均存储在 cookie 中，页面刷新后携带以恢复会话

#### `message` — 发送聊天消息

```json
{
  "type": "message",
  "content": "你好呀，今天天气真好！"
}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | ✓ | 固定 `"message"` |
| `content` | string | ✓ | 消息正文，最长 **100KB**（超出返回 error） |

#### `ping` — 心跳

```json
{
  "type": "ping"
}
```

- 客户端每 **25 秒** 发送一次（见 `app.js` 的 `setInterval`）
- 服务端回复 `pong`，无额外处理

### 2.3 服务端 → 客户端消息

#### `init_ok` — 初始化成功

```json
{
  "type": "init_ok",
  "session_id": "a1b2c3d4e5f6",
  "role_id": "小星",
  "emotion": "engaged",
  "name": "小星"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"init_ok"` |
| `session_id` | string | 实际使用的 session_id（客户端应保存到 cookie） |
| `role_id` | string | 实际绑定的角色 ID |
| `emotion` | string | 当前 AI 情绪标签，用于前端 UI 展示 |
| `name` | string | 角色名字，用于前端标题/头像 |

前端收到后行为：
- 保存 `session_id` 到 cookie（`role_id` 在选择角色时已存入；有效期 24h）
- 调用 `showEmotion(data.emotion)` 更新 UI 情绪显示
- 使用 `data.name` 更新顶部角色名

#### `segment` — 分段回复

```json
{
  "type": "segment",
  "content": "嗨！今天天气确实不错呀"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"segment"` |
| `content` | string | 一个独立气泡的文本内容 |

- **当前分段推送暂停**：服务端把完整回复作为**单个** `segment` 发送（分段算法保留待恢复，见[第 4 节](#4-分段推送)）
- 前端把 `segment` 内容累积进当前 assistant 气泡（markdown 源码），收到 `done` 后用 marked 渲染

#### `done` — 回复结束

```json
{
  "type": "done",
  "content": "嗨！今天天气确实不错呀",
  "emotion": "engaged",
  "turn": 5
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"done"` |
| `content` | string | 完整回复原文 |
| `emotion` | string | 回复完成时的 AI 情绪标签 |
| `turn` | int | 当前对话轮次计数 |

前端收到后行为：
- `isProcessing = false`（解锁发送按钮）
- `showEmotion(data.emotion)` 更新情绪显示
- 隐藏正在输入指示器

#### `error` — 错误

```json
{
  "type": "error",
  "content": "消息过长（最大100KB）"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"error"` |
| `content` | string | 人类可读的错误描述 |

#### `pong` — 心跳回复

```json
{
  "type": "pong"
}
```

无额外字段。前端收到后不处理。

### 2.4 消息大小限制

- 客户端 `message` 内容最大 **100KB**（`#176`）
- 超出时服务端返回 `{"type":"error","content":"消息过长（最大100KB）"}`，继续等待下条消息
- 服务端回复无硬限制，由模型 `max_tokens` 情绪动态调控

### 2.5 断开重连

```
WebSocket onclose
    │
    ├── 设置状态 "已断开"
    ├── hideTyping()
    └── setTimeout(connect, reconnectDelay)  ← 2s 起始，指数退避至 30s 上限
        │
        └── 重连后重新发送 init（携带 cookie 中的 session_id / role_id）
```

- 断线后自动重连：初始延时 **2 秒**，每次失败翻倍，上限 **30 秒**（JS 侧指数退避）
- WS 断开时服务端会 `remove()` 内存会话；重连 init 时重建 WebAgent，从 DB 恢复最近 30 轮对话（`#98`）与人格文件，会话体验不中断
- 多标签页：新标签页的 proactive 任务会 cancel 旧标签页的任务（`register_proactive` 逻辑）

---

## 3. REST API

### 3.1 `POST /api/chat` — 发送消息

WebSocket 不可用时的降级方案。请求/响应使用 Pydantic 模型校验（`web/schemas.py`）。

**Request** (`ChatRequest`):

```json
{
  "session_id": "default",
  "message": "你好"
}
```

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `session_id` | string | — | `"default"` | 会话标识 |
| `message` | string | ✓ | — | 消息正文，不可为空 |

**Response** (`ChatResponse`):

```json
{
  "response": "嗨！今天心情不错呀",
  "emotion": "engaged",
  "turn": 5,
  "session_id": "default"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `response` | string | AI 完整回复 |
| `emotion` | string | 回复后的情绪标签 |
| `turn` | int | 当前对话轮次 |
| `session_id` | string | 实际使用的 session_id |

**错误响应**:

- `422 Unprocessable Entity`：`message` 为空或类型错误（FastAPI/Pydantic 自动校验）。
- `429 Too Many Requests`：触发速率限制（每 IP 30 次/分钟）。

注意：REST 模式无分段推送，前端收到完整 `response` 后直接单气泡显示（markdown 经 marked 渲染）；早期的客户端分段 `splitSegments()` 已随服务端分段一并停用（[见第 4 节](#4-分段推送)）。

### 3.2 `GET /api/status` — 获取关系状态

获取 AI 当前情绪、关系指标以及 7 天关系历史（`#132`）。响应使用 Pydantic 模型 `StatusResponse`。

**Query Parameters**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | string | `"default"` | 会话标识 |

**Response**:

```json
{
  "turn": 42,
  "emotion": "engaged",
  "relationship": {
    "trust": 0.35,
    "familiarity": 0.28,
    "intimacy": 0.15,
    "fun": 0.2
  },
  "relationship_history": [
    { "timestamp": "2026-06-01 12:00:00", "trust": 0.3, "familiarity": 0.25, "intimacy": 0.1, "fun": 0.15 }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `turn` | int | 总对话轮次 |
| `emotion` | string | 当前情绪标签 |
| `relationship` | object | 关系四维指标（trust/familiarity/intimacy/fun） |
| `relationship_history` | array | 最近 7 天关系快照数组（timestamp 为北京时间） |

### 3.3 `GET /api/chat/history` — 获取最近对话

返回当前 session 的最近对话轮次（用于页面刷新后恢复聊天记录）。响应使用 Pydantic 模型 `HistoryResponse`。

**Query Parameters**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | string | `"default"` | 会话标识 |

**Response**:

```json
{
  "turns": [
    { "role": "user", "content": "你好" },
    { "role": "assistant", "content": "嗨！" }
  ],
  "session_id": "default"
}
```

### 3.4 `GET /` — 前端页面

返回 `web/static/index.html`。

### 3.5 `GET /static/*` — 静态资源

FastAPI `StaticFiles` 挂载，提供 `app.js`、`style.css` 等前端资源。

### 3.6 `GET /api/logs` — 实时服务日志（SSE）

Server-Sent Events 流，推送当天 `logs/YYYY-MM-DD.log` 内容。连接时先发送最近 100 行历史日志，随后持续 tail 新写入的日志行。

**Query Parameters**: 无

**Response**: `text/event-stream`

```
data: 2026-07-13 12:24:38 [INFO] web.server: [ws] accepted: 127.0.0.1:9559 (1 total)

data: 2026-07-13 12:24:38 [INFO] web.session: [session] create: 3626d9aa3865
```

**错误处理**: 若当天日志文件不存在，返回 `data: [no log file]`。

### 3.7 `GET /api/roles` — 列出可用角色

返回 `personalities/` 目录下的所有角色。

**Response**:

```json
{
  "roles": [
    { "id": "default", "name": "Luna" },
    { "id": "小星", "name": "小星" }
  ]
}
```

### 3.8 `GET /api/sessions` — 获取某角色的唯一 session

当前架构下一个角色只对应一个 session，因此返回的 sessions 数组固定为 `[role_id]`。

**Query Parameters**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `role_id` | string | ✓ | 角色 ID |

**Response**:

```json
{
  "role_id": "小星",
  "sessions": ["小星"]
}
```

### 3.9 `GET /api/monitor` — LLM 调用监控记录

返回 `core/monitor.py` 内存环形缓冲中的 LLM API 调用记录（默认最多保留 200 条，按时间倒序），开发调试用。`monitor_enabled=false` 时不再记录新调用。

**Query Parameters**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | `0` | 只返回最近 N 条；`0` 表示全部 |

**Response**: JSON 数组，单条记录字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | string | 调用时间（`HH:MM:SS`） |
| `model` | string | 使用的模型 |
| `duration_ms` | float | 调用耗时（毫秒） |
| `max_tokens` / `temperature` | int / float | 该次调用的生成参数 |
| `messages` | array | 完整请求 messages（含 system/user/assistant） |
| `response` | string | 完整响应文本 |
| `source` | string | 调用来源（`react` / `session` / `assess` / `tool_agent` / `dream` 等） |

### 3.10 `GET /api/monitor/clear` — 清空监控缓冲

**Response**: `{"status": "cleared"}`

### 3.11 `GET /monitor` — 监控页面

返回 `web/static/monitor.html`（配合 3.9 / 3.10 使用）。

### 3.12 `GET /favicon.ico` — 站点图标

返回 `204 No Content`（支持 GET/HEAD），避免浏览器请求 favicon 产生 404 噪音（`WS-029`）。

---

## 4. 分段推送

> 当前状态：分段推送**暂停使用**——`_send_segments` 直接把完整回复作为单个 `segment` 发送（代码内 TODO：待 markdown 流式稳定后恢复）。`_split_segments` 与 `_calc_delay` 仍保留在 `web/server.py` 中，以下算法为保留实现。

### 4.1 服务端分段（`_split_segments`）

6 级 fallback 算法：

```
输入文本
    │
    ├── ① 句末标点分割（。！？.!?\n，含引号括号尾随）
    ├── ② 逗号/分号分割（，,；;，仅 40 字以上长段）
    ├── ③ 空格分割（仅当仍为单段时）
    ├── ④ 语气词分割（啊吗呢了吧么呀哦嘛哇）
    ├── ⑤ 自然停顿（然后/但是/所以… + 了/过/到）
    └── ⑥ 18 字符硬切（兜底）
    │
    └── 合并 <4 字符的碎片到前一段
```

### 4.2 客户端分段（REST fallback）

客户端分段已随服务端分段一并移除：`app.js` 中不再有 `splitSegments()`，REST 降级拿到完整 `response` 后直接单气泡显示（markdown 经 marked 渲染）。

### 4.3 分段数据流

```
服务端生成完整回复
    │
    ├── WebSocket: _send_segments() → 单个 segment（完整回复）→ done
    │   （保留实现：_split_segments() → 逐段 _calc_delay → 逐段 send segment）
    │
    └── REST: 返回完整 response → 前端单气泡渲染
```

---

## 5. 情绪调速

分段之间的发送延时由情绪状态动态决定（当前随分段推送一并暂停，`_calc_delay` 保留在 `web/server.py` 中）：

```
delay = base[emotion] × (1 + seg_len / 80) × random(0.8, 1.3)
```

### 5.1 基础延时表

| 情绪 | 基础延时 | 典型 20 字段约 |
|------|----------|---------------|
| `excited` | 0.7s | ~1.0s |
| `surprised` | 0.8s | ~1.1s |
| `joyful` / `anticipating` | 0.9s | ~1.2~1.6s |
| `anxious` | 1.0s | ~1.4s |
| `trusting` | 1.1s | ~1.5s |
| `engaged` | 1.3s | ~1.6~2.3s |
| `afraid` / `disgusted` | 1.3s | ~1.8s |
| `content` | 1.5s | ~1.9~2.6s |
| `frustrated` | 1.5s | ~2.0s |
| `neutral` | 1.7s | ~2.1~3.0s |
| `melancholy` | 2.2s | ~2.7~3.9s |
| `sad` | 2.5s | ~3.1~4.4s |
| `angry` | 1.0s | ~1.4s |

### 5.2 响应速度变化趋势

- **积极/兴奋**（excited/joyful）→ 回复快，段间间隔短
- **中性/平静**（content/neutral）→ 正常节奏
- **消极/悲伤**（melancholy/sad）→ 回复慢，段间间隔长
- **愤怒**（angry）→ 快节奏（与兴奋同级）
- **恐惧/焦虑**（anxious/afraid）→ 略快但小于积极情绪

---

## 6. 主动行为循环

### 6.1 循环机制

每 15 秒 tick 的后台协程（`_proactive_loop`）：

```
_proactive_loop (15s tick, asyncio.create_task)
    │
    ├── 睡眠/唤醒检查（每 tick）
    │   ├── 午睡 12:00-13:00 / 夜睡 23:00-01:00 → 入睡
    │   └── 午醒 13:10-16:00 / 晨醒 7:00-10:00 → 醒来（分享梦境）
    │
    ├── 睡眠中 → 30s 后重试
    │
    ├── 空闲 < 30s → skip（绝对底线）
    │
    └── 空闲 > 情绪阈值?
        └── random() < score?
            └── InnerDrive (Agent 1) 决策：
                ├── chat → 主动搭话（上限 2 次/小时）
                ├── explore → 自主搜索/浏览（上限 1 次/小时）
                └── silent → 不操作
```

### 6.2 空闲阈值

| 情绪 | 阈值 |
|------|------|
| `excited` | 60s |
| `joyful` | 90s |
| `engaged` | 180s |
| `neutral` | 360s |
| `angry` | 480s |
| `sad` | 900s |
| +resentment | 额外最多 +300s（随 resentment 比例） |

### 6.3 频率限制

| 行为 | 冷却时间 | 说明 |
|------|----------|------|
| chat | 1800s (30min) | 主动搭话 |
| explore | 3600s (1hr) | 自主工具调用 |

### 6.4 消息类型

主动行为（chat / explore）生成的消息**会写入短期记忆**并持久化到 `conversation_turns`（`#299` 修复"主动消息不持久化"）；睡眠/唤醒消息同样入历史（`metadata={"sleep": True}`，`#156`），页面刷新后可恢复显示。

---

## 7. 会话管理

### 7.1 SessionManager

```python
class SessionManager:
    _sessions: dict[session_id → WebAgent]  # 活跃会话池
    _proactive_tasks: dict[session_id → asyncio.Task]
    _active_ws: dict[session_id → WebSocket]
    _lock: Lock  # 线程安全
```

| 方法 | 说明 |
|------|------|
| `get_or_create(session_id, role_id)` | 获取或创建 WebAgent；新 session 绑定 `role_id`，已有 session 忽略 `role_id` |
| `remove(session_id)` | 移除会话、cancel 后台任务、清理 WS |
| `register_proactive(sid, task, ws)` | 注册/替换 proactive 任务（新标签页 cancel 旧任务） |
| `get_active_ws(session_id)` | 获取当前活跃的 WebSocket（多标签页切换） |
| `cleanup_old(max_sessions, ttl)` | 清理超时会话（默认 24h TTL, 最多 50 个） |
| `shutdown()` | 优雅关闭：保存所有 session、cancel 所有任务 |

### 7.2 会话生命周期

```
首次打开页面
    │
    ├── 无 role_id cookie → 显示角色选择弹窗
    ├── 选择角色
    │
    ├── connect() → WebSocket /ws
    ├── send {"type":"init", "role_id":"小星", "session_id":"小星"}
    │
    ├── 服务端按 role_id 加载 personalities/小星.json
    ├── 创建/恢复 WebAgent（session_id = role_id）
    ├── 注册 proactive 后台任务
    └── 返回 session_id / role_id → 存入 cookie（max-age=86400）
        │
        页面刷新
            │
            ├── connect() → WebSocket /ws
            ├── send {"type":"init", "role_id":"小星", "session_id":"小星"}  ← 从 cookie 读取
            │
            ├── 服务端重建 WebAgent（旧 WS 断开时已 remove；
            │   从 DB 恢复最近 30 轮 + personalities/小星.json 情绪状态）
            ├── 旧 proactive 任务被 cancel
            └── 注册新 proactive 任务
```

### 7.3 Session 隔离

| 隔离级别 | 当前状态 |
|----------|----------|
| 独立 Personality | ✓ 每个 WebAgent 按 role_id 加载独立 personality 文件 |
| 独立 EmotionalState | ✓ 同一角色的不同 session 也拥有独立情绪状态 |
| 独立 ConversationBuffer | ✓ 每个 WebAgent 独立短期记忆 |
| SQLite session_id 过滤 | ✓ user_facts / experiences / reflections / conversation_turns / relationship_metrics / relationship_snapshots / observations / facts_v2 均带 session_id 列并按其过滤；注意 user_facts 的唯一约束 `UNIQUE(category, fact_key)` 不含 session_id，多角色同 key 会互相覆盖（已知未修） |
| session → role 映射 | ✓ `session_roles` 表持久化 `session_id → role_id` |
| 共享 Provider/Embedding | ✓ SN-005/006：SessionManager 级别共享 HTTP 会话 |
| 共享 EmbeddingCache | ✓ 只读 LRU 无竞争 |
| 睡眠状态隔离 | ✓ SL-001：`.sleep_state.{session_id}` 每会话一文件 |
| WebAgent 资源释放 | ✓ SN-013：remove/evict/shutdown 调用 `close()` |

### 7.4 超时清理

```python
session_manager.cleanup_old(max_sessions=50, ttl_seconds=86400)
```

- 超过 24 小时无活动的 session 自动移除
- 超过 50 个 session 时驱逐最旧的
- SN-016：lifespan shutdown 阶段调用 `cleanup_old()`，消除死代码

---

## 8. 错误处理

### 8.1 WebSocket 错误

| 场景 | 服务端行为 | 客户端行为 |
|------|-----------|-----------|
| Origin 不合法 | `websocket.close(code=4003)` 拒绝连接 | `onclose` → 自动重连（会再次被拒） |
| 连接数超限（每 IP >5 或全局 >100） | `websocket.close(code=4004)` 拒绝连接 | 同上 |
| 消息 >100KB | 回复 `{"type":"error","content":"消息过长"}` | 前端显示系统消息提示 |
| WebSocket 异常断开 | log `info` 级别 | `onclose` → 自动重连（指数退避） |
| WebSocket 异常后发送失败 | try-except 静默忽略 | 同上 |
| 内部处理异常 | 回复 `{"type":"error"}`，catch 异常后继续 | 日志回显 |

### 8.2 REST API 错误

| 场景 | HTTP 状态码 | Response |
|------|------------|----------|
| 请求格式非法 / 字段缺失 | 422 | FastAPI 标准校验错误体 |
| 触发速率限制 | 429 | `{"error":"Too many requests. Please slow down."}` |
| session 不存在 | 200 | 自动创建新 session |
| 服务端异常 | 500 | 异常信息通过 response 透出 |

说明：Pydantic 校验错误统一返回 `422`；内存滑动窗口限流器对 `/api/*` 路径按客户端 IP 限速（`/api/chat` 30 次/分钟，`/api/status` 与 `/api/chat/history` 60 次/分钟）。

### 8.3 前端错误处理

```javascript
ws.onerror = function() { setStatus('error'); };
ws.onclose = function() {
    setStatus('disconnected');
    hideTyping();
    setTimeout(connect, reconnectDelay);                   // 自动重连
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);  // 指数退避，上限 30s
};
```

- 连接 error → 状态显示"连接异常"（黄灯）
- 连接 close → 状态显示"已断开"（红灯）→ 2s 后自动重连，失败逐次翻倍至 30s 上限
- REST fallback 失败 → 静默恢复 UI（`catch` 中重置 `isProcessing` 状态）

---

## 9. 安全

### 9.1 Origin 验证（`#158` / `#24`）

```python
allowed = {"localhost", "127.0.0.1"}  # + config.allowed_origins 的主机名
if origin and origin != "null":
    if urlparse(origin).hostname not in allowed:
        await websocket.close(code=4003)
```

- 默认仅允许 `localhost` 和 `127.0.0.1` 来源（按主机名匹配，忽略 scheme/端口）
- 空 Origin 或 `"null"`（非浏览器/本地客户端）视为合法（兼容性）
- 拒绝非 localhost 跨站 WebSocket 连接
- 用户可在 `config.json` 中通过 `allowed_origins` 追加额外可信主机（便于内网穿透域名）

### 9.2 消息大小限制

- 所有 WebSocket 消息（含 message 内容）限制 100KB（`#176` 防 OOM）

### 9.3 速率限制（`#24` / `RL-001`）

基于内存滑动窗口的 per-IP 限流器（`web/rate_limit.py`）：

| 路径 | 限制 | 说明 |
|------|------|------|
| `/api/chat` | 30 次 / 60 秒 | 覆盖 REST 与 WebSocket `message` |
| `/api/status` | 60 次 / 60 秒 | REST 状态查询 |
| `/api/chat/history` | 60 次 / 60 秒 | REST 历史查询 |

- REST 层通过 `RateLimitMiddleware` 统一拦截，超限返回 `429 Too Many Requests`
- WebSocket 层在收到 `message` 时同样调用限流器，超限回复 `{"type":"error","content":"发送太频繁了，请稍后再试。"}`
- 部署在反向代理后时，限流器优先读取 `X-Forwarded-For` 头部第一段 IP

### 9.4 WebSocket 连接限制

- 每 IP 最多 5 条、全局最多 100 条 WebSocket 连接，超限 `close(code=4004)`（`#158`）
- 多标签页共享同一 session 的后台 proactive 任务会自动 cancel 旧任务
- 速率限制见 [9.3](#93-速率限制24--rl-001)

### 9.5 静态文件

- FastAPI `StaticFiles` 无额外限制，仅供前端 HTML/CSS/JS

### 9.6 安全响应头（`#24` / `WS-027` / `WS-028`）

每个 HTTP 响应都会附加：

| 头部 | 值 | 作用 |
|------|-----|------|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://localhost:* http://localhost:* http://127.0.0.1:*; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'` | 禁止内联脚本，限制连接来源，防点击劫持 |
| `X-Frame-Options` | `DENY` | 拒绝被嵌入 iframe |
| `X-Content-Type-Options` | `nosniff` | 禁止 MIME 嗅探 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | 控制 referrer 泄露 |

### 9.7 安全加固状态

| # | 问题 | 状态 |
|---|------|------|
| #158 | WebSocket Origin 校验 | ✅ 已加（默认仅 localhost，可扩展） |
| #176 | 消息大小 100KB 限制 | ✅ 协议层 + 应用层双重校验 |
| #24 | CORS 可配置化 | ✅ `allowed_origins` + 默认 localhost |
| #24 | 速率限制细化 | ✅ REST + WebSocket 双通道限流 |
| #24 | CSP 细化 | ✅ 移除 `unsafe-inline` 脚本，connect-src 限制域名 |
| WS-027 | X-Frame-Options | ✅ DENY |
| WS-028 | Content-Security-Policy | ✅ 已加（含 frame-ancestors 'none'） |
| #155 | API Key 可能泄露到日志 | 低（单人），待 #155 后续治理 |
| #155 | Session ID 客户端可控 | 低（单人） |

---

## 10. 配置参考

以下配置项直接影响 API 行为：

| 配置项 | 默认值 | 影响 |
|--------|--------|------|
| `web_host` | `"0.0.0.0"` | 监听地址 |
| `web_port` | `8000` | 监听端口 |
| `allowed_origins` | `[]` | 额外允许的 CORS Origin 列表（默认已含 localhost） |
| `monitor_enabled` | `true` | 是否记录 LLM 调用到监控缓冲（`/api/monitor` 数据源，MN-003） |
| `api_endpoint` | `"https://api.deepseek.com"` | LLM API 地址 |
| `api_model` | `"deepseek-v4-flash"` | 使用的模型 |
| `api_timeout` | `180` | API 请求超时（秒） |
| `max_tokens` | `512` | 最大回复 token 数 |
| `temperature` | `0.8` | 回复随机性（Agent 3） |
| `conversation_examples` | 见 `config.py` | 对话风格示例数组（#28） |

环境变量覆盖（参考 `config.py`）：

| 环境变量 | 覆盖配置 |
|----------|----------|
| `DEEPSEEK_API_KEY` | `api_key` |
| `DEEPSEEK_API_ENDPOINT` | `api_endpoint` |
| `DEEPSEEK_API_MODEL` | `api_model` |
| `AI_FRIEND_DB_PATH` | `db_path` |
| `AI_FRIEND_LOG_LEVEL` | `log_level` |

---

## 相关文档

- [架构总览](architecture.md)
- [技术文档](technical.md)
- [消息流转](message-flow.md)
- [配置参考](config-reference.md)
- [部署手册](deployment.md)
