# 技术文档

## 目录

1. [整体架构](#1-整体架构)
2. [Agent 循环](#2-agent-循环)
3. [情感系统](#3-情感系统)
4. [记忆系统](#4-记忆系统)
5. [工具系统](#5-工具系统)
6. [提示词工程](#6-提示词工程)
7. [Web 界面](#7-web-界面)
8. [数据模型](#8-数据模型)
9. [存储层](#9-存储层)
10. [配置系统](#10-配置系统)
11. [部署说明](#11-部署说明)

---

## 1. 整体架构

### 1.1 模块依赖图

```
main.py / web_main.py
    │
    ├── config.py ─────────── 配置加载（config.json + Config dataclass）
    │
    ├── core/
    │   ├── agent.py ──────── 状态机 + ReAct 循环（核心调度器）
    │   ├── personality.py ── 人格加载 + 情绪动力学
    │   ├── provider.py ───── LLM API 客户端（OpenAI 兼容）
    │   └── dispatcher.py ─── tool_call XML 解析 + 工具调度
    │
    ├── memory/
    │   ├── short_term.py ─── ConversationBuffer（内存 deque）
    │   ├── long_term.py ──── LongTermMemory（SQLite CRUD 封装）
    │   ├── retrieval.py ──── 三层检索 + 评分 + LLM 重排序
    │   └── consolidation.py ─ 记忆合并（短→长转移）
    │
    ├── tools/
    │   ├── traits.py ─────── Tool 基类 + ToolRegistry
    │   ├── memory_tools.py ─ recall / remember 工具
    │   ├── file_tools.py ─── read_file 工具
    │   └── notify_tool.py ── notify 工具
    │
    ├── storage/
    │   ├── database.py ───── SQLite 连接 + Schema + Migration
    │   └── repository.py ─── 数据访问层（CRUD）
    │
    ├── prompts/
    │   ├── system.py ─────── System prompt 动态组装
    │   └── templates.py ──── 抽取/总结/反思 prompt 模板
    │
    ├── models/
    │   ├── personality.py ── 人格数据模型
    │   ├── memory.py ─────── 记忆数据模型
    │   └── conversation.py ─ 对话数据模型
    │
    ├── ui/
    │   ├── cli.py ────────── 命令行界面 + 非阻塞输入线程
    │   └── display.py ────── 打字机效果 + 彩色输出
    │
    └── web/
        ├── server.py ─────── FastAPI + WebSocket 端点
        ├── session.py ────── 会话管理器
        └── static/ ───────── 前端静态资源
```

### 1.2 设计原则

- **单向依赖**：core → memory → storage，core → tools，不存在循环依赖
- **接口隔离**：provider 抽象 LLM 调用，storage 抽象持久化，各层可独立替换
- **数据驱动**：所有状态变化通过数据模型传递，模块间不直接耦合

---

## 2. Agent 循环

### 2.1 状态机

Agent 采用有限状态机（FSM）模式，定义 7 个状态：

```
       ┌──────────────────────────────────────────────┐
       │                                              │
       ▼                                              │
   ┌──────┐    ┌────────┐    ┌──────────┐    ┌──────┐ │
   │ BOOT │───▶│  IDLE  │───▶│ PERCEIVE │───▶│THINK│ │
   └──────┘    └────────┘    └──────────┘    └──┬───┘ │
                     ▲                          │     │
                     │                     ┌────┘     │
                     │                     ▼          │
                     │                 ┌────────┐     │
                     │                 │  ACT   │     │
                     │                 └───┬────┘     │
                     │                     │          │
                     │                     ▼          │
                     │                 ┌──────────┐   │
                     │                 │ REFLECT  │───┘
                     │                 └──────────┘
                     │
                     │                 ┌──────────┐
                     └─────────────────│ SHUTDOWN │
                                       └──────────┘
```

#### BOOT
- 加载人格配置
- 初始化数据库连接
- 播放欢迎语
- → IDLE

#### IDLE
- **CLI 模式**：非阻塞读取 stdin，后台守护线程将输入推入队列
- **Web 模式**：等待 WebSocket 消息
- 如果空闲时间 > `proactive_min_idle`：
  - 调用 `_calculate_proactivity()` 计算主动发起分数
  - 随机命中 → 直接进入 THINK（主动版本）
- → PERCEIVE（有输入）或 THINK（主动）

#### PERCEIVE
- 存储用户消息到 ConversationBuffer 和 SQLite
- 调用 MemoryRetriever 检索相关记忆
- → THINK

#### THINK
- 组装 System Prompt（6 个区块）
- 构建 Messages 数组，动态计算 token 占用，塞满 80% 上下文
- 调用 provider.generate()，流式接收响应
- 解析 `<tool_call>` XML 标签
- → ACT

#### ACT
- 如果有工具调用：
  - 执行工具
  - 将结果格式化为 `<tool_result>` 追加到消息列表
  - → THINK（下一轮 ReAct 迭代）
- 如果没有工具调用：
  - 输出最终回复
  - → REFLECT

#### REFLECT
- 情感分析 → 更新 EmotionalState
- 检查是否需要记忆合并（每 5 轮 / 高强度情绪）
- 每 10 轮保存 personality.json
- → IDLE

#### SHUTDOWN
- 强制记忆合并
- 保存所有状态
- 关闭数据库连接

### 2.2 ReAct 循环

每次用户输入可能触发多轮 ReAct 迭代（最多 `_max_tool_iterations = 5` 次）：

```
第 1 轮：THINK → LLM 返回 "<tool_call>..."
        ACT → 执行工具，结果喂回
第 2 轮：THINK → LLM 基于工具结果继续
        ACT → 这次没有 tool_call → 最终回复 → REFLECT
```

### 2.3 双模式设计

Agent 支持两种运行模式：

**CLI 模式**（`agent.run()`）：
- 同步主循环 `while self._running`
- 通过 ConsoleInterface 读写终端
- 流式输出打字机效果

**Web 模式**（`agent.process_message()` / `agent.process_proactive()`）：
- 单次调用，返回完整回复
- 通过 `on_token` 回调逐字推送
- 由 WebSocket 协程驱动

```python
# CLI 模式 - 状态机驱动
def run(self):
    while self._running:
        handler = {AgentState.IDLE: self._on_idle, ...}[self.state]
        handler()

# Web 模式 - 事件驱动
def process_message(self, user_input: str, on_token=None) -> str:
    # 直接走核心逻辑，绕过状态机
    return self._react_loop(messages, on_token)
```

---

## 3. 情感系统

### 3.1 情绪维度

采用三维情绪模型：

| 维度 | 范围 | 描述 |
|------|------|------|
| Valence | -1.0 ~ 1.0 | 积极/消极 |
| Arousal | 0.0 ~ 1.0 | 兴奋/平静 |
| Dominant Emotion | string | 当前主导情绪标签 |

### 3.2 8 维基础情绪

基于 Plutchik 情绪轮，增加 8 个连续维度（0.0 ~ 1.0）：

```
joy       trust       fear      surprise
sadness   anticipation anger     disgust
```

每个维度独立衰减，受对话内容调制。

### 3.3 情绪动力学

```
每次交互：
  1. estimate_emotional_impact(sentiment, personal_sharing, topic_energy)
     → 计算 delta_valence, delta_arousal, primary_deltas

  2. shift(dv, da, primary_deltas)
     → valence += dv × (1 - inertia)
     → arousal += da × (1 - inertia)
     → primary_emotions += primary_deltas × (1 - inertia)

  3. decay()
     → valence 趋向 baseline
     → baseline 趋向 mood（慢速）
     → primary_emotions 趋向中性
```

### 3.4 特质调制

性格特质（traits）对情绪的影响：

| Trait | 效果 |
|-------|------|
| empathy > 0.7 | 情感反应 1.5x |
| playfulness > 0.6 | arousal 衰减更慢 |
| warmth > 0.7 | trust 提升更多 |
| thoughtfulness > 0.6 | anticipation 提升更多 |

### 3.5 情感标签映射

```
(V > 0.5, A > 0.6)          → excited
(V > 0.5, A < 0.4)          → content
(V > 0, 0.4 <= A <= 0.6)    → engaged
(V < 0, A > 0.5)            → anxious
(V < -0.3, A < 0.4)         → melancholy
(V < -0.5, A > 0.6)         → frustrated
primary_emotion > 0.7        → 对应标签（joyful/trusting/afraid...）
```

---

## 4. 记忆系统

### 4.1 架构

```
短期记忆（ConversationBuffer）
    │ deque, maxlen=N, 内存
    │
    ├── 每轮对话直接追加
    │
    ▼
长期记忆（SQLite 4 张表）
    ├── user_facts       用户事实（评分 + 置信度 + 重要性）
    ├── experiences      共享体验（情感色调 + 重要性）
    ├── reflections      反思洞察（类型 + 重要性）
    └── conversation_turns 完整对话历史
```

### 4.2 三层检索

#### Layer 1: Hot Memory

始终注入 prompt 的高分记忆：
- Top 5 facts（按 composite_score）
- 最新 2-3 条 experiences
- 当前关系状态
- 最新 3 条 reflections

#### Layer 2: Query-Guided

```
用户输入
    │
    ├ Step A: 评分过滤（纯 SQL，~1ms）
    │   score = composite_score × 0.2
    │         + importance × 0.3         ← 重要度权重最高
    │         + keyword_hits × 0.2
    │         + category_boost × 0.2
    │         - recall_penalty × 0.02
    │
    └ Step B: LLM 重排序（候选 > 15 条时触发）
        极小 LLM 调用（10-20 tokens 输出）
        → 只取 LLM 选中的 3-8 条注入 prompt
```

#### Layer 3: On-Demand

LLM 在回复中输出 `<tool_call>{"name": "recall", ...}</tool_call>` 主动回溯，不占用每轮 prompt 空间。

### 4.3 记忆合并（Consolidation）

触发条件：
- 每 5 轮对话
- 情绪强度 |valence| > 0.7
- pending buffer >= 10 条
- 空闲 > 120s 且有未合并内容

合并流程：

```
pending_turns
    │
    ├ Step 1: FACT EXTRACTION
    │   LLM 从对话原文抽取事实
    │   格式：FAT|category|key|value|confidence|importance
    │   存入 user_facts（UNIQUE(category, key)，合并策略）
    │
    ├ Step 2: EXPERIENCE SUMMARIZATION
    │   LLM 将对话片段总结为共享体验
    │   格式：SUMMARY|TONE|SIGNIFICANCE|IMPORTANCE|TAGS
    │   存入 experiences
    │
    ├ Step 3: REFLECTION GENERATION
    │   每轮 consolidation 触发
    │   基于 experiences + facts + relationship 生成洞察
    │   类型：self_discovery / user_discovery / relationship_insight / pattern / prediction
    │   存入 reflections
    │
    └ Step 4: RELATIONSHIP UPDATE
        familiarity += 0.02
        if sentiment > 0.3: trust += sentiment × 0.05
        if personal_sharing: intimacy += 0.03
```

### 4.4 记忆生命周期

```
创建 → 评分衰减（composite_score × 0.99 / 天）
  → score < 0.2 → 归档（is_active = 0）
    → 归档 > 90 天 → 软删除
```

修剪触发条件（每次 consolidation 执行）：

| 表 | 上限 | 淘汰策略 |
|----|------|----------|
| user_facts | 200 | 按 composite_score ASC 归档超出部分 |
| experiences | 100 | 按 composite_score ASC 归档 |
| reflections | 50 | 按 significance ASC 删除 |

### 4.5 上下文压缩

```
模型上下文：180,000 tokens (DeepSeek v4)
压缩阈值：80% = 144,000 tokens
触发：每次请求动态计算 token，超出时自动执行

压缩过程：
1. 收集所有非 system 消息
2. 发送给 LLM 生成对话摘要（100-150 字）
3. 摘要注入 system prompt
4. 清空 ConversationBuffer
5. token 计数器归零
```

---

## 5. 工具系统

### 5.1 Tool 基类

```python
class Tool:
    def name(self) -> str: ...
    def description(self) -> str: ...
    def parameters_schema(self) -> dict: ...  # JSON Schema
    def execute(self, args: dict) -> ToolResult: ...
```

### 5.2 ToolRegistry

```python
registry = ToolRegistry()
registry.register(MyTool())
registry.list_specs()       # → list[ToolSpec]
registry.format_for_prompt()  # → markdown 格式工具列表
```

`format_for_prompt()` 输出示例：

```
- **recall**: 回忆关于用户的信息或共同经历。
  参数: {"type": "object", "properties": {"query": {"type": "string"}}}
```

### 5.3 工具调用协议

LLM 回复中的工具调用格式：

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "用户喜欢什么"}}
</tool_call>
```

支持回退格式：
- 裸 JSON：`{"name": "...", "arguments": {...}}`
- 嵌套 JSON：`{"tool_call": {"name": "...", "arguments": {...}}}`

解析流程（`core/dispatcher.py`）：

```
1. 剥离 <think>...</think> 块
2. 正则提取 <tool_call>...</tool_call>
3. JSON 解析每个调用
4. 参数别名归一化（search → query, text → content 等）
5. 回退：尝试将整个响应作为 JSON 解析
```

### 5.4 内置工具

| 工具 | 功能 | 参数 |
|------|------|------|
| `recall` | 回忆用户信息或共同经历 | query: string |
| `remember` | 记住用户重要信息 | category, key, value, importance |
| `read_file` | 读取本地文件 | path, max_chars |
| `notify` | 发送 Windows 桌面通知 | title, message, duration |

### 5.5 虚假操作检测

检测 LLM 声称执行了操作但未调用工具的情况：

```python
def contains_fake_action(text: str) -> bool:
    keywords = ["已发送", "已通知", "已经为你", "已记住", "已回忆"]
    return any(kw in text for kw in keywords)
```

检测到后自动重新提示 LLM 实际调用工具。

---

## 6. 提示词工程

### 6.1 System Prompt 组装

每轮动态组装，6 个区块：

```
=== Block 0: 当前时间 ===
当前时间：2026-05-28 15:30 Thursday

=== Block 1: 身份核心 ===
你是{name}，一个有情感、有记忆的 AI 朋友。
你的核心特质：{traits}
你的说话风格：{speaking_style}
你的背景：{backstory}

=== Block 2: 当前情绪状态 ===
你感到 {mood}。
（情绪{valence_desc}，{arousal_desc}）
说话按这个感觉来。

=== Block 3: 关系指标 ===
信任: 0.3  熟悉度: 0.3
亲密: 0.3  趣味: 0.3

=== Block 4: 长期记忆 ===
你知道的关于用户的事情：
- 名字: 小陈
- 摄影喜好: 城市风景和街拍

你们的共同回忆：
- [温暖] 分享了养宠物的趣事

你的最近思考：
- 用户似乎很喜欢拍照

=== Block 5: 工具列表 ===
可用工具（recall / remember / read_file / notify）
<tool_call>{"name": "...", "arguments": {...}}</tool_call>

=== Block 6: 最近对话 + 指令 ===
用户：你好
你：你好呀！

指令：
像朋友一样回她。
- 嘴可以贱，但心要暖
- 分享好事就真心夸，吐槽就跟着一起骂
- 如果用户说了个人信息，用 remember 记住
- 需要回忆之前的事用 recall 查询

=== Block 7: 对话示例 ===
用户：今天去外滩拍照了
你：蛙趣！那肯定好看！发出来看看[旺柴]
```

### 6.2 Prompt 模板

#### 事实抽取（FACT_EXTRACTION_PROMPT）

```
从这段对话中提取关于用户的事实信息。
每个事实输出一行，格式：
FACT|分类|关键词|值|置信度|重要性

分类: preference, identity, event, relationship, routine
置信度: 0.0~1.0
重要性: 0.0~1.0（0.3以下=临时 0.6=长期 1.0=永久）
```

#### 体验总结（EXPERIENCE_SUMMARIZATION_PROMPT）

```
将这段对话总结为一段共享体验。
格式：
SUMMARY: | TONE: | SIGNIFICANCE: | IMPORTANCE: | TAGS:
```

#### 反思生成（REFLECTION_PROMPT）

```
回顾你和用户的最近互动，产生新的洞察。
类型：self_discovery / user_discovery / relationship_insight / pattern / prediction
```

---

## 7. Web 界面

### 7.1 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI (ASGI) |
| 实时通信 | WebSocket |
| 前端 | 纯 HTML + CSS + JS |
| 运行 | Uvicorn |
| 端口 | 8000（可配置） |

### 7.2 WebSocket 协议

```
客户端 → 服务端:
  {"type": "init", "session_id": "xxx"}        # 初始化会话
  {"type": "message", "content": "你好"}       # 发送消息
  {"type": "ping"}                              # 心跳

服务端 → 客户端:
  {"type": "init_ok", "session_id": "xxx", "emotion": "engaged"}
  {"type": "segment", "content": "你好呀！"}    # 消息分段
  {"type": "done", "content": "...", "emotion": "engaged", "turn": 5}
  {"type": "error", "content": "..."}
  {"type": "pong"}
```

### 7.3 消息分段与速度控制

AI 回复被按句子拆分为多条独立消息，模拟真人打字节奏：

```python
def _split_segments(text: str) -> list[str]:
    # 1. 按 。！？.!?\n 拆分
    # 2. 超过 40 字的在 ，,；; 再拆
    # 3. 合并碎片化短句

def _calc_delay(emotion: str, seg_len: int) -> float:
    # base_speed[emotion] × (1 + seg_len/80) × random(0.8, 1.5)
```

各情绪基础速度：

| 情绪 | 基础间隔 |
|------|----------|
| excited / surprised | 1.8s |
| joyful / anticipating | 2.0s |
| trusting | 2.5s |
| anxious / angry | 2.5s |
| afraid / disgusted | 3.0s |
| engaged | 3.0s |
| frustrated | 3.5s |
| content | 3.5s |
| neutral | 4.0s |
| melancholy | 5.0s |
| sad | 6.0s |

### 7.4 主动对话后台任务

```python
async def _proactive_loop(websocket, session_id):
    while True:
        idle = time.time() - agent.last_activity_time
        if idle > proactive_min_idle:
            score = agent._calculate_proactivity(idle)
            if random.random() < score:
                response = agent.process_proactive()
                await send_segments(websocket, response)
        await asyncio.sleep(15)
```

用户发新消息时自动重置 `last_activity_time`，断开 WebSocket 时自动取消任务。

### 7.5 会话管理

```python
class SessionManager:
    _sessions: dict[session_id → WebAgent]
    _lock: Lock

    def get_or_create(session_id) -> WebAgent
    def remove(session_id)
```

- 每个浏览器标签页独立 Agent 实例
- 独立 Personality（情绪互不影响）
- 独立 ConversationBuffer（短期记忆隔离）
- 共享 SQLite（长期记忆按 session_id 过滤）

---

## 8. 数据模型

### 8.1 Personality Models (`models/personality.py`)

```python
@dataclass
class Trait:
    name: str
    value: float          # 0.0 ~ 1.0

@dataclass
class EmotionalState:
    valence: float        # -1.0 ~ 1.0
    arousal: float        # 0.0 ~ 1.0
    baseline_valence: float
    baseline_arousal: float
    decay_rate: float
    mood_valence: float
    mood_arousal: float
    mood_decay_rate: float
    inertia: float        # 情绪惯性（0=瞬间变，1=不变）
    joy: float            # 8 维基础情绪
    trust: float
    fear: float
    surprise: float
    sadness: float
    anticipation: float
    anger: float
    disgust: float
    history: list[str]    # 最近 10 轮情绪

@dataclass
class PersonalityConfig:
    name: str
    traits: list[Trait]
    speaking_style: str
    backstory: str
    interests: list[str]
```

### 8.2 Memory Models (`models/memory.py`)

```python
@dataclass
class UserFact:
    id: Optional[int]
    category: str         # preference/identity/event/relationship/routine
    fact_key: str
    fact_value: str
    confidence: float     # 0.0~1.0 事实可靠性
    importance: float     # 0.0~1.0 长久重要性
    created_at: str
    recall_count: int
    is_active: bool
    composite_score: float

@dataclass
class Experience:
    id: Optional[int]
    summary: str
    emotional_tone: str
    significance: float   # 0.0~1.0
    importance: float     # 0.0~1.0
    tags: list[str]
    turn_range: tuple[int, int]
    is_archived: bool

@dataclass
class Reflection:
    id: Optional[int]
    content: str
    insight_type: str     # self_discovery/user_discovery/relationship_insight/pattern/prediction
    significance: float
```

### 8.3 Conversation Models (`models/conversation.py`)

```python
@dataclass
class Turn:
    turn_id: int
    role: str             # user / assistant
    content: str
    timestamp: datetime
    metadata: dict

@dataclass
class MemoryContext:
    facts: list[UserFact]
    experiences: list[Experience]
    reflections: list[Reflection]
    relationship: dict[str, float]  # trust/familiarity/intimacy/playfulness
```

---

## 9. 存储层

### 9.1 SQLite Schema

```sql
CREATE TABLE user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    importance REAL DEFAULT 0.5,
    source_turn INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    recall_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    composite_score REAL DEFAULT 1.0,
    UNIQUE(category, fact_key)
);

CREATE TABLE experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    emotional_tone TEXT,
    significance REAL DEFAULT 0.5,
    importance REAL DEFAULT 0.5,
    tags TEXT DEFAULT '[]',
    turn_range_start INTEGER,
    turn_range_end INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    recall_count INTEGER DEFAULT 0,
    is_archived INTEGER DEFAULT 0,
    composite_score REAL DEFAULT 0.5
);

CREATE TABLE reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    insight_type TEXT,
    related_experience_ids TEXT DEFAULT '[]',
    significance REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE relationship_metrics (
    dimension TEXT PRIMARY KEY,
    value REAL DEFAULT 0.3,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE conversation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    emotional_state TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.2 WAL 模式

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
```

- 读写不互斥，高并发场景性能更好
- 自动恢复，崩溃后不会损坏

### 9.3 连接管理

```python
class Database:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()

    @contextmanager
    def cursor(self):
        with self._lock:
            yield c
            self.conn.commit()
```

线程安全：所有写操作通过 `cursor()` 上下文管理器，内部加锁。

---

## 10. 配置系统

### 10.1 优先级

```
config.json  >  Config dataclass 默认值
```

`config.json` 不存在时使用代码内的默认值。

### 10.2 完整配置项

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "reasoning_effort": "",
  "personality_file": "personality.json",
  "db_path": "ai_friend.db",
  "short_term_capacity": 500,
  "consolidation_interval": 5,
  "proactive_min_idle": 180.0,
  "proactive_max_interval": 600.0,
  "typing_speed": 0.005,
  "temperature": 0.8,
  "max_tokens": 512,
  "max_facts": 200,
  "max_experiences": 100,
  "max_reflections": 50,
  "web_host": "0.0.0.0",
  "web_port": 8000,
  "log_level": "INFO"
}
```

---

## 11. 部署说明

### 11.1 环境要求

- Python 3.12+
- 依赖：`requests`, `tiktoken`, `plyer`, `fastapi`, `uvicorn`

### 11.2 安装

```bash
pip install requests tiktoken plyer fastapi uvicorn
```

### 11.3 配置

```bash
cp config.example.json config.json
# 编辑 config.json 填入你的 API key
```

### 11.4 启动

```bash
# CLI 模式
python main.py

# Web 模式（开发）
python web_main.py

# Web 模式（生产）
uvicorn web.server:app --host 0.0.0.0 --port 8000 --workers 4
```

### 11.5 自定义人格

编辑 `personality.json`，修改 name / traits / speaking_style / backstory 即可。

### 11.6 数据文件

| 文件 | 说明 | gitignore |
|------|------|-----------|
| `personality.json` | 人格定义 + 情绪状态持久化 | 否 |
| `ai_friend.db` | SQLite 数据库 | 是 |
| `config.json` | 用户配置 | 是 |

### 11.7 Token 估算

使用 `tiktoken` 库的 `cl100k_base` 编码精确估算 token 数。不可用时回退到启发式：

```
CJK 字符: ÷ 1.5
ASCII 字母: ÷ 4
数字: ÷ 3
其他: ÷ 8
```
