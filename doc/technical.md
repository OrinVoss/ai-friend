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
    ├── config.py ─────────── 配置加载（config.json + Config dataclass + 环境变量）
    │
    ├── core/
    │   ├── inner_drive.py ────── Agent 1 InnerDriveAgent：自主推理 + 记忆检索 + 缺口决策
    │   ├── tool_agent.py ─────── Agent 2 ToolAgent：外部工具执行 + ToolAttemptTracker
    │   ├── agent.py ──────────── Agent 3 Roleplay：人格驱动 + ReAct 循环, temp=0.8
    │   ├── context_manager.py ── 上下文窗口管理（token估算+压缩）
    │   ├── sleep_manager.py ──── 睡眠/唤醒系统（窗口判断+梦境）
    │   ├── proactivity.py ────── 主动行为引擎（评分+话题+限速）
    │   ├── cli_controller.py ─── CLI 状态机（run + _on_* handlers）
    │   ├── message_handler.py ── 消息入口（process_* 三方法）
    │   ├── personality.py ────── 情绪引擎（四层：输入→调制→怨恨→记忆）
    │   ├── provider.py ───────── LLM API 客户端（OpenAI 兼容，流式）
    │   └── dispatcher.py ─────── tool_call XML 解析 + 工具调度
    │
    ├── memory/
    │   ├── short_term.py ─── ConversationBuffer（内存 deque）
    │   ├── long_term.py ──── LongTermMemory（SQLite CRUD 封装）
    │   ├── retrieval.py ──── 三层检索 + 评分 + LLM 重排序
    │   └── consolidation.py ─ 记忆合并（短→长转移 + 修剪）
    │
    ├── tools/
    │   ├── traits.py ──────── Tool 基类 + ToolRegistry
    │   ├── memory_tools.py ── recall / remember (Agent 1,3)
    │   ├── file_tools.py ──── read_file（目录列举 + 多文件）
    │   ├── search_tools.py ── glob + grep（白名单限制）
    │   ├── notify_tool.py ─── notify（PowerShell toast）
    │   ├── web_tools.py ───── web_search + web_fetch（AnySearch）
    │   └── music_tool.py ──── music_play（模糊搜索）
    │
    ├── tests/ ───────────────── 单元测试（171 用例）
    │
    ├── storage/
    │   ├── database.py ───── SQLite 连接 + Schema + WAL 模式
    │   └── repository.py ─── 数据访问层（CRUD + 修剪）
    │
    ├── prompts/
    │   ├── system.py ─────── System prompt 动态组装（7 区块）
    │   └── templates.py ──── 抽取/总结/反思 prompt 模板
    │
    ├── models/
    │   ├── personality.py ── EmotionalState + PersonalityConfig
    │   ├── memory.py ─────── UserFact + Experience + Reflection
    │   └── conversation.py ─ Turn + MemoryContext
    │
    ├── ui/
    │   ├── cli.py ────────── 命令行界面 + 非阻塞输入线程
    │   └── display.py ────── 打字机效果 + 彩色输出
    │
    ├── web/
    │   ├── server.py ─────── FastAPI + WebSocket + proactive_loop
    │   ├── session.py ────── SessionManager + WebAgent
    │   └── static/ ───────── HTML/CSS/JS 前端
    │
    └── doc/ ──────────────── 文档目录
```

### 1.2 双端架构

```
CLI 模式： main.py
    ConsoleInterface（非阻塞 stdin）
        → Agent.run()（状态机循环）
            → _on_idle → _on_perceive → _on_think → _on_act → _on_reflect

Web 模式： web_main.py → uvicorn
    FastAPI + WebSocket
        → SessionManager.get_or_create(session_id)
            → WebAgent.process_message() / process_proactive()
                → Agent.process_message() → _react_loop()
