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
| `/ws` | WebSocket | 双向实时通信（主力通道） |
| `/api/chat` | POST | REST 聊天（WebSocket 降级备用） |
| `/api/status` | GET | 获取关系状态和统计 |
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
  │     "session_id":"xxx"}        │
  │                               ├── get_or_create(session_id)
  │                               ├── create_task(_proactive_loop)
  │                               ├── {"type":"init_ok", ←─────────┐
  │                               │    "session_id":"xxx",          │
  │                               │    "emotion":"engaged"}         │
  │                               │                                 │
  ├── {"type":"message", ──────▶  │
  │     "content":"你好"}         │
  │                               ├── process_message("你好")
  │                               ├── {"type":"segment", ←─────────┤
  │                               │         "content":"嗨！"}       │
  │                               ├── {"type":"segment", ←─────────┤
  │                               │         "content":"今天心情不错呀"} │
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
  "session_id": "a1b2c3d4e5f6"
}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | ✓ | 固定 `"init"` |
| `session_id` | string | — | 已有 session_id 传此值恢复会话；省略则服务端新生成 |

- 连接建立后**必须先发 init**，否则后续 `message` 消息无可用 session
- session_id 存储在 cookie 中（`setCookie('session_id', ...)`），页面刷新后携带以恢复会话

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

- 客户端每 **30 秒** 发送一次（见 `app.js` 的 `setInterval`）
- 服务端回复 `pong`，无额外处理

### 2.3 服务端 → 客户端消息

#### `init_ok` — 初始化成功

```json
{
  "type": "init_ok",
  "session_id": "a1b2c3d4e5f6",
  "emotion": "engaged"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"init_ok"` |
| `session_id` | string | 实际使用的 session_id（客户端应保存到 cookie） |
| `emotion` | string | 当前 AI 情绪标签，用于前端 UI 展示 |

前端收到后行为：
- 保存 `session_id` 到 cookie（有效期 24h）
- 调用 `showEmotion(data.emotion)` 更新 UI 情绪显示

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

