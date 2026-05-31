# AI 朋友 — 架构与使用文档

> 具有人格、情绪、长短期记忆的 AI 朋友。基于 DeepSeek API，采用三层 Agent 架构，支持 CLI 和 Web 双端。

---

## 快速开始

### 环境要求

- Python 3.12+
- 依赖：`pip install -r requirements.txt`

### 安装

```bash
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json 填入 API Key（或用环境变量 DEEPSEEK_API_KEY）
```

### 启动

```bash
# CLI 模式
python main.py

# Web 模式
python web_main.py
# → http://localhost:8000
```

### 自定义人格

编辑 `personality.json`：

| 字段 | 说明 |
|------|------|
| `name` | AI 名字 |
| `traits` | 性格特质及强度 (0~1) |
| `speaking_style` | 说话风格描述 |
| `backstory` | 背景故事 |
| `interests` | 兴趣领域 |

### CLI 内置命令

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情 |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |

---

## 架构总览

```
浏览器/终端
    │
    ├── CLI: python main.py → ConsoleInterface → Agent.run()
    │
    └── Web: python web_main.py → FastAPI + WebSocket
              │
              ├── web/server.py  (HTTP + WS + proactive_loop)
              ├── web/session.py (SessionManager + WebAgent)
              └── web/static/    (HTML + CSS + JS)
    │
    ▼
Agent 1: core/inner_drive.py  (InnerDriveAgent)
    │  Perceive → 检索记忆 → 识别缺口 → 决策
    │  内部工具: recall / remember
    │  若不需要外部工具 → 跳过 Agent 2 (闲聊优化)
    │  若需要 → 输出自然语言请求给 Agent 2
    ▼
Agent 2: core/tool_agent.py  (ToolAgent, temp=0.3, 纯工具调用)
    │  7 个外部工具: web_fetch, web_search, read_file, glob, grep, music_play, notify
    │  ToolAttemptTracker: 3 retries/round, 3 rounds max
    │  失败 → 回报 Agent 1 重新决策
    │  无人格/无情绪/无记忆
    ▼
Agent 3: core/agent.py  (Roleplay Agent, temp=0.8, 人格驱动)
    │  接收 inner_drive_summary + tool_results
    │
    ├── core/context_manager.py  (上下文窗口管理)
    ├── core/sleep_manager.py    (睡眠/唤醒)
    ├── core/proactivity.py      (主动行为引擎)
    ├── core/cli_controller.py   (CLI 状态机)
    ├── core/message_handler.py  (消息入口 + 三层编排 + 重试循环)
    ├── core/personality.py  (四层情绪引擎)
    ├── core/provider.py     (LLM API 客户端)
    ├── core/dispatcher.py   (tool_call 解析执行)
    │
    ├── memory/
    │   ├── short_term.py    (ConversationBuffer, 线程安全)
    │   ├── long_term.py     (SQLite CRUD)
    │   ├── embeddings.py    (EmbeddingEngine, Qwen3.5-0.8B, llama.cpp, LRU cache)
    │   ├── retrieval.py     (三层检索 + 混合评分 语义 0.6 + 关键词 0.4)
    │   └── consolidation.py (记忆合并 + 情感分析 + 自动嵌入编码)
    │
    ├── tools/               (Agent 1,3: 2 内部 / Agent 2: 7 外部)
    ├── storage/             (SQLite WAL, 版本化迁移)
    ├── prompts/             (提示词模板, inner_drive / 破防/怨恨/梦境注入)
    └── models/              (EmotionalState, EmotionEvent)

后处理（不变）:
    Emotion → Memory consolidation → Reflection
```

---

## Agent 循环

### 状态机 (CLI)

```
BOOT → IDLE → PERCEIVE → THINK → ACT → REFLECT → IDLE
                ↑          │              │
                │    有 tool_call         │
                └────── 继续迭代 ←───────┘
```

### 事件驱动 (Web)

```
WebSocket 消息 → process_message() → _react_loop() → _send_segments()
```

---

## 情绪模型（四层架构）

**Layer 1 — 多维输入**：sentiment + 交互模式

**Layer 2 — 交叉调制 + 分速衰减**

| 情绪 | 半衰期 | 说明 |
|------|--------|------|
| surprise | 3 turns | 转瞬即逝 |
| fear | 6 | 快 |
| joy | 12 | 中等 |
| anger | 15 | 慢，残留 |
| sadness | 20 | 持久 |
| trust | 25 | 最难动摇 |

**Layer 3 — 怨恨残留**：anger > 0.6 触发，3%/turn 衰减，压制 joy + 减慢 trust 恢复

**Layer 4 — 情绪事件记忆**：强情绪自动记录，注入 prompt

**破防机制**：连续 5 次负面交互触发，累积伤害 1.4x/turn，三级递进

---

## 记忆系统