```

### 1.3 设计原则

- **三层架构**：Agent 1 InnerDriveAgent（自主推理，记忆检索 + 缺口决策）→ Agent 2 ToolAgent（外部工具执行, temp=0.3，ToolAttemptTracker 重试）→ Agent 3 Roleplay（人格驱动, temp=0.8），从根本上解决模型虚构工具调用问题。闲聊场景优化为单次 LLM 调用
- **单向依赖**：core → memory → storage，core → tools，不存在循环依赖
- **接口隔离**：provider 抽象 LLM 调用，storage 抽象持久化，各层可独立替换
- **双路径**：CLI 用状态机驱动，Web 用事件驱动，共享核心逻辑（_react_loop）

---

## 2. Agent 循环

### 2.1 状态机

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

| 状态 | 职责 | CLI | Web |
|------|------|-----|-----|
| BOOT | 加载人格、初始化、播放欢迎语 | 执行 | 跳过（process_message 直接可用） |
| IDLE | 等待输入 / 主动发起检测 | 守护线程轮询 | WebSocket 协程等待 |
| PERCEIVE | 存储对话、检索记忆 | 完整执行 | 合入 process_message |
| THINK | 组装 prompt、调 LLM、解析 tool_call | _on_think | process_message → _react_loop |
| ACT | 执行工具 / 输出回复 | 状态机处理 | process_message 返回 |
| REFLECT | 情绪更新、记忆合并、保存 | 完整执行 | _react_loop 尾部 |
| SHUTDOWN | 保存状态、关闭连接 | 执行 | 无（session 级别） |

### 2.2 ReAct 循环

每次用户输入可能触发多轮 ReAct 迭代（最多 10 次）：

```
第 1 轮：THINK → LLM 返回 "<tool_call>..."
        ACT → execute_tool_calls() → 结果喂回
第 2 轮：THINK → LLM 基于工具结果继续
        ACT → 无 tool_call → 最终回复 → REFLECT
```

**工具调用解析**：

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "用户喜欢什么"}}
</tool_call>
```

### 2.3 process_message（Web 模式）

```python
def process_message(self, user_input, on_token=None):
    self.short_term.add_turn("user", user_input)
    mem_ctx = self.retriever.retrieve_for_query(user_input)
    sys_prompt = build_system_prompt(...)
    messages = [{"role": "system", "content": sys_prompt}, ...]
    return self._react_loop(messages, on_token)
```

### 2.4 动态 max_tokens

```python
def _max_tokens_for_emotion(self) -> int:
    mapping = {
        "excited": 768, "joyful": 768, "surprised": 700,
        "engaged": 512, "content": 512, "neutral": 512,
        "anxious": 300, "afraid": 300,
        "melancholy": 256, "sad": 256,
        "frustrated": 256, "angry": 256,
    }
    return mapping.get(self.personality.emotion.dominant_emotion, 512)
```

### 2.5 主动发起计算

```python
score = base_idle × 时间调制 + arousal × 情绪调制
      + intimacy × 关系调制 − 告别惩罚 − 短回复惩罚
```

影响因素：空闲时间、时间段（白天更活跃）、情绪状态、关系亲密度、用户最近情感倾向。

---

## 3. 情感系统

### 3.1 情绪维度

采用三维 VAD 模型 + 8 维 Plutchik 基础情绪：

```
     ┌─────────────────────────────────────┐
     │          兴奋 (high arousal)         │
     │    anxious        excited           │
     │      │              │               │
     │  ────┼──── 中性 ────┼────           │
     │      │              │               │
     │ melancholy        content           │
     │          平静 (low arousal)          │
     │   消极             积极              │
     │  (low valence)   (high valence)      │
     └─────────────────────────────────────┘
```

| 维度 | 范围 | 描述 |
|------|------|------|
| valence | -1.0 ~ 1.0 | 积极/消极 |
| arousal | 0.0 ~ 1.0 | 兴奋/平静 |
| mood_valence | -1.0 ~ 1.0 | 背景心境（小时级变化） |
| mood_arousal | 0.0 ~ 1.0 | 背景心境 |
| inertia | 0.0 ~ 1.0 | 情绪惯性（0=秒变，1=不变） |

基础情绪（Plutchik 情绪轮）：

```
joy  trust  fear  surprise
sadness  anticipation  anger  disgust
```

每个维度 0.0~1.0 连续值，独立衰减。

### 3.2 情绪动力学

