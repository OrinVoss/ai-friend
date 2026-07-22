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

角色文件位于 `personalities/{role_id}.json`。编辑对应角色文件即可：

| 字段 | 说明 |
|------|------|
| `id` | 角色 ID（建议与文件名一致） |
| `personality.name` | AI 名字 |
| `personality.traits` | 性格特质及强度 (0~1) |
| `personality.speaking_style` | 说话风格描述 |
| `personality.backstory` | 背景故事 |
| `personality.interests` | 兴趣领域 |

- `personalities/default.json` 是 `config.json` 中 `personality_file` 指向的模板。
- Web 端启动时选择角色；角色与 session 严格一一对应（`session_id = role_id`），由 `core/personality_manager.py` 的 `PersonalityManager` 统一加载/保存/枚举角色，每个角色拥有独立的情绪与记忆。

### CLI 内置命令

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情 |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |
| `/help` | 帮助 |

---

## 架构总览

```
浏览器/终端
    │
    ├── CLI: python main.py → ConsoleInterface → Agent.run()
    │
    └── Web: python web_main.py → FastAPI + WebSocket
              │
              ├── web/server.py  (HTTP + WS + proactive_loop + Pydantic + 滑动窗口限流)
              ├── web/session.py (SessionManager + WebAgent：按角色加载 personality，session 隔离)
              ├── web/schemas.py (Pydantic 请求/响应模型)
              ├── web/rate_limit.py (内存滑动窗口限流)
              ├── web/static/    (HTML + CSS 变量 + JS，浅色响应式)
              └── personalities/ (角色定义目录，每个角色独立 JSON)
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
    ├── core/cli_controller.py   (CLI 输入循环)
    ├── core/message_handler.py  (消息入口 + 三层编排 + 重试循环)
    ├── core/personality.py      (四层情绪引擎)
    ├── core/personality_manager.py (人格加载/保存/枚举)
    ├── core/personality_validator.py (人格校验器)
    ├── core/provider.py         (LLM API 客户端)
    ├── core/dispatcher.py       (tool_call 解析执行)
    ├── core/cognitive_state.py  (CognitiveState, 输入去重/error_fallback 跳过)
    ├── core/inner_drive_state.py (内驱状态池/挂念清单)
    │
    ├── memory/
    │   ├── short_term.py        (ConversationBuffer, 线程安全)
    │   ├── long_term.py         (SQLite CRUD)
    │   ├── embeddings.py        (EmbeddingEngine, Qwen3.5-0.8B, llama.cpp, LRU cache)
    │   ├── retrieval.py         (三层检索 + 混合评分 语义 0.6 + 关键词 0.4)
    │   ├── retrieval_pipeline.py (多阶段检索管线 + Agent Profile 渲染)
    │   ├── consolidation.py     (记忆合并 + 统一固化 + 分层洞察 L1/L2/L3 + 自动嵌入编码 + 双写 Observation/FactV2)
    │   ├── fact_checker.py      (矛盾检测 + LLM 复核 + 置信度衰减 + 用户纠正 + 向上传播)
    │   ├── memory_agent.py      (Memory Agent: 向量召回 + 交叉验证 + 置信度回答)
    │   └── lifecycle.py         (MemoryLifecycleManager: Observation→Fact→Insight 生命周期)
    │
    ├── tools/               (Agent 1,3: 2 内部 / Agent 2: 7 外部)
    ├── storage/             (aiosqlite 异步, WAL, 版本化迁移；session_roles 记录 session→role 映射)
    ├── prompts/             (提示词模板, inner_drive / 破防/怨恨/梦境注入)
    └── models/              (EmotionalState / Turn / UserFact / Observation / FactV2 / InsightV2 等)

后处理（不变）:
    Emotion → Memory consolidation → Insight（2026-07-20 起，原 Reflection）
```

### 模块依赖

```
storage ← memory ← tools ← core   （主体单向依赖，无环）
models / prompts                  （纯数据 / 模板层，被各层引用）
```

- `core/agent.py` 是装配枢纽，直接依赖 15 个内部模块（全项目最多）。
- 跨层例外：`storage/repository.py`、`memory/long_term.py` 等直接使用 `core/async_utils.py` 的 `run_async()`，`memory/consolidation.py` 使用 `core/personality.py`；被引用方不回依赖，故不成环。
- 潜在环靠函数内 lazy import 打破：`agent ↔ cli_controller`、`short_term ↔ context_manager`、`prompts.system → core.prompt_cache`；`core/inner_drive.py` 顶层零内部 import（全部延迟到方法内）。
- 统一装配：`core/session_factory.py` 是 CLI/Web 唯一装配点，provider 与 embed engine 进程共享，Repository 按 session 隔离（P0）。