- **分段之间带延时发送**，模拟人类打字节奏
- 每个 `segment` 在前端创建独立 assistant 气泡
- 延时由[情绪调速](#5-情绪调速)公式计算

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
    └── setTimeout(connect, 3000)  ← 3 秒后自动重连
        │
        └── 重连后重新发送 init（携带 cookie 中的 session_id）
```

- 断线后 **3 秒** 自动重连（JS 侧 `setTimeout`）
- 重连后 session 保留（`SessionManager` 持有），会话不中断
- 多标签页：新标签页的 proactive 任务会 cancel 旧标签页的任务（`register_proactive` 逻辑）

---

## 3. REST API

### 3.1 `POST /api/chat` — 发送消息

WebSocket 不可用时的降级方案。

**Request**:

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

**Response**:

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

```json
{
  "error": "empty message"
}
```

注意：REST 模式无分段推送，前端收到完整 `response` 后自行用 `splitSegments()` 分段 + `setTimeout` 模拟逐段显示。分段逻辑与 WebSocket 端一致（[见第 4 节](#4-分段推送)）。

### 3.2 `GET /api/status` — 获取关系状态

获取 AI 当前情绪、关系指标以及 7 天关系历史（`#132`）。

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
    { "timestamp": "2026-06-01T12:00:00", "trust": 0.3, "familiarity": 0.25, "intimacy": 0.1, "fun": 0.15 }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `turn` | int | 总对话轮次 |
| `emotion` | string | 当前情绪标签 |
| `relationship` | object | 关系四维指标（trust/familiarity/intimacy/fun） |
| `relationship_history` | array | 最近 7 天关系快照数组 |

### 3.3 `GET /` — 前端页面

返回 `web/static/index.html`。

### 3.4 `GET /static/*` — 静态资源

FastAPI `StaticFiles` 挂载，提供 `app.js`、`style.css` 等前端资源。

---

## 4. 分段推送

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

前端 `splitSegments()` 使用相同的分割策略（排除服务端第②步逗号分割）：

```
输入文本
    ├── ① 句末标点分割
    ├── ② 空格分割
    ├── ③ 语气词分割
    └── ④ 自然停顿 / 18 字符硬切（兜底）
    └── 合并 <4 字符碎片
```

### 4.3 分段数据流

```
服务端生成完整回复
    │
    ├── WebSocket: _split_segments() → 逐段 _calc_delay → send segment
    │
    └── REST: 返回完整 response → 前端 splitSegments() → setTimeout 逐段显示
```

---

## 5. 情绪调速

分段之间的发送延时由情绪状态动态决定：

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
| +resentment | 额外 +300s |

### 6.3 频率限制

| 行为 | 冷却时间 | 说明 |
|------|----------|------|
| chat | 1800s (30min) | 主动搭话 |
| explore | 3600s (1hr) | 自主工具调用 |

### 6.4 消息类型

主动行为生成的消息**不写入短期记忆**（`add_to_history=False`），避免污染长程对话上下文。

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
| `get_or_create(session_id)` | 获取或创建 WebAgent，返回 `(sid, agent)` |
| `remove(session_id)` | 移除会话、cancel 后台任务、清理 WS |
| `register_proactive(sid, task, ws)` | 注册/替换 proactive 任务（新标签页 cancel 旧任务） |
| `get_active_ws(session_id)` | 获取当前活跃的 WebSocket（多标签页切换） |
| `cleanup_old(max_sessions, ttl)` | 清理超时会话（默认 24h TTL, 最多 50 个） |
| `shutdown()` | 优雅关闭：保存所有 session、cancel 所有任务 |

### 7.2 会话生命周期

```
首次打开页面
    │
    ├── connect() → WebSocket /ws
    ├── send {"type":"init"}  ← cookie 中无 session_id
    │
    ├── 服务端创建新 session（uuid4 hex[:12]）
    ├── 注册 proactive 后台任务
    └── 返回 session_id → 存入 cookie（max-age=86400）
        │
        页面刷新
            │
            ├── connect() → WebSocket /ws
            ├── send {"type":"init", "session_id":"xxx"}  ← 从 cookie 读取
            │
            ├── 服务端恢复已有 session（内存池）
            ├── 旧 proactive 任务被 cancel
            └── 注册新 proactive 任务
```

### 7.3 Session 隔离

| 隔离级别 | 当前状态 |
|----------|----------|
| 独立 Personality | ✓ 每个 WebAgent 独立 Personality 实例 |
| 独立 ConversationBuffer | ✓ 每个 WebAgent 独立短期记忆 |
| 共享 SQLite | ✗ 无 session_id 过滤（`#154` 待修复） |
| 共享 EmbeddingCache | ✓ 只读 LRU 无竞争 |

### 7.4 超时清理

```python
session_manager.cleanup_old(max_sessions=50, ttl_seconds=86400)
```

- 超过 24 小时无活动的 session 自动移除
- 超过 50 个 session 时驱逐最旧的

---

## 8. 错误处理

### 8.1 WebSocket 错误

| 场景 | 服务端行为 | 客户端行为 |
|------|-----------|-----------|
| Origin 不合法 | `websocket.close(code=4003)` 拒绝连接 | `onclose` → 3s 重连（会再次被拒） |
| 消息 >100KB | 回复 `{"type":"error","content":"消息过长"}` | 前端显示系统消息提示 |
| WebSocket 异常断开 | log `info` 级别 | `onclose` → 3s 自动重连 |
| WebSocket 异常后发送失败 | try-except 静默忽略 | 同上 |
| 内部处理异常 | 回复 `{"type":"error"}`，catch 异常后继续 | 日志回显 |

### 8.2 REST API 错误

| 场景 | HTTP 状态码 | Response |
|------|------------|----------|
| 空消息 | 200 | `{"error":"empty message"}` |
| session 不存在 | 200 | 自动创建新 session |
| 服务端异常 | 200 | 异常信息通过 response 透出 |

注意：REST API 当前未使用标准 HTTP 状态码（所有请求返回 200），异常通过 response body 的 text 内容或 error 字段传递。当前为单人本地使用场景。

### 8.3 前端错误处理

```javascript
ws.onerror = function() { setStatus('error'); };
ws.onclose = function() {
    setStatus('disconnected');
    hideTyping();
    setTimeout(connect, 3000);  // 自动重连
};
```

- 连接 error → 状态显示"连接异常"（黄灯）
- 连接 close → 状态显示"已断开"（红灯）→ 3s 后自动重连
- REST fallback 失败 → 静默恢复 UI（`catch` 中重置 `isProcessing` 状态）

---

## 9. 安全

### 9.1 Origin 验证（`#158`）

```python
allowed = {"http://localhost:8000", "http://127.0.0.1:8000", "null"}
if origin and origin not in allowed and not origin.startswith("http://localhost"):
    await websocket.close(code=4003)
```

- 仅允许 `localhost` 和 `127.0.0.1` 来源
- 空 Origin（非浏览器客户端）视为合法（兼容性）
- 拒绝非 localhost 跨站 WebSocket 连接

### 9.2 消息大小限制

- 所有 WebSocket 消息（含 message 内容）限制 100KB（`#176` 防 OOM）

### 9.3 WebSocket 连接限制

- 单人使用场景，无连接数/速率限制
- 多标签页共享同一 session 的后台 proactive 任务会自动 cancel 旧任务

### 9.4 静态文件

- FastAPI `StaticFiles` 无额外限制，仅供前端 HTML/CSS/JS

### 9.5 已知安全缺口

| # | 问题 | 当前风险 |
|---|------|---------|
| #155 | API Key 可能泄露到日志 | 低（单人） |
| #155 | Session ID 客户端可控 | 低（单人） |
| #24 | 无 CORS + CSP 头 | 低（单人 localhost） |

---

## 10. 配置参考

以下配置项直接影响 API 行为：

| 配置项 | 默认值 | 影响 |
|--------|--------|------|
| `web_host` | `"0.0.0.0"` | 监听地址 |
| `web_port` | `8000` | 监听端口 |
| `api_endpoint` | `"https://api.deepseek.com"` | LLM API 地址 |
| `api_model` | `"deepseek-v4-flash"` | 使用的模型 |
| `api_timeout` | `180` | API 请求超时（秒） |
| `max_tokens` | `512` | 最大回复 token 数 |
| `temperature` | `0.8` | 回复随机性（Agent 3） |

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
- [里程碑与 Issue](milestones-and-issues.md)