```
每次交互：
  1. estimate_impact(sentiment, personal_sharing, topic_energy)
     → dv = sentiment × 0.3
     → da = topic_energy × 0.2 - 0.05
     → primary_deltas = {joy: ..., trust: ..., ...}

  2. trait modulation（特质调制）
     empathy > 0.7   → dv ×= 1.5
     playfulness > 0.6 → da ×= 0.7（衰减慢）
     warmth > 0.7    → trust += 0.1

  3. shift(dv, da, primary_deltas)
     → valence += dv × (1 - inertia)
     → arousal += da × (1 - inertia)
     → joy += delta_joy × (1 - inertia)

3.5. cross_modulate()（交叉调制）
     → 情绪维度互相制约，防止矛盾状态：
       anger ×0.6→ joy↓    anger ×0.4→ trust↓
       sadness ×0.5→ joy↓  sadness ×0.4→ anticipation↓
       joy ×0.4→ anger↓    joy ×0.3→ sadness↓
       trust ×0.5→ fear↓   fear ×0.3→ trust↓
       disgust ×0.4→ joy↓  disgust ×0.3→ trust↓

  4. decay()
     → valence → baseline（turn 级快衰减）
     → baseline → mood（小时级慢衰减）
     → 基础情绪 → 中性
```

### 3.3 分速衰减

不同情绪维度使用独立半衰期（单位：对话轮次）：

| 情绪 | 半衰期 | 每 turn 衰减率 |
|------|--------|---------------|
| surprise | 3 | 0.206 |
| fear | 6 | 0.109 |
| anticipation | 8 | 0.083 |
| disgust | 10 | 0.067 |
| joy | 12 | 0.056 |
| anger | 15 | 0.045 |
| sadness | 20 | 0.034 |
| trust | 25 | 0.027 |

### 3.4 怨恨残留

- anger > 0.6 触发累积，3%/turn 衰减
- 增强 anger 对 joy/trust 的压制（cross_modulate）
- joy 上限锁定：`joy_ceiling = 1.0 - resentment * 0.5`
- 减慢 anger/sadness decay

### 3.5 情绪事件记忆

强情绪触发时自动记录（trigger/emotion/intensity），最近 3 条注入 prompt。AI 现在"记得为什么生气"。

### 3.6 情绪标签映射

```
valence/arousal 映射：
  (V > 0.5, A > 0.6)       → excited
  (V > 0.5, A < 0.4)       → content
  (V > 0, 0.4 <= A <= 0.6) → engaged
  (V < 0, A > 0.5)         → anxious
  (V < -0.3, A < 0.4)      → melancholy
  (V < -0.5, A > 0.6)      → frustrated

基础情绪 > 0.7 覆盖上述映射：
  joy > 0.7 → joyful    trust > 0.7 → trusting
  fear > 0.6 → afraid   surprise > 0.7 → surprised
  sadness > 0.6 → sad   anger > 0.6 → angry
```

### 3.4 破防机制

连续负面交互的累积伤害系统。

```
用户输入
    │
    ▼
analyze_sentiment(用户输入)  ← 分析用户情绪，非 AI 回复
    │
    ├── sentiment < -0.5  →  _consecutive_negative += 1
    ├── sentiment > 0.1   →  _consecutive_negative -= 1
    └── 其他              →  保持不变
    │
    ▼
伤害放大：sentiment *= 1.0 + consecutive × 0.4
    │
    ▼
apply_emotional_shift() → 情绪更快速地走向消极
    │
    ▼
prompt 注入：
    ├── 1-2 次  → "被怼了一下" — 轻回怼
    ├── 3-4 次  → "有点受伤"   — 委屈，底气不足
    └── 5+ 次   → "破防了"     — 哭腔、反问、撒娇式回击
```

引用语气的示例内嵌到 system prompt 中引导 LLM 行为。

---

## 4. 记忆系统

### 4.1 架构

```
短期记忆（ConversationBuffer）
    │ deque, maxlen=500, 内存
    │ 每轮对话直接追加
    ▼
长期记忆（SQLite 4 张表）
    ├── user_facts          用户事实（评分 + 置信度 + 重要性）
    ├── experiences         共享体验（情感色调 + 重要性）
    ├── reflections         反思洞察（类型 + 重要性）
    └── conversation_turns  完整对话历史
```

### 4.2 三层检索

```
用户输入
    │
    ├ Layer 1: Hot Memory ──────────────────────────┐
    │  始终注入 prompt：Top 5 facts + 最新 3           │
    │  experiences + 当前关系状态 + 最新 3 reflections  │
    │                                                 │
    ├ Layer 2: Query-Guided ─────────────────────────┤
    │  Step A — 评分过滤（纯 SQL）                     │
    │    score = composite × 0.2 + importance × 0.3   │
    │          + keyword × 0.2 - recall_penalty × 0.02│
    │                                                 │
    │  Step B — LLM 重排序（候选 > 15 条时触发）        │
    │    极小调用（10-20 tokens 输出）→ 选出 3-8 条     │
    │                                                 │
    └ Layer 3: On-Demand ────────────────────────────┘
      LLM 调 <tool_call>{"name": "recall"} 主动回溯
```