三层检索（支持混合评分）：
1. **Hot Memory**：高分 facts + 最新 experiences（常驻 prompt）
2. **Query-Guided**：语义 (0.6) + 关键词 (0.4) 混合评分 → LLM 重排序
3. **On-Demand**：LLM 主动调 recall 工具回溯

语义搜索：基于 Qwen3.5-0.8B-Q6_K.gguf（640MB, GPU CUDA, llama.cpp, 512维），
通过本地 llama-server /v1/embeddings API 计算余弦相似度。嵌入服务器不可用时自动降级为纯关键词检索。

短期记忆：ConversationBuffer（deque, 线程安全，重启从 DB 恢复最近 30 轮）

---

## 工具系统（9 个，三层分工）

| Agent | 工具 | 功能 | 后端 |
|------|------|------|------|
| Agent 2 | web_fetch | 网页内容提取 | AnySearch extract |
| Agent 2 | web_search | 网络搜索 | AnySearch API |
| Agent 2 | read_file | 读取本地文件 | 本地文件系统 |
| Agent 2 | glob | 文件名模式搜索 | 本地遍历 |
| Agent 2 | grep | 正则内容搜索 | 本地搜索 |
| Agent 2 | music_play | 播放音乐 | 默认播放器 |
| Agent 2 | notify | Windows toast 通知 | PowerShell WinRT |
| Agent 1,3 | recall | 回忆用户信息 | SQLite |
| Agent 1,3 | remember | 记住用户信息 | SQLite |

Agent 1 (InnerDriveAgent) 自主推理决策，输出自然语言工具请求。
Agent 2 (ToolAgent) 接收请求执行外部工具，ToolAttemptTracker 控制重试，temperature=0.3。
Agent 3 (Roleplay Agent) 接收 inner_drive_summary + tool_results，仅内部工具可用。

---

## 双端设计

| | CLI | Web |
|------|-----|-----|
| 驱动 | 状态机循环 | 事件驱动 |
| 输入 | stdin 线程 | WebSocket |
| 输出 | 打字机效果 | 分段独立气泡 + 情绪调速 |
| 主动对话 | IDLE 轮询 | proactive_loop 协程 |
| 会话 | 单用户 | SessionManager |

---

## 自主行为系统

### 作息

| 事件 | 时间 | 触发 |
|------|------|------|
| 午睡 | 12:00-13:00 | 情绪驱动 |
| 午醒 | 13:10-16:00 | 随机（arousal 高→早醒） |
| 夜睡 | 23:00-01:00 | 情绪驱动 |
| 晨醒 | 7:00-10:00 | 随机 |

睡前发消息，醒来分享 LLM 生成的梦境。

### 频率限制

| 行为 | 上限 |
|------|------|
| 探索（自主工具调用） | 1 次/小时 |
| 聊天（主动搭话） | 2 次/小时 |
| 梦境 | 每次睡眠 1 次 |

### 空闲阈值（情绪驱动）

| 情绪 | 阈值 |
|------|------|
| excited | 60s |
| joyful | 90s |
| engaged | 180s |
| neutral | 360s |
| sad | 900s |
| +resentment | 额外 +300s |

---

## 配置

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "",
  "api_model": "deepseek-v4-flash",
  "api_timeout": 180,
  "thinking": "disabled",
  "max_tokens": 512,
  "temperature": 0.8,
  "web_port": 8000
}
```

环境变量覆盖：`DEEPSEEK_API_KEY`, `ANYSEARCH_API_KEY` 等。

---

## 项目结构

```
├── main.py                  CLI 入口
├── web_main.py              Web 入口
├── config.py / config.json  配置系统
├── requirements.txt         依赖锁定
├── personality.json         人格 + 情绪状态
├── data/                    SQLite 数据库
├── changes/                 修改记录
├── doc/                     文档
│
├── core/                    核心引擎（三层架构）
│   ├── inner_drive.py       Agent 1 InnerDriveAgent（自主推理 + 缺口决策）
│   ├── tool_agent.py        Agent 2 ToolAgent（外部工具执行, temp=0.3）
│   ├── agent.py             Agent 3 Roleplay（人格驱动, temp=0.8）
│   ├── personality.py       情绪引擎（四层）
│   ├── provider.py          LLM API 客户端
│   └── dispatcher.py        tool_call 解析
├── memory/                  记忆系统
├── tools/                   Agent 1,3: 2 内部 / Agent 2: 7 外部
├── storage/                 SQLite（WAL + 迁移）
├── prompts/                 提示词模板
├── models/                  数据模型
├── ui/                      CLI 界面
└── web/                     Web 界面
    ├── server.py            FastAPI + WebSocket
    ├── session.py           SessionManager
    └── static/              前端
```

## 相关链接

- [里程碑与 Issue](milestones-and-issues.md)
- [技术文档](technical.md)
- [消息流转](message-flow.md)

## License

MIT