---

## Agent 循环

### 统一管线（CLI + Web，P0-P3 已完成）

```
用户输入 / 时间 tick
    │
    ▼
ConversationEngine（core/conversation_engine.py，唯一管线）
    ├── handle_message      → MessageHandler 三层 Agent 编排
    ├── handle_proactive / handle_explore
    └── 事件：on_token / on_message_done / on_proactive / on_sleep_reply / on_error
    │
    ├── CLI 前端：core/cli_controller.py（输入循环 + _CliFrontend 打字机渲染）
    └── Web 前端：web/server.py（WS 帧）+ web/session.py

时间驱动：RuntimeDriver（core/runtime_driver.py）
    ├── Web：asyncio task（WS init 时启动）
    └── CLI：守护线程（start_in_thread）
    └── 睡眠/唤醒/做梦/主动搭话/自由探索，两端同一节奏
```

---

## 提示词缓存与 Agent 上下文复用

为减少单次请求中系统提示词的重复构建，项目引入了分层提示词缓存（`core/prompt_cache.py`）和 Agent 1 → Agent 3 上下文摘要复用。

### 分层缓存

`prompts/system.py` 将系统提示拆分为三类块：

| 类型 | 内容 | 缓存策略 |
|------|------|----------|
| 静态块 | 身份定义、对话示例、内驱指令、工具说明 | 无 TTL，personality 文件变更时失效 |
| 慢变块 | 关系指标、长期记忆（facts/experiences/insights） | TTL 可配置（默认 60 秒） |
| 动态块 | 当前时间、情绪状态、工具历史、最近对话、破防状态、指令 | 不缓存 |

缓存键为 `(session_id, personality_version, component_name)`。`personality_version` 取 personality 文件的 `mtime:size:path`，因此编辑角色文件会自动让静态块失效。

### Agent 1 携带上下文摘要

`InnerDriveResult` 新增 `context_summary` 字段。Agent 1 完成判断后，会把已格式化的关系/记忆摘要写入该字段。Agent 3 构建 prompt 时，如果 `context_summary` 非空，直接使用它作为慢变块，不再调用 `retriever.retrieve_for_query()`，避免同一请求内两次检索长期记忆。

同一条消息内 Agent 1 的 assess / review / re_decide 共享 `_cs_memo` 缓存，`memory_agent.answer()` 每轮至多调用一次（R1，2026-07-20）；空 query（主动路径）跳过 MemoryAgent 置信度管线，直接走 retriever（F3）。

### 静态对话示例限制

`conversation_examples_max_turns` 控制系统提示中的对话示例仅在会话前 N 轮注入，之后自动省略，减少长期运行时的 token 开销。

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

多阶段检索管线共享（`memory/retrieval_pipeline.py`），`ContextBuilder` 按 Agent Profile 渲染：Agent 1 读取完整交叉验证结果，Agent 3 读取轻量事实/经历/关系，Agent 2 不读记忆。

语义搜索：基于 Qwen3.5-0.8B-Q6_K.gguf（640MB, GPU CUDA, llama.cpp, 1024维），
通过本地 llama-server /v1/embeddings API 计算余弦相似度。嵌入服务器不可用时自动降级为纯关键词检索。

短期记忆：ConversationBuffer（deque, 线程安全，重启从 DB 恢复最近 30 轮）

长期记忆共 9 张表（schema v6 删除归档表后实为 9 张），已按 `session_id` 隔离：`facts_v2`（经验证的事实，confidence/stability/freshness/importance 四维评分）、`experiences`、`insights_v2`（假设性洞察，hypothesis + evidence + confidence + expires_at）、`conversation_turns`、`relationship_metrics`、`relationship_snapshots`、`session_roles`（`session_id → role_id` 映射），以及记忆生命周期 Layer 1 的 `observations`（原始观察）。旧 `user_facts` / `reflections` 表已分别于 schema v4/v5 迁移并归档，归档表于 schema v6（2026-07-21，A8）物理删除（迁移前自动备份在 `data/backups/`）。Layer 6 已强制 `session_id = role_id`（`assemble_session` 与 `SessionManager.get_or_create` 不一致即抛错），因此这些表也按角色隔离，实现「一个角色一份记忆」。