### 4.3 记忆合并

触发条件：每 5 轮 / |valence| > 0.7 / pending >= 10 / 空闲 > 120s

```
pending_turns
    │
    ├ Step 1: LLM 抽取 facts
    │   → FACT|category|key|value|confidence|importance
    │   → upsert user_facts（UNIQUE(category, key)）
    │
    ├ Step 2: LLM 总结 experience
    │   → SUMMARY|TONE|SIGNIFICANCE|IMPORTANCE|TAGS
    │   → insert experiences
    │
    ├ Step 3: LLM 生成 reflection
    │   → TYPE|CONTENT|SIGNIFICANCE
    │   → insert reflections
    │
    └ Step 4: 更新 relationship
        → familiarity += 0.02
        → if sentiment > 0.3: trust += sentiment × 0.05
        → if personal_sharing: intimacy += 0.03
```

### 4.4 记忆生命周期

```
创建 → 评分衰减（composite × 0.99/天）
  → score < 0.2 → 归档（is_active = 0）
    → 归档 > 90 天 → 软删除

修剪（每次 consolidation 执行）：
  user_facts     ≤ 200   按 composite_score ASC 归档
  experiences    ≤ 100   按 composite_score ASC 归档
  reflections    ≤ 50    按 significance ASC 删除
```

### 4.5 上下文压缩

```
模型上下文：180,000 tokens（DeepSeek v4）
压缩阈值：80% = 144,000 tokens
触发：每次请求动态计算，超出时自动执行

压缩过程：
  1. 收集所有非 system 消息
  2. LLM 生成对话摘要（100-150 字）
  3. 摘要注入 system prompt
  4. 清空 ConversationBuffer
```

---

## 5. 工具系统

### 5.1 Tool 基类

```python
class Tool:
    def name(self) -> str
    def description(self) -> str
    def parameters_schema(self) -> dict  # JSON Schema
    def execute(self, args: dict) -> ToolResult
```

### 5.2 ToolRegistry

```python
registry = ToolRegistry()
registry.register(MyTool())
registry.format_for_prompt()
# 输出 markdown 格式工具列表供 LLM 参考
```

### 5.3 工具调用协议

LLM 输出格式：

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "..."}}
</tool_call>
```

回退格式：裸 JSON `{"name": "...", "arguments": {...}}`

解析流程：
1. 剥离 `<think>...</think>` 块
2. 正则提取 `<tool_call>...</tool_call>`
3. JSON 解析，参数别名归一化（search → query, text → content）
4. 回退：尝试将整个响应作为 JSON 解析

### 5.4 内置工具（9 个，三层分工）

三层架构从根本上解决模型虚构工具调用内容的问题：
- **Agent 1 (InnerDriveAgent)**：自主推理决策，内部使用 recall/remember。识别知识缺口，输出自然语言工具请求给 Agent 2。
- **Agent 2 (ToolAgent)**：temperature=0.3，独立精简 prompt，纯工具执行。无人格、无情绪、无记忆。7 个外部工具。ToolAttemptTracker：3 retries/round，3 rounds max（9 总尝试）。失败后回报 Agent 1 重新决策。
- **Agent 3 (Roleplay Agent)**：temperature=0.8，完整人格。接收 inner_drive_summary + tool_results。仅 recall/remember 两个内部工具（均为本地 SQLite 操作）。外部工具指令已完全移出 prompt。

| 工具 | 功能 | 参数 | 后端 | Agent |
|------|------|------|------|------|
| web_fetch | 提取网页正文内容（自动去 HTML） | url | AnySearch extract | Agent 2 |
| web_search | 网络搜索，支持中文 + freshness(day/week/month/year) | query, max_results, freshness | AnySearch API (JSON-RPC 2.0) | Agent 2 |
| read_file | 读取本地文件（≤500KB，目录列举，多文件，行号） | path, limit, offset | 本地文件系统 | Agent 2 |
| glob | glob 模式搜索文件（**/*.py 等） | pattern, path | 本地遍历 | Agent 2 |
| grep | 正则搜索文件内容（上下文+过滤） | pattern, path, glob, context | 本地搜索 | Agent 2 |
| music_play | 用默认播放器播放音乐文件（模糊搜索自动匹配） | song | os.startfile | Agent 2 |
| notify | Windows toast 桌面通知（独立线程，不阻塞） | title, message, duration | PowerShell WinRT | Agent 2 |
| recall | 回忆用户信息或共同经历 | query: str | SQLite 三层检索 | Agent 1,3 |
| remember | 记住用户重要信息 | category, key, value, importance | SQLite upsert | Agent 1,3 |

#### 工具别名归一化

`_normalize_args()` 自动处理参数别名:
- `query/search/keyword/question` → `query`
- `text/msg/content` → `content` (message 保留原样，供 notify 使用)
- `person/who/user/target` → `name`

#### 工具调用记录

每次执行后记录到 `_tool_call_history` (最多 20 条)，注入 Agent 3 系统 prompt，AI 可告知用户真实调用记录。

### 5.5 自主行为（作息 + 探索 + 聊天）

所有自主行为由 `web/server.py:_proactive_loop` 后台协程驱动，15 秒轮询一次。

#### 完整决策流程

```
_proactive_loop (15s tick)
    │
    ├──▶ _get_sleep_state()
    │    │ 检查当前时间是否在睡眠/醒来窗口
    │    │
    │    ├── 入睡窗口命中:
    │    │   │ 午睡 12:00-13:00, 夜睡 23:00-01:00
    │    │   │
    │    │   │ sleepiness 计算:
    │    │   │   base = 0.0
    │    │   │   +0.4 if sad/melancholy
    │    │   │   +0.3 if arousal < 0.3
    │    │   │   -0.2 if excited/joyful
    │    │   │   +0.2 × resentment
    │    │   │
    │    │   │ random() < max(threshold, sleepiness) → 入睡
    │    │   │
    │    │   ├── self._sleeping = True
    │    │   ├── 消息: "我去午睡了…[困]" / "夜深了…晚安[月亮]"
    │    │   └── _generate_dream()
    │    │       │ prompt: 事实+经历+情绪 → 碎片化梦境(1-2句)
    │    │       │ 存储: record_emotion_event("梦: {dream}")
    │    │
    │    └── 醒来窗口命中:
    │         │ 午醒 13:10-16:00, 晨醒 7:00-10:00
    │         │
    │         │ wake_chance 计算:
    │         │   base = 0.3 (午醒) / 0.2 (晨醒)
    │         │   + (hour - window_start) / window_width (越晚越高)
    │         │   + (arousal - 0.3) × 0.2 (高 arousal → 醒得早)
    │         │   - resentment × 0.1 (怨恨 → 醒得晚)
    │         │
    │         │ random() < wake_chance → 醒来
    │         │
    │         ├── self._sleeping = False
    │         └── 消息: "睡醒了…做了个梦：{dream}" 或 "没做梦睡得挺香"
    │
    ├── ag._sleeping? → skip + 用户消息 "zzz...💤"
    │
    ├── idle < 30s? → 绝对底线, continue
    │
    ├── idle > 情绪阈值? → _calculate_proactivity(idle)
    │    │
    │    │ 情绪阈值表:
    │    │   excited: 60s    joyful: 90s     engaged: 180s
    │    │   neutral: 360s   sad: 900s        angry: 480s
    │    │   + resentment × 300s (额外惩罚)
    │    │
    │    │ score 计算:
    │    │   base = min(0.3, (idle - threshold) / 900)
    │    │   + time_mod (10-21点 +0.2, 7-22点 +0.1, 深夜 0)
    │    │   + emotion_mod (arousal × 0.2, sad -0.15)
    │    │   + intimacy_mod (intimacy × 0.15 + familiarity × 0.1)
    │    │   + sentiment_mod (positive +0.1, negative -0.3)
    │    │   - goodbye_penalty (晚安/再见 每句 -0.15)
    │    │   - short_penalty (短回复 每句 -0.08)
    │    │   capped at [0, 0.8]
    │    │
    │    └── random() < score? → 触发!
    │         │
    │         ├── 40% → process_explore()
    │         │    │ _check_rate_limit("explore"): 距上次 < 1hr → 拒绝
    │         │    │
    │         │    │ prompt: explore_mode=True
    │         │    │ "你现在闲着，可以做点感兴趣的事"
    │         │    │ "用 web_search 搜好奇的东西"
    │         │    │ "如果发现了特别有意思的想分享，说出来"
    │         │    │ "没什么特别就回复'.'或'没啥'"
    │         │    │
    │         │    │ _react_loop(messages, add_to_history=False)
    │         │    │ AI 可自由调用 web_search/web_fetch/music_list 等
    │         │    │
    │         │    │ 返回值:
    │         │    │   len > 30 且非工具输出 → 视为分享 → 发送消息
    │         │    │   否则 → 返回 None (安静)
    │         │    │
    │         │    └── 发送? → cooldown=12 (3min), reset last_activity_time
    │         │
    │         └── 60% → process_proactive()
    │              │ _check_rate_limit("chat"): 距上次 < 30min → 拒绝
    │              │
    │              │ prompt: is_proactive=True
    │              │ "用户有一会儿没说话了。嘴贱一下开启话题"
    │              │ "调侃一句/分享一下你在想啥/说好无聊"
    │              │
    │              │ topic: _pick_proactive_topic()
    │              │   最近体验/用户事实/通用话题 随机选一
    │              │
    │              │ _react_loop(messages, add_to_history=False)
    │              │ (主动回复不进入短期记忆)
    │              │
    │              └── 发送 → cooldown=12, reset last_activity_time
    │
    └── 未触发 → await sleep(15), continue