记忆生命周期（一期 Fact 上线 2026-07-18，二期 Insight 上线 2026-07-20）：对话 → Observation（原始观察，低置信度）→ 验证/用户确认 → Fact（四维评分）→ Insight（假设 + 证据链 + confidence + expires_at）。由 `memory/lifecycle.py` 的 MemoryLifecycleManager 提供 observe / promote / verify / contradict / create_insight / verify_insight / expire_insight / decay / gc；MemoryConsolidator 每批合并先写入一条 Observation（整批对话文本，无额外 LLM 调用），提取的 fact 再 promote 为 FactV2；统一固化（`consolidation_unified_call`，默认 on）将事实提取+体验总结+L1 insight 合并为 1 次 LLM 调用；分层 L1/L2/L3 生成结构化 Insight（LLM 输出 JSON：hypothesis/insight_type/evidence/confidence/needs_more_evidence，解析失败静默跳过），单写 insights_v2。读路径全部走 facts_v2 / insights_v2（repository 旧方法名适配，Reflection 返回形状不变：content=hypothesis、significance=confidence）；旧 `user_facts` / `reflections` 表数据已迁移并归档（schema v4 / v5），归档表已于 schema v6 物理删除。

矛盾检测与传播（2026-07-20）：FactChecker 检出的嵌入相似候选矛盾先经 LLM 复核（`verify_fn`，复述/近义否决则保留旧事实），同键不同值的直接判定不复核；Fact 被推翻时向上传播——引用它的 active Insight 标记 `needs_more_evidence` 且 confidence ×0.5。Memory Agent 证据池纳入 active Insight（待验证项显式标注），query 与指代锚点余弦达到 `memory_agent_coreference_threshold`（默认 0.78）时先由 LLM 改写为自足形式再检索（P2）。Memory Agent 证据池纳入 active Insight（待验证项显式标注），query 与指代锚点余弦达到 `memory_agent_coreference_threshold`（默认 0.78）时先由 LLM 改写为自足形式再检索（P2）。

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
| 驱动 | ConversationEngine + RuntimeDriver | ConversationEngine + RuntimeDriver |
| 输入 | stdin 线程 | WebSocket |
| 输出 | 打字机效果 | 分段独立气泡 + 情绪调速 |
| 主动对话 | IDLE 轮询 | proactive_loop 协程 |
| 会话 | 单用户 | SessionManager |

---

## 自主行为系统

### 两级门控决策 (#125)

```
Stage 1 (轻量): ProactivityManager.calculate_proactivity(idle) → score
                random() < score → 触发 Stage 2

Stage 2 (LLM):  InnerDriveAgent.assess_proactive(idle, time) → ProactiveIntent
                → action: "chat" | "explore" | "silent"
                → topic_hint, reasoning（传入 Agent 3 作上下文）

Stage 3 (执行):  chat → MessageHandler.handle_proactive(intent=intent)
                explore → MessageHandler.handle_explore(intent=intent)
                silent → 不操作（不消耗频率限制）
```