```

#### 关键实现方法

| 方法 | 位置 | 说明 |
|------|------|------|
| `InnerDriveAgent.perceive_and_decide()` | core/inner_drive.py | Agent 1 自主推理：检索记忆 → 识别缺口 → 决策 → 输出自然语言请求或跳过 |
| `build_inner_drive_prompt()` | prompts/system.py | Agent 1 system prompt：当前时间 + 身份 + 记忆 + 工具列表 |
| `ToolAgent.run_with_request()` | core/tool_agent.py | Agent 2 接收自然语言请求，执行外部工具，ToolAttemptTracker 重试 |
| `ToolAgent._build_prompt()` | core/tool_agent.py | Agent 2 精简 prompt（无情绪/记忆/工具记录） |
| `ToolAttemptTracker` | core/tool_agent.py | 3 retries/round × 3 rounds max = 9 总尝试，失败回报 Agent 1 |
| `_get_sleep_state()` | core/agent.py | 返回 (should_sleep, message_or_None) |
| `_generate_dream()` | core/agent.py | LLM 生成 1-2 句碎片化梦境 |
| `_check_rate_limit(action)` | core/agent.py | explore: 3600s 间隔, chat: 1800s 间隔 |
| `_calculate_proactivity(idle)` | core/agent.py | 返回 0.0~0.8 的触发概率 |
| `_pick_proactive_topic()` | core/agent.py | 从经历/事实/通用中随机选话题 |
| `process_explore()` | core/agent.py | 探索模式: 自由工具调用, 有趣才分享 |
| `process_proactive()` | core/agent.py | 主动搭话: 调侃/分享/找话题 |
| `process_dream()` | core/agent.py | 旧版梦境生成 (已被 _generate_dream 替代) |

#### 状态追踪

```python
self._sleep.is_sleeping: bool       # 当前是否在睡眠 (SleepManager)
self._proactive._last_explore_time: float  # 上次探索时间戳 (ProactivityManager)
self._proactive._last_chat_time: float     # 上次聊天时间戳 (ProactivityManager)
```

### 5.6 虚假操作检测（已由三层架构根治）

三层架构从根本上解决了模型虚构工具调用的问题：
- Agent 2 ToolAgent 仅负责工具执行，不在 prompt 中包含 personality 或对话历史，temperature=0.3 确保结果稳定
- Agent 3 Roleplay Agent 的 prompt 中已完全移除外部工具指令（仅保留 recall/remember 两个内部工具）
- 模型不再有虚构工具行为的动机和空间

```python
def contains_fake_action(text):
    # 旧版检测（三层架构下此问题已根本解决）
    # 检测 LLM 声称执行了操作但未调工具
    keywords = ["已发送", "已通知", "已记住", ...]
```

---

## 6. 提示词工程

### 6.1 System Prompt 组装

7 个区块动态拼接：

```
=== Block 1: 当前时间 ===
当前时间：2026-05-28 12:00 Thursday

=== Block 2: 身份核心 ===
你是{name}，一个有情感、有记忆的 AI 朋友。
你的核心特质：{traits}
你的说话风格：{speaking_style}
你的背景：{backstory}

=== Block 3: 情绪状态 ===
你感到 {mood}，心底有一丝{primary_emotion}。
情绪{valence_desc}，{arousal_desc}。说话按这个感觉来。

=== Block 4: 关系指标 ===
信任: 0.3  熟悉度: 0.3  亲密: 0.3  趣味: 0.3

=== Block 5: 长期记忆 ===
你知道的关于用户的事情：
- 名字: 小陈
- 摄影喜好: 城市风景和街拍

=== Block 6: 工具列表 ===
可用工具：recall / remember / read_file / notify
<tool_call>{"name": "...", "arguments": {...}}</tool_call>

=== Block 7: 对话示例 + 指令 ===
用户：今天去外滩拍照了
你：蛙趣！那肯定好看！发出来看看[旺柴]

像朋友一样回她。嘴可以贱，但心要暖。
```

### 6.2 Prompt 模板

| 模板 | 用途 | 关键参数 |
|------|------|----------|
| FACT_EXTRACTION | 从对话抽取用户事实 | text |
| EXPERIENCE_SUMMARIZATION | 总结共享体验 | text |
| REFLECTION | 生成反思洞察 | experiences, reflections, facts, relationship |
| EMOTION_ANALYSIS | 分析用户消息情感 | text |
| MEMORY_RERANK | 记忆候选重排序 | query, candidates |
| CONTEXT_COMPRESS | 对话摘要生成 | conversation |

---

## 7. Web 界面

### 7.1 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | FastAPI (ASGI) |
| 通信 | WebSocket |
| 前端 | 纯 HTML + CSS + JS |
| 运行 | Uvicorn（开发）/ 多 worker（生产） |

### 7.2 WebSocket 协议

```
客户端 → 服务端:
  {"type": "init", "session_id": "xxx"}        # 初始化会话
  {"type": "message", "content": "你好"}       # 发送消息
  {"type": "ping"}                              # 心跳（30s 间隔）

服务端 → 客户端:
  {"type": "init_ok", "session_id": "xxx", "emotion": "engaged"}
  {"type": "segment", "content": "你好呀！"}    # 创建独立气泡
  {"type": "done", "content": "...", "emotion": "engaged", "turn": 5}
  {"type": "error", "content": "..."}
  {"type": "pong"}
```

### 7.3 分段推送

```
response = agent.process_message(content)
    │
    ▼
_split_segments()
    │  6 级 fallback：
    │    ① 标点分割（。！？.!?\n，含引号括号尾随）
    │    ② 逗号拆分（，,；;，40 字以上长段）
    │    ③ 空格分割
    │    ④ 语气词分割（啊吗呢了吧么呀哦嘛哇）
    │    ⑤ 自然停顿（然后/但是/所以… + 了/过/到）
    │    ⑥ 18 字符硬切（兜底）
    │  合并 <4 字符的碎片
    ▼
["你好呀！", "今天怎么样？", "我这边天气不错。"]
    │
    ▼
for i, seg in enumerate(segments):
    if i > 0:
        await asyncio.sleep(_calc_delay(emotion, len(seg)))
    await ws.send({"type": "segment", "content": seg})
    │  前端每个 segment 创建独立气泡
    ▼
await ws.send({"type": "done", ...})
```

延迟计算：

```
delay = base[emotion] × (1 + seg_len/80) × random(0.8, 1.3)
```

| 情绪 | 基础延时 | 典型 20 字段约 |
|------|----------|---------------|
| excited / surprised | 0.7~0.8s | ~1.0~1.3s |
| joyful / anticipating | 0.9s | ~1.2~1.6s |
| engaged | 1.3s | ~1.6~2.3s |
| content | 1.5s | ~1.9~2.6s |
| neutral | 1.7s | ~2.1~3.0s |
| melancholy | 2.2s | ~2.7~3.9s |
| sad | 2.5s | ~3.1~4.4s |

### 7.4 自主行为循环

```
_proactive_loop (15s tick)
    │
    ├─ 入睡? → 发睡前消息 → 生成梦境
    ├─ 醒来? → 发梦境分享
    ├─ 睡着? → skip (30s后重试)
    ├─ 空闲 < 30s? → skip
    │
    ├─ 空闲 > 情绪阈值?
    │   └─ 随机命中?
    │       ├─ 40% 探索 (1/hr limit) → 自由工具 → 有趣才分享
    │       └─ 60% 聊天 (2/hr limit) → 主动搭话
    └─ 未命中 → 等15s