主动行为决策现在由 InnerDrive (Agent 1) 的 LLM 推理驱动，替换了原来的随机话题选择和 40/60 分流。ProactivityManager 保留作为 Stage 1 轻量预筛选器（避免每 15 秒调用 LLM）。

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
  "web_host": "0.0.0.0",
  "web_port": 8000,
  "web_access_token": "",
  "allowed_origins": [],
  "consolidation_unified_call": true,
  "use_memory_agent": false,
  "proactive_think_loop": true,
  "conversation_examples": [
    {
      "user": "今天去外滩拍照了，日落的时候光影特别好",
      "replies": [
        "蛙趣！那肯定好看！发出来看看[旺柴]",
        "哇哇哇，听起来就很绝！拍了多久啊？"
      ]
    }
  ]
}
```

环境变量覆盖：`DEEPSEEK_API_KEY`, `ANYSEARCH_API_KEY` 等。
- `allowed_origins`：默认已包含 `localhost:8000` 和 `127.0.0.1:8000`，可在此追加额外 CORS 来源。
- `conversation_examples`：系统提示词中的对话风格示例，支持自定义以减少 token 浪费。

---

## 项目结构

```
├── main.py                  CLI 入口
├── web_main.py              Web 入口
├── config.py / config.json  配置系统
├── requirements.txt         依赖锁定
├── personalities/           角色定义目录（每个角色独立 JSON，含个性+情绪）
│   ├── default.json           默认角色模板
│   └── 小星.json               示例角色
├── data/                    SQLite 数据库
├── changes/                 修改记录
├── doc/                     文档
│
├── core/                    核心引擎（23 模块，三层架构）
    │   ├── inner_drive.py       Agent 1 InnerDriveAgent（自主推理 + 记忆检索 + 缺口决策 + 主动沉思循环）
    │   ├── tool_agent.py        Agent 2 ToolAgent（外部工具执行 + ToolAttemptTracker, temp=0.3）
    │   ├── agent.py             Agent 3 Roleplay（人格驱动, temp=0.8）+ ReAct 循环
    │   ├── message_handler.py   消息入口（handle_message / proactive / explore 三层编排）
    │   ├── context_manager.py   上下文窗口管理（token 估算 + 压缩 + 摘要）
    │   ├── prompt_cache.py      Prompt 分层缓存（静态/慢变/动态块复用, #160）
    │   ├── session_factory.py   CLI/Web 共享会话装配（统一管线 P0，per-session Repository）
    │   ├── conversation_engine.py 统一对话引擎 + Frontend 事件接口（统一管线 P1）
    │   ├── runtime_driver.py    共享时间驱动（睡眠/唤醒/主动搭话/探索，统一管线 P2）
    │   ├── personality.py       情绪引擎（四层）
    │   ├── personality_manager.py 人格局加载/保存/枚举（统一入口）
    │   ├── personality_validator.py 人格校验器（A4，情绪状态校验）
    │   ├── sleep_manager.py     睡眠系统（窗口判断 + 梦境生成 + 状态持久化）
    │   ├── proactivity.py       主动行为（评分 + 频率限制）
    │   ├── cli_controller.py    CLI 输入循环 + 命令层（ConversationEngine 前端）
    │   ├── provider.py          LLMProvider ABC + DeepSeekProvider 实现（OpenAI 兼容，流式，JSON mode）
    │   ├── monitor.py           LLM API 调用监控（环形缓冲，开发调试用）
    │   ├── embedding_server.py  本地嵌入服务生命周期（CLI/Web 共享）
    │   ├── logging_setup.py     日志配置（logs/YYYY-MM-DD.log + stderr）
    │   ├── async_utils.py       异步→同步桥接 run_async()（线程池安全）
    │   ├── dispatcher.py        tool_call 三层解析（JSON / XML / 裸 JSON）+ 执行 + 别名下沉
    │   ├── cognitive_state.py   CognitiveState Phase 1+2（输入去重/error_fallback 跳过/Agent 1 决策温度 0.3）
    │   └── inner_drive_state.py 内驱状态池（挂念清单/沉思循环/响应线索）
    ├── memory/                  记忆系统（9 模块）
    │   ├── short_term.py        ConversationBuffer（deque, 线程安全）
    │   ├── long_term.py         LongTermMemory（aiosqlite 异步 CRUD + 同步兼容包装）
    │   ├── embeddings.py        本地嵌入语义搜索（Qwen3.5-0.8B, llama.cpp, 1024维, LRU cache）
    │   ├── retrieval.py         三层检索 + 混合评分（语义 0.6 + 关键词 0.4 + 置信度权重 0.15）
    │   ├── retrieval_pipeline.py 多阶段检索管线（QueryClues/ContextBuilder/Agent Profile 渲染）
    │   ├── consolidation.py     记忆合并 + FactChecker 集成 + 自动嵌入编码 + 双写 Observation/FactV2 + unified consolidation
    │   ├── fact_checker.py      矛盾检测 + LLM 复核 + 置信度衰减 + 用户纠正 + 向上传播
    │   ├── memory_agent.py      Memory Agent：向量召回 + 交叉验证 + 置信度回答 + Insight 证据池 + 向量锚点指代解析（确定性管道，P0~P2）
    │   └── lifecycle.py         MemoryLifecycleManager（Observation→Fact: observe/promote/verify/contradict/decay/gc）
├── tools/                   Agent 1,3: 2 内部 / Agent 2: 7 外部
├── storage/                 SQLite（aiosqlite 异步 + WAL + 版本化迁移 + 软删除）
├── prompts/                 提示词模板
├── models/                  数据模型（EmotionalState / Turn / UserFact / Observation / FactV2）
├── ui/                      CLI 界面
└── web/                     Web 界面
    ├── server.py            FastAPI + WebSocket + Pydantic + 滑动窗口限流
    ├── session.py           SessionManager + WebAgent（封装 Agent 私有接口）
    ├── schemas.py           Pydantic 请求/响应模型
    ├── rate_limit.py        内存滑动窗口限流
    └── static/              前端（CSS 变量 + 无内联颜色）
```

## 相关链接

- [API 文档](api.md)
- [启动流程](startup-flow.md)
- [配置参考](config-reference.md)
- [人格定制指南](personality-guide.md)
- [测试指南](testing-guide.md)
- [工具开发指南](tool-development.md)
- [Prompt 工程参考](prompt-reference.md)
- [部署手册](deployment.md)
- [已知问题](known-issues.md)
- [系统性解决方案](systematic-solution.md)
- [重构设计与进度](refactor/README.md)
- [技术文档](technical.md)
- [消息流转](message-flow.md)

## License

MIT