```

空闲阈值与情绪挂钩：excited 60s, sad 900s, neutral 360s，resentment 额外+300s。

### 7.5 主动对话后台（旧）
        if idle > config.proactive_min_idle:
            score = agent.agent._calculate_proactivity(idle)
            if random.random() < score:
                response = agent.process_proactive()
                await _send_segments(ws, response)
        await asyncio.sleep(15)
```

- 用户发消息时重置 `last_activity_time`
- WebSocket 断开时自动 cancel
- 多标签页共享 agent 实例（待修复竞争条件）

### 7.5 会话管理

```python
class SessionManager:
    _sessions: dict[session_id → WebAgent]
    _lock: Lock

    def get_or_create(session_id) -> WebAgent
    def remove(session_id)
```

- 每个浏览器标签页独立 Agent 实例
- 独立 Personality + ConversationBuffer
- 共享 SQLite（无 session_id 隔离，待修复）

---

## 8. 数据模型

### 8.1 EmotionalState

```python
valence: float          # -1~1
arousal: float          # 0~1
baseline_valence: float
baseline_arousal: float
decay_rate: float
mood_valence: float     # 背景心境
mood_arousal: float
mood_decay_rate: float
inertia: float          # 0~1 情绪惯性
joy/trust/fear/...      # 8 维 Plutchik 0~1
history: list[str]      # 最近 10 轮情绪标签
```

### 8.2 UserFact

```python
category: str           # preference/identity/event/relationship/routine
fact_key: str
fact_value: str
confidence: float       # 0~1
importance: float       # 0~1（0.3 临时, 0.6 长期, 1.0 永久）
composite_score: float  # 综合评分用于检索排序
```

### 8.3 Experience

```python
summary: str
emotional_tone: str
significance: float     # 0~1
importance: float       # 0~1
tags: list[str]
```

### 8.4 Reflection

```python
content: str
insight_type: str       # self_discovery/user_discovery/relationship_insight/pattern/prediction
significance: float     # 0~1
```

---

## 9. 存储层

### 9.1 SQLite Schema

```sql
-- 5 张核心表
user_facts          用户事实（UNIQUE category+fact_key）
experiences         共享体验（tags 存 JSON）
reflections         反思洞察（related_experience_ids 存 JSON）
relationship_metrics 关系指标（key-value）
conversation_turns  完整对话历史
```

### 9.2 WAL 模式

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

### 9.3 连接管理

```python
class Database:
    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()

    @contextmanager
    def cursor(self):
        with self._lock:
            yield c
            self.conn.commit()
```

---

## 10. 配置系统

优先级：环境变量（计划中） > config.json > Config dataclass

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "max_tokens": 512,
  "temperature": 0.8,
  "short_term_capacity": 500,
  "consolidation_interval": 5,
  "proactive_min_idle": 180.0,
  "proactive_max_interval": 600.0,
  "typing_speed": 0.005,
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

### 环境

```bash
pip install requests tiktoken plyer fastapi uvicorn
```

### 启动

```bash
# CLI 模式
python main.py

# Web 模式（开发）
python web_main.py

# Web 模式（生产）
uvicorn web.server:app --host 0.0.0.0 --port 8000 --workers 4
```

### 数据文件

| 文件 | 说明 | gitignore |
|------|------|-----------|
| `personality.json` | 人格定义 + 情绪状态持久化 | 否 |
| `data/ai_friend.db` | SQLite 数据库 | 是 |
| `config.json` | 用户配置 | 是 |

### Token 估算

使用 `tiktoken` 的 `cl100k_base` 编码（待替换为 DeepSeek 专用 tokenizer）。不可用时回退启发式：

```
CJK 字符: ÷ 1.5
ASCII 字母: ÷ 4
数字: ÷ 3
其他: ÷ 8
```
