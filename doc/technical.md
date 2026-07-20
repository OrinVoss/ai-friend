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
    ├── core/（19 模块）
    │   ├── inner_drive.py ────── Agent 1 InnerDriveAgent：自主推理 + 记忆检索 + 缺口决策
    │   ├── tool_agent.py ─────── Agent 2 ToolAgent：外部工具执行 + ToolAttemptTracker + response_format JSON mode
    │   ├── agent.py ──────────── Agent 3 Roleplay：人格驱动 + ReAct 循环, temp=0.8
    │   ├── message_handler.py ── 消息入口（handle_message / proactive / explore 三层编排）
    │   ├── conversation_engine.py ── 统一对话引擎 + Frontend 事件接口（unified-pipeline P1）
    │   ├── runtime_driver.py ─── 共享时间驱动：睡眠/唤醒/主动搭话/探索（unified-pipeline P2）
    │   ├── session_factory.py ── CLI/Web 共享会话装配（统一管线 P0）
    │   ├── context_manager.py ── 上下文窗口管理（token估算+压缩）
    │   ├── prompt_cache.py ───── Prompt 分层缓存（静态/慢变/动态块复用）(#160)
    │   ├── sleep_manager.py ──── 睡眠/唤醒系统（窗口判断+梦境）
    │   ├── proactivity.py ────── 主动行为引擎（评分+话题+限速）
    │   ├── cli_controller.py ─── CLI 输入循环 + 命令层（ConversationEngine 前端）
    │   ├── personality.py ────── 情绪引擎（四层：输入→调制→怨恨→记忆）
    │   ├── provider.py ───────── LLMProvider 抽象基类 + DeepSeekProvider 实现（OpenAI 兼容，流式，response_format JSON mode）(#23)
    │   ├── monitor.py ────────── LLM API 调用监控（环形缓冲 200 条，开发调试用）
    │   ├── embedding_server.py ─ 本地嵌入服务器自动启动（CLI/Web 共享）(#58)
    │   ├── logging_setup.py ──── 日志配置（CLI/Web 共享）(#58)
    │   ├── async_utils.py ─────── 异步→同步统一桥接 run_async()（#134）
    │   ├── dispatcher.py ─────── tool_call 三层解析（JSON calls 数组 / XML / 裸 JSON）+ 工具调度
    │   └── inner_drive_state.py ─ 内驱状态池（二期：关注列表 / 沉思循环 / 响应线索）
    │
    ├── memory/（7 模块）
    │   ├── short_term.py ───── ConversationBuffer（内存 deque）
    │   ├── long_term.py ────── LongTermMemory（aiosqlite 异步 CRUD + 同步兼容包装）
    │   ├── embeddings.py ───── EmbeddingEngine（llama-server API, 1024 维）+ EmbeddingCache（LRU）
    │   ├── lifecycle.py ────── MemoryLifecycleManager：Observation→Fact 生命周期（observe/promote/verify/contradict/decay/gc）(ML-001)
    │   ├── fact_checker.py ──── FactChecker：矛盾检测 + 置信度衰减 + 用户纠正 (#6)
    │   ├── retrieval.py ────── 三层检索 + 混合评分（语义 0.6 + 关键词 0.4）+ LLM 重排序
    │   └── consolidation.py ── 记忆合并（短→长转移 + 修剪 + FactChecker 集成 + 自动嵌入编码 + 双写 Observation/FactV2）
    │
    ├── tools/
    │   ├── traits.py ──────── Tool 基类（含 to_json_schema()）+ ToolRegistry
    │   ├── memory_tools.py ── recall / remember (Agent 1,3)
    │   ├── file_tools.py ──── read_file（目录列举 + 多文件）+ file_tree（目录树）
    │   ├── search_tools.py ── glob + grep（白名单限制）
    │   ├── notify_tool.py ─── notify（PowerShell toast）
    │   ├── web_tools.py ───── web_search + web_fetch（AnySearch）
    │   └── music_tool.py ──── music_play（模糊搜索）
    │
    ├── tests/ ───────────────── 单元测试（410 用例，30 个测试文件）
    │
    ├── storage/
    │   ├── database.py ───── SQLite 异步连接（aiosqlite + asyncio.Lock）+ 9 表 Schema + WAL 模式
    │   └── repository.py ─── 异步数据访问层（CRUD + 修剪 + session 隔离）
    │
    ├── prompts/
    │   ├── system.py ─────── System prompt 分层组装（静态/慢变/动态块 + PromptCache）(#160)
    │   ├── instructions.py ── Agent 1/2/3 指令文案集中管理（#294）
    │   ├── tools_description.py ─ 工具触发规则/意图选项（由 ToolRegistry 动态生成）
    │   └── templates.py ──── 抽取/总结/反思 prompt 模板
    │
    ├── models/
    │   ├── personality.py ── EmotionalState + PersonalityConfig
    │   ├── memory.py ─────── UserFact + Experience + Reflection + Observation + FactV2 + InsightV2
    │   └── conversation.py ─ Turn + MemoryContext
    │
    ├── ui/
    │   ├── cli.py ────────── 命令行界面 + 非阻塞输入线程
    │   └── display.py ────── 打字机效果 + 彩色输出
    │
    ├── web/
    │   ├── server.py ─────── FastAPI + WebSocket + RuntimeDriver 启动/生命周期
    │   ├── session.py ────── SessionManager + WebAgent
    │   ├── schemas.py ────── Pydantic 请求/响应模型
    │   ├── rate_limit.py ─── 内存滑动窗口限流中间件
    │   └── static/ ───────── HTML/CSS/JS 前端
    │
    └── doc/ ──────────────── 文档目录
```

### 1.2 双端架构

统一管线（unified-pipeline P0-P3）已覆盖 CLI 与 Web，两端共享同一 `ConversationEngine` + `RuntimeDriver`，只有前端渲染不同。

```
CLI 模式： main.py
    load_config() + setup_logging() + auto_start_embedding()  (#58 共享启动)
    assemble_session() ── 统一装配（per-session Repository）
    Agent.run()
        → CliController.run()
            ├── ConversationEngine(a)   # 统一对话引擎
            ├── _CliFrontend(a.ui)      # 终端打字机渲染
            └── RuntimeDriver(engine, frontend).start_in_thread()
                └── 睡眠/唤醒/做梦/主动搭话/自由探索

Web 模式： web_main.py → uvicorn
    load_config() + setup_logging() + auto_start_embedding()  (#58 共享启动)
    FastAPI + WebSocket
        → SessionManager.get_or_create(session_id)
            → WebAgent
                ├── assemble_session() ── 统一装配
                ├── ConversationEngine(a)
                ├── _WsProactiveFrontend(ws)  # WebSocket 分段气泡
                └── RuntimeDriver(engine, frontend) as asyncio task
                    └── 与 CLI 同一时间节奏
```

### 1.3 设计原则

- **三层架构**：Agent 1 InnerDriveAgent（自主推理，记忆检索 + 缺口决策）→ Agent 2 ToolAgent（外部工具执行, temp=0.3，ToolAttemptTracker 重试）→ Agent 3 Roleplay（人格驱动, temp=0.8），从根本上解决模型虚构工具调用问题。闲聊场景优化为单次 LLM 调用
- **单向依赖**：core → memory → storage，core → tools，层间无循环依赖（个别内部环靠 lazy import 维持）
- **统一装配**：`core/session_factory.py` 是 CLI/Web 唯一装配点，provider 与 embed engine 进程共享，Repository 按 session 隔离（P0）
- **接口隔离**：provider 抽象 LLM 调用，storage 抽象持久化，各层可独立替换
- **统一管线 + 双前端**：CLI 与 Web 共享 `ConversationEngine` + `RuntimeDriver`，只有 Frontend 渲染不同

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

| 状态 | 职责 | 当前实现 |
|------|------|----------|
| BOOT | 加载人格、初始化、播放欢迎语 | CLI 启动时由 `CliController._on_boot()` 播放欢迎语；Web 端会话创建即就绪，不单独经历 BOOT |
| IDLE | 等待输入 / 主动发起检测 | CLI 在 `CliController.run()` 中阻塞读 stdin；主动行为由 `RuntimeDriver` 在后台 tick |
| PERCEIVE | 存储对话、检索记忆 | `MessageHandler.handle_message()` 内部执行 |
| THINK | 组装 prompt、调 LLM、解析 tool_call | `Agent._react_loop()` / `MessageHandler` 处理 |
| ACT | 执行工具 / 输出回复 | `dispatcher.execute_tool_calls()` 执行，结果回灌 `_react_loop()` |
| REFLECT | 情绪更新、记忆合并、保存 | 每次回复后由 `MessageHandler` 触发；CLI 退出时额外执行一次 |
| SHUTDOWN | 保存状态、关闭连接 | CLI 退出时保存；Web 端按 session 生命周期保存 |

### 2.2 ReAct 循环

每次用户输入可能触发多轮 ReAct 迭代（最多 `config.max_tool_iterations` 次，默认 5）：

```
第 1 轮：THINK → LLM 返回 JSON 工具调用（或 XML 回退）
        ACT → execute_tool_calls() → 结果喂回
第 2 轮：THINK → LLM 基于工具结果继续
        ACT → 无 tool_call → 最终回复 → REFLECT
```

**工具调用解析（三层）**：

Tier 1 — JSON mode 结构化输出：
```json
{"calls": [{"name": "recall", "arguments": {"query": "用户喜欢什么"}}]}
```

Tier 2 — XML 标签兼容回退：
```xml
<tool_call>
{"name": "recall", "arguments": {"query": "用户喜欢什么"}}
</tool_call>
```

### 2.3 process_message（Web 模式）

```python
def process_message(self, user_input, on_token=None):  # → MessageHandler.handle_message
    self.short_term.add_turn("user", user_input)
    drive_result = self._inner_drive.assess(user_input)  # Agent 1：检索记忆 + 决策
    if not drive_result.needs_external_tools:
        # drive_result.context_summary（记忆/关系摘要）直接传给 Agent 3，不再重复检索
        return self._run_agent3(user_input, drive_result, on_token=on_token)
    exec_result = self._run_agent2(user_input, drive_result)   # Agent 2 多轮工具执行
    return self._run_agent3(user_input, drive_result,
                            tool_records=exec_result.records_text, final_response=True)
```

### 2.4 动态 max_tokens

```python
def _max_tokens_for_emotion(self) -> int:
    base = self.config.max_tokens  # 默认 512
    mapping = {
        "excited": 512, "joyful": 512, "surprised": 448,
        "engaged": base, "content": base, "trusting": base,
        "anticipating": base, "neutral": base,
        "anxious": 128, "afraid": 128,
        "melancholy": 128, "sad": 128,
        "frustrated": 128, "angry": 128, "disgusted": 128,
    }
    return mapping.get(self.personality.emotion.dominant_emotion, base)
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
长期记忆（SQLite 9 张表）
    ├── facts_v2            经验证的事实（confidence/stability/freshness/importance）
    ├── experiences         共享体验（情感色调 + 重要性）
    ├── insights_v2         假设性洞察（hypothesis + evidence + confidence，二期替换 reflections）
    ├── conversation_turns  完整对话历史
    ├── relationship_metrics 关系指标（按 session 隔离）
    ├── relationship_snapshots 关系指标历史快照
    ├── session_roles       session_id → role_id 映射
    ├── observations        原始观察（记忆生命周期 Layer 1）
    └── user_facts_archive  旧 user_facts 归档（schema v4 后代码不再读写）
```

### 4.2 三层检索

```
用户输入
    │
    ├ Layer 1: Hot Memory ──────────────────────────┐
    │  每轮必取：活跃 facts 候选（≤50 条）+ 最新 5       │
    │  experiences + 当前关系状态 + 最新 3 insights      │
    │  （insights_v2，经适配器返回 Reflection 形状）      │
    │                                                 │
    ├ Layer 2: Query-Guided ─────────────────────────┤
    │  Step A — 混合评分                               │
    │    语义 cosine × 0.6 + 关键词评分 × 0.4           │
    │    关键词分 = composite × 0.2 + importance × 0.3  │
    │      + confidence × 0.15 + keyword × 0.2        │
    │      − min(recall × 0.02, 0.3)                  │
    │    嵌入不可用 → 纯关键词评分（降级）                │
    │                                                 │
    │  Step B — LLM 重排序（候选 > 15 条时触发）         │
    │    极小调用（10-20 tokens 输出）→ 重排后截断至 15 条 │
    │    最终注入前 10 条 facts                         │
    │                                                 │
    └ Layer 3: On-Demand ────────────────────────────┘
      LLM 调 <tool_call>{"name": "recall"} 主动回溯
```

### 4.3 记忆合并

触发条件：每 5 轮 / |valence| > 0.7 / pending >= 10 / 空闲 > 120s

```
pending_turns
    │
    ├ Step 0: 写入 Observation（ML-001，已正式上线 2026-07-18）
    │   → 整批对话文本直接存一条 Observation（无新增 LLM 调用）
    │   → 本批提取的 fact 以其为来源 promote 为 FactV2
    │
    ├ Step 1: LLM 抽取 facts（#127 只提取 user_fact）
    │   → FACT|category|key|value|confidence|importance|fact_type
    │   → 跳过 agent_fact / system_fact（AI 行为/系统属性不入库）
    │   → 单写 facts_v2（UNIQUE(session_id, category, key)，逐条 promote）
    │   → FactChecker 矛盾检测 (#6)：
    │       同 (category, key) 不同 value → 直接矛盾
    │       嵌入相似度 > 0.65 且 value 不同 → 语义矛盾
    │       矛盾事实: confidence × 0.4
    │       衰减后 < 0.2 → 软删除 (is_active=0)
    │
    ├ Step 2: LLM 总结 experience
    │   → SUMMARY|TONE|SIGNIFICANCE|IMPORTANCE|TAGS
    │   → insert experiences
    │
    ├ Step 3: 分层洞察（#5，二期 2026-07-20 替代反思）
    │   → L1 基础洞察（每次）/ L2 行为模式（每 3 次）/ L3 深度洞察（每 10 次）
    │   → LLM 输出 JSON（hypothesis/evidence/confidence）→ insert insights_v2
    │
    ├ Step 4: 更新 relationship
    │   → familiarity += 0.02
    │   → trust: trusting 情绪 +0.05 / sentiment > 0.3 → +sentiment × 0.05 / 负面情绪 −0.02
    │   → intimacy: personal_sharing +0.03 / content·engaged·trusting +0.02
    │   → playfulness: 积极情绪 +0.02 / 负面情绪 −0.02
    │
    ├ Step 5: 修剪（见 4.4）+ 每 5 次执行一次 lifecycle GC
    │
    └ Step 6: _embed_new_items() 自动嵌入编码（见 4.6）
```

### 4.4 记忆生命周期

**事实与旧三表（facts_v2 / experiences / insights_v2）**：

```
修剪（每次 consolidation 执行，按 session 隔离）：
  facts_v2       ≤ 200   超出部分 freshness/confidence × 0.1 降级（最低 composite 优先）
  experiences    ≤ 100   按 composite_score ASC 归档（is_archived=1）
  insights_v2    ≤ 50    按 confidence ASC 过期（status='expired'，二期替代旧 reflections 软删除）

矛盾衰减（FactChecker，见 4.7）：
  confidence × 0.4 → 衰减后 < 0.2 → 软删除（facts_v2 status='contradicted'）
```

**Layer 1 新生命周期（ML-001，已正式上线 2026-07-18：单写 facts_v2，读走 facts_v2，user_facts 归档为 user_facts_archive）**：

```
Observation（原始观察，整批对话文本，低置信）
    │ 重复证据 / 明确确认
    ▼ promote
FactV2（四维评分：confidence / stability / freshness / importance）
    │
    ├ verify     → verification_count += 1，刷新 last_verified_at
    ├ contradict → status = "contradicted"
    └ decay（GC 时）→ freshness/confidence × 0.99^天数
         → freshness < 0.2 → status = "decayed"

GC（每 5 次 consolidation 执行一次）：
  decay + merge_duplicates（占位）+ 归档 > 30 天的 observations
```

由 `MemoryLifecycleManager`（memory/lifecycle.py）提供 observe / promote / verify / contradict / decay / gc；对应模型 Observation / FactV2（models/memory.py），测试 tests/test_memory_lifecycle.py（7 用例）。

### 4.5 上下文压缩

```
模型上下文：1,000,000 tokens（deepseek-v4-flash）
压缩阈值：80% = 800,000 tokens
触发：每次请求动态计算，超出时自动执行

压缩过程：
  1. 收集所有非 system 消息（每条截断 500 字，整体保留最后 8000 字）
  2. LLM 生成对话摘要（2000-2500 字，第三人称）
  3. 摘要注入 system prompt（compressed_summary 区块）
  4. 清空 ConversationBuffer
```

### 4.6 语义嵌入

本地嵌入引擎 `memory/embeddings.py` 提供两类组件：

**EmbeddingEngine** — llama.cpp server 客户端：
- 模型：Qwen3.5-0.8B-Q6_K.gguf（~640MB, GPU CUDA 加速）
- 端点：`http://localhost:8080/v1/embeddings`（OpenAI 兼容 API）
- 维度：1024（`config.embedding_dim`，L2 归一化后存为 SQLite BLOB）
- 启动方式：`start_embedding_server.bat`（启动 llama-server）

**EmbeddingCache** — LRU 缓存：
- 按 SHA-256 文本哈希去重，避免重复编码
- 默认容量 1000 条，达到上限淘汰最旧条目
- 每个条目存储 `np.ndarray` 副本，线程安全

**混合检索流程**：

```
用户查询
    │
    ├── health_check() → 嵌入服务可用?
    │   ├── 是 → encode_single(query) → cosine 相似度 × 0.6
    │   │         + keyword_score × 0.4 → 综合排序
    │   └── 否 → 纯关键词评分（降级）
    │
    └── 候选结果 → LLM 重排（>15 条时）→ 注入 prompt
```

**嵌入存储**：

每次 consolidation 完成后，`_embed_new_items()` 扫描 `facts_v2`、`observations`、`experiences`、`insights_v2` 四张可嵌入表中 `embedding IS NULL` 或版本过期的行，批量编码后写入 `embedding` BLOB 列（`float32 × dim` 原始字节）。（2026-07-18：user_facts 归档后移出清单；2026-07-20：reflections 归档，换 insights_v2）

**维度校验**（2026-07-16 修复）：

`bytes_to_vec` 默认按 BLOB 长度推断维度（`dim=None`）；检索的两个调用点显式传 `dim=len(query_vec)` 校验，维度不匹配的旧向量记 warning、该条仅按关键词评分，不再静默置 0。

**优雅降级**：
- 嵌入服务不可用时（health_check 失败/网络错误），自动回退到纯关键词评分
- 不影响记忆合并和基本检索功能
- 启动期间无需等待嵌入服务

### 4.7 虚假记忆修正 (#6)

**FactChecker** (`memory/fact_checker.py`) 在 consolidation 时自动运行：

**矛盾检测**：
1. 同 (category, fact_key) 不同 fact_value → 直接矛盾
2. 嵌入余弦相似度 > 0.65 且 value 不同 → 语义矛盾
3. 嵌入引擎不可用时回退关键词重叠（Jaccard ≥ 0.5）检测（FC-005）

**置信度衰减**：
- 被矛盾的事实：confidence × 0.4（新事实置信度明显更低时 ×0.7 轻度衰减，FC-003）
- 衰减后 < 0.2 → 软删除（is_active=0, composite_score=0）

**检索过滤**：
- `search_facts` / `get_active_facts` 自动过滤 `confidence < 0.2` 的事实
- `_keyword_score_single` 评分中加入 confidence × 0.15 权重

**用户纠正**：
- `RememberTool` 设置 `correct=true` → 旧事实软删除，新事实 confidence=1.0, importance=0.9
- confidence=1.0 确保纠正不会被后续 upsert 覆盖

---

## 5. 工具系统

> 工具开发指南见 [工具开发文档](tool-development.md)。

### 5.1 Tool 基类

```python
class Tool:
    def name(self) -> str
    def description(self) -> str
    def parameters_schema(self) -> dict  # JSON Schema
    def to_json_schema(self) -> dict     # OpenAI function-calling JSON Schema
    def execute(self, args: dict) -> ToolResult
```

`to_json_schema()` 生成 OpenAI 兼容的 function-calling JSON Schema，供 provider 的 `response_format` 参数使用，实现结构化 JSON 工具调用。

### 5.2 ToolRegistry

```python
registry = ToolRegistry()
registry.register(MyTool())
registry.format_for_prompt()
# 输出 markdown 格式工具列表供 LLM 参考
```

### 5.3 工具调用协议

LLM 输出格式（三层解析，优先级从高到低）：

**Tier 1 — JSON calls 数组（结构化输出 / JSON mode）**：

```json
{"calls": [{"name": "recall", "arguments": {"query": "..."}}]}
```

Provider 传入 `response_format={"type": "json_object"}` 启用 JSON mode，LLM 返回含 `calls` 数组的结构化 JSON 对象。

**Tier 2 — XML 标签（兼容回退）**：

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "..."}}
</tool_call>
```

**Tier 3 — 裸 JSON（最终回退）**：

```json
{"name": "recall", "arguments": {"query": "..."}}
```

解析流程：
1. 剥离 `<think>...</think>` 块
2. 尝试解析为含 `calls` 数组的 JSON 对象（JSON mode 输出）
3. 正则提取 `<tool_call>...</tool_call>`
4. JSON 解析，参数别名归一化（search → query, text → content）
5. 回退：尝试将整个响应作为单个 JSON 对象解析

### 5.4 内置工具（CLI 10 个 / Web 9 个，三层分工）

三层架构从根本上解决模型虚构工具调用内容的问题：
- **Agent 1 (InnerDriveAgent)**：自主推理决策，内部使用 recall/remember。识别知识缺口，输出自然语言工具请求给 Agent 2。
- **Agent 2 (ToolAgent)**：temperature=0.3，独立精简 prompt，纯工具执行。无人格、无情绪、无记忆。共定义 8 个外部工具，其中 `file_tree` 仅在 CLI 注册（`session_factory.py` 的 `include_file_tree=True`），Web 端注册 7 个外部工具。ToolAttemptTracker：3 retries/round，3 rounds max（9 总尝试）。失败后回报 Agent 1 重新决策。
- **Agent 3 (Roleplay Agent)**：temperature=0.8，完整人格。接收 inner_drive_summary + tool_results。仅 recall/remember 两个内部工具（均为本地 SQLite 操作）。外部工具指令已完全移出 prompt。

> 注册数量：`session_factory.py` 中 CLI 注册 10 个工具（8 外部 + 2 内部），Web 注册 9 个工具（7 外部 + 2 内部，无 `file_tree`）。

| 工具 | 功能 | 参数 | 后端 | Agent |
|------|------|------|------|------|
| web_fetch | 提取网页正文内容（自动去 HTML） | url | AnySearch extract | Agent 2 |
| web_search | 网络搜索，支持中文 + freshness(day/week/month/year) | query, max_results, freshness | AnySearch API (JSON-RPC 2.0) | Agent 2 |
| read_file | 读取本地文件（≤500KB，目录列举，多文件，行号） | path, limit, offset | 本地文件系统 | Agent 2 |
| file_tree | 列出目录结构树（跳过 .git/__pycache__ 等，深度 ≤4） | path, depth | 本地遍历 | Agent 2 |
| glob | glob 模式搜索文件（**/*.py 等） | pattern, path | 本地遍历 | Agent 2 |
| grep | 正则搜索文件内容（上下文+过滤） | pattern, path, glob, context | 本地搜索 | Agent 2 |
| music_play | 用默认播放器播放音乐文件（模糊搜索自动匹配） | song | os.startfile | Agent 2 |
| notify | Windows toast 桌面通知（独立线程，不阻塞） | title, message, duration | PowerShell WinRT | Agent 2 |
| recall | 回忆用户信息或共同经历 | query: str | SQLite 三层检索 + confidence>=0.2 过滤 | Agent 1,3 |
| remember | 记住用户重要信息（支持 correct=true 纠正旧事实） | category, key, value, importance, correct | SQLite upsert (correct 走 correct_fact) | Agent 1,3 |

#### 工具别名归一化

`_normalize_args()` 自动处理参数别名:
- `query/search/keyword/question` → `query`
- `text/msg/content` → `content` (message 保留原样，供 notify 使用)
- `person/who/user/target` → `name`

#### 工具调用记录

每次执行后记录到 `_tool_call_history` (最多 20 条)，注入 Agent 3 系统 prompt，AI 可告知用户真实调用记录。

### 5.5 自主行为（作息 + 探索 + 聊天）

所有自主行为由 `core/runtime_driver.py` 的 `RuntimeDriver` 驱动，15 秒一次 tick，CLI 与 Web 共用同一节奏：
- **CLI**：`driver.start_in_thread()` 在守护线程中运行事件循环。
- **Web**：`asyncio.create_task(driver.run())` 在服务端事件循环中运行。

> 注：`_get_sleep_state()` 与 `_generate_dream()` 均为 `async`，RuntimeDriver 直接 `await`；
> `_sleeping` 过渡由 `SleepManager._lock`（asyncio.Lock）保护，避免并发 tick 竞态。
> 旧 `web/server.py:_proactive_loop` 已被 `RuntimeDriver` 取代（unified-pipeline P2）。

#### 完整决策流程

```
RuntimeDriver.run() (15s tick)
    │
    ├──▶ engine.get_sleep_state()
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
    │    │   └── engine.generate_dream()
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
    ├── engine.is_sleeping? → skip + 用户消息 "zzz...💤"
    │
    ├── idle < 30s? → 绝对底线, continue
    │
    ├── idle > 情绪阈值? → engine.calculate_proactivity(idle)
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
    │    └── random() < score? → 触发! (Stage 1 轻量预筛选)
    │         │
    │         └── InnerDrive Agent 1 决策 (Stage 2 LLM推理, #125)
    │              │ assess_proactive(idle) → ProactiveIntent
    │              │   action: "chat" | "explore" | "silent"
    │              │   topic_hint + reasoning → Agent 3 上下文
    │              │
    │              ├── action="chat" → process_proactive(intent=intent)
    │              │    │ _check_rate_limit("chat"): 距上次 < 30min → 拒绝
    │              │    │ prompt: is_proactive=True + inner_drive_summary
    │              │    │ topic 由 inner drive 推理而非随机选择
    │              │    │ _react_loop(messages, add_to_history=False)
    │              │
    │              ├── action="explore" → process_explore(intent=intent)
    │              │    │ _check_rate_limit("explore"): 距上次 < 1hr → 拒绝
    │              │    │ prompt: explore_mode=True + inner_drive_summary
    │              │    │ AI 可自由调用 web_search/web_fetch
    │              │    │ 返回值: len > 30 且非工具输出 → 分享, 否则 None
    │              │
    │              └── action="silent" → 不操作 (不消耗频率限制)
    │
    └── 未触发 → await sleep(15), continue
```

#### 关键实现方法

| 方法 | 位置 | 说明 |
|------|------|------|
| `RuntimeDriver.run()` | core/runtime_driver.py | 统一时间驱动：睡眠/唤醒/主动搭话/探索 tick，CLI 守护线程 / Web asyncio task |
| `RuntimeDriver.start_in_thread()` | core/runtime_driver.py | CLI 入口：在独立事件循环的守护线程中启动驱动 |
| `ConversationEngine.handle_message()` | core/conversation_engine.py | 统一消息处理入口（三层 Agent 管线） |
| `ConversationEngine.handle_proactive()` | core/conversation_engine.py | 主动搭话执行入口 |
| `ConversationEngine.handle_explore()` | core/conversation_engine.py | 自由探索执行入口 |
| `ConversationEngine.get_sleep_state()` | core/conversation_engine.py | async；返回 (should_sleep, message_or_None) |
| `ConversationEngine.generate_dream()` | core/conversation_engine.py | async；LLM 生成梦境 |
| `InnerDriveAgent.perceive_and_decide()` | core/inner_drive.py | Agent 1 自主推理：检索记忆 → 识别缺口 → 决策 → 输出自然语言请求或跳过 |
| `build_inner_drive_prompt()` | prompts/system.py | Agent 1 system prompt：当前时间 + 身份 + 记忆 + 工具列表 |
| `ToolAgent.run_with_request()` | core/tool_agent.py | Agent 2 接收自然语言请求，执行外部工具，ToolAttemptTracker 重试 |
| `ToolAgent.run_with_requests()` | core/tool_agent.py | MH-001: 批量执行多个 ToolRequest，合并结果给 Agent 3 |
| `ToolAgent._build_prompt()` | core/tool_agent.py | Agent 2 精简 prompt（无情绪/记忆/工具记录） |
| `ToolAttemptTracker` | core/tool_agent.py | 3 retries/round × 3 rounds max = 9 总尝试，失败回报 Agent 1 |
| `_get_sleep_state()` | core/agent.py | async；返回 (should_sleep, message_or_None)，SL-002 锁保护 |
| `_generate_dream()` | core/agent.py | async；LLM 生成 1-2 句碎片化梦境，SL-010 非阻塞 |
| `decide_proactive_action(idle)` | core/agent.py | Agent 1 InnerDrive LLM 决策主动行为: chat/explore/silent (#125) |
| `assess_proactive(idle)` | core/inner_drive.py | InnerDrive 主动决策 prompt → ProactiveIntent |
| `_check_rate_limit(action)` | core/agent.py | explore: 3600s 间隔, chat: 1800s 间隔 |
| `_calculate_proactivity(idle)` | core/agent.py | 返回 0.0~0.8 的触发概率 |
| `_pick_proactive_topic()` | core/agent.py | 从经历/事实/通用中随机选话题 |
| `process_explore()` | core/agent.py | 探索模式: 自由工具调用, 有趣才分享 |
| `process_proactive()` | core/agent.py | 主动搭话: 调侃/分享/找话题 |

#### 状态追踪

```python
self._sleep.is_sleeping: bool       # 当前是否在睡眠 (SleepManager)
self._proactive._last_explore_time: float  # 上次探索时间戳 (ProactivityManager)
self._proactive._last_chat_time: float     # 上次聊天时间戳 (ProactivityManager)
```

### 5.6 虚假记忆修正（#6 已根治）

三层架构解决了工具调用虚构问题，**FactChecker (#6)** 进一步解决了事实层面的虚假记忆：
- 矛盾检测（直接 + embedding 语义相似度）
- 置信度衰减（×0.4 on contradiction，<0.2 软删除）
- 用户纠正（RememberTool `correct=true` → confidence=1.0）
- 检索过滤（confidence >= 0.2 SQL 过滤 + 评分权重）

---

## 6. 提示词工程

> 完整 Prompt 模板参考见 [Prompt 工程参考](prompt-reference.md)。

### 6.1 System Prompt 组装

按变化频率分三层组装（#160 分层缓存，core/prompt_cache.py）：

- **静态块**（身份、inner drive 指令、工具列表）：经 `PromptCache` 无 TTL 缓存，人格文件变更（mtime/size）自动失效
- **慢变块**（关系指标、长期记忆）：短 TTL 缓存（`prompt_cache_ttl_seconds`，默认 60s）
- **动态块**（当前时间、情绪状态、工具调用记录、最近对话、指令）：每次重建

Agent 1 检索后通过 `drive_result.context_summary` 把记忆/关系摘要直接传给 Agent 3 复用，不再重复检索。对话示例仅在前 `conversation_examples_max_turns`（默认 3）轮注入。

组装结果示例：

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

=== Block 6: 内部工具列表 ===
可用工具：recall / remember
<tool_call>{"name": "...", "arguments": {...}}</tool_call>

=== Block 7: 对话示例 + 指令 ===
用户：今天去外滩拍照了
你：蛙趣！那肯定好看！发出来看看[旺柴]

像朋友一样回她。嘴可以贱，但心要暖。
```

对话示例现在来自 `config.conversation_examples`（#28），可在 `config.json` 中自定义：

```json
{
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
### 6.2 Prompt 模板

| 模板 | 用途 | 关键参数 |
|------|------|----------|
| FACT_EXTRACTION | 从对话抽取用户事实 | text |
| EXPERIENCE_SUMMARIZATION | 总结共享体验 | text |
| INSIGHT_GENERATION | L1 假设性洞察（每次 consolidation，二期替代 REFLECTION） | facts, experiences |
| INSIGHT_L2 | L2 行为模式归纳（每 3 次） | facts, experiences, insights |
| INSIGHT_L3 | L3 长期模式/深度动机（每 10 次） | facts, experiences, relationship, current_emotion, patterns |
| EMOTION_ANALYSIS | 分析用户消息情感 | text |
| MEMORY_RERANK | 记忆候选重排序 | query, candidates |
| CONTEXT_COMPRESS | 对话摘要生成（prompts/system.py） | conversation |

---

## 7. Web 界面

> 完整 API 参考见 [API 文档](api.md)。

### 7.1 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | FastAPI (ASGI) |
| 通信 | WebSocket |
| 前端 | 纯 HTML + CSS + JS |
| 运行 | Uvicorn（开发）/ 多 worker（生产） |

### 7.2 WebSocket 协议

> 协议细节、消息格式、分段推送参数见 [API 文档](api.md#2-websocket-协议)。

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

由 `core/runtime_driver.py` 的 `RuntimeDriver` 统一驱动，Web 端每个 session 持有一个 `asyncio.Task`。

```
RuntimeDriver.run() (15s tick)
    │
    ├─ 入睡? → 发睡前消息 → 生成梦境
    ├─ 醒来? → 发梦境分享
    ├─ 睡着? → skip (30s后重试)
    ├─ 空闲 < 30s? → skip
    │
    ├─ 空闲 > 情绪阈值?
    │   └─ 随机命中? (Stage 1)
    │       └─ InnerDrive 决策 (Stage 2, #125)
    │           ├─ chat → 主动搭话 (2/hr)
    │           ├─ explore → 自由工具 (1/hr)
    │           └─ silent → 不操作
    └─ 未命中 → 等15s
```

空闲阈值与情绪挂钩：excited 60s, sad 900s, neutral 360s，resentment 额外+300s。

### 7.5 会话管理

```python
class SessionManager:
    _sessions: dict[session_id → WebAgent]
    _proactive_tasks: dict[session_id → asyncio.Task]
    _active_ws: dict[session_id → WebSocket]
    _lock: Lock

    def get_or_create(session_id) -> tuple[str, WebAgent]
    def remove(session_id)
    def register_proactive(session_id, task, websocket)
    def cleanup_old(max_sessions, ttl_seconds)
    async def shutdown()
```

- 每个 session 拥有独立的 `WebAgent` 实例（独立 `Personality` + `ConversationBuffer`）
- `WebAgent` 封装 `Agent` 私有接口，Web 端不再直接访问 `agent._xxx`（#45）
- 多标签页共享同一 session 时，新连接会 cancel 旧 proactive 任务
- `SessionManager` 级别共享 `LLMProvider` / `EmbeddingEngine` HTTP 会话（SN-005/006）
- 24h TTL / 最多 50 个 session 自动清理（#148）
- lifespan shutdown 阶段优雅关闭：保存 personality、cancel 任务、释放共享连接（#212）

### 7.6 REST API 与校验（#43）

REST 端点使用 Pydantic 模型（`web/schemas.py`）进行请求/响应校验：

| 模型 | 用途 | 关键约束 |
|------|------|----------|
| `ChatRequest` | `POST /api/chat` | `message` 必填且非空，`session_id` 默认 `"default"` |
| `ChatResponse` | `POST /api/chat` | `response`, `emotion`, `turn`, `session_id` |
| `StatusResponse` | `GET /api/status` | `turn`, `emotion`, `relationship`, `relationship_history` |
| `HistoryResponse` | `GET /api/chat/history` | `turns: list[HistoryTurn]`, `session_id` |

- 字段缺失/类型错误时 FastAPI 自动返回 `422 Unprocessable Entity`
- 校验失败信息包含具体字段与错误原因

### 7.7 Web 安全（#24）

| 机制 | 实现 | 说明 |
|------|------|------|
| CORS | `CORSMiddleware` | 默认允许 `localhost:8000` / `127.0.0.1:8000`；`config.allowed_origins` 可追加 |
| 速率限制 | `RateLimitMiddleware` + `RateLimiter` | per-IP 滑动窗口：聊天 30/60s，状态/历史 60/60s |
| WebSocket 限流 | `RateLimiter.is_allowed()` | `message` 消息同样受 30/60s 限制 |
| CSP | `Content-Security-Policy` | `script-src 'self'`（无内联脚本），`connect-src` 限制 localhost |
| X-Frame-Options | `DENY` | 防止点击劫持 |
| X-Content-Type-Options | `nosniff` | 防止 MIME 嗅探 |
| Referrer-Policy | `strict-origin-when-cross-origin` | 控制 referrer 泄露 |

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
confidence: float       # 0~1, <0.2 检索时自动过滤, 0=虚假记忆
importance: float       # 0~1（0.3 临时, 0.6 长期, 1.0 永久）
composite_score: float  # 综合评分用于检索排序
is_active: bool         # False=软删除（矛盾检测/用户纠正触发）
```

### 8.3 Experience

```python
summary: str
emotional_tone: str
significance: float     # 0~1
importance: float       # 0~1
tags: list[str]
```

### 8.4 Reflection（读路径兼容形状，数据来自 insights_v2）

```python
content: str            # 适配：= insights_v2.hypothesis
insight_type: str       # pattern / emotion / user_discovery / ...
significance: float     # 适配：= insights_v2.confidence
level: int              # 1/2/3（MM-006）
```

### 8.4b InsightV2（Layer 1 二期，2026-07-20）

```python
hypothesis: str         # 可验证的假设（非空）
evidence_fact_ids: list[int]  # 证据链（facts_v2 id 列表）
insight_type: str       # pattern / contradiction / connection / emotion / prediction / ...
confidence: float       # 0~1
needs_more_evidence: bool
expires_at: str | None  # 过期时间，GC 到期置 status='expired'
status: str             # active / expired / verified / rejected
created_by: str         # consolidation / migration / ...
```

### 8.5 Observation（ML-001）

```python
content: str            # 原始观察文本（整批对话，非空）
episode_turn_start/end: int
source_turn: int
created_by: str         # 默认 "consolidation"
session_id: str
embedding: bytes        # float32 × dim
is_archived: bool       # > 30 天由 GC 归档
```

### 8.6 FactV2（ML-001）

```python
category / fact_key / fact_value: str   # UNIQUE(session_id, category, fact_key)
confidence: float       # 0~1
stability: float        # 0~1 稳定性
freshness: float        # 0~1 新鲜度，decay 主指标
importance: float       # 0~1
status: str             # active / decayed / merged / obsolete / contradicted
source_observation_ids: list[int]
verification_count: int
```

---

## 9. 存储层

### 9.1 SQLite Schema

```sql
-- 9 张业务表（另有 schema_version 元表记录迁移版本，当前 version=5）
facts_v2            经验证的事实（UNIQUE(session_id, category, fact_key)，Layer 1）
experiences         共享体验（tags 存 JSON）
insights_v2         假设性洞察（evidence_fact_ids 存 JSON，二期替代 reflections）
relationship_metrics 关系指标（key-value，PK (session_id, dimension)）
conversation_turns  完整对话历史
relationship_snapshots 关系指标历史快照
session_roles       session_id → role_id 映射
observations        原始观察（Layer 1 记忆生命周期，ML-001）
user_facts_archive  旧 user_facts 归档（schema v4 后代码不再读写，数据保留）
```

### 9.2 WAL 模式

```sql
-- 异步执行（aiosqlite）
await conn.execute("PRAGMA journal_mode=WAL")
await conn.execute("PRAGMA foreign_keys=ON")
```

WAL 模式允许并发读写，配合 `asyncio.Lock` 确保协程安全。

### 9.3 连接管理

采用 `aiosqlite` + `asyncio.Lock` 异步架构，替代原有的 `sqlite3` + `threading.Lock`：

```python
class Database:
    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = asyncio.Lock()

    async def open(self):
        self.conn = await aiosqlite.connect(self._db_path)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")

    @asynccontextmanager
    async def cursor(self):
        async with self._lock:
            cursor = await self.conn.cursor()
            try:
                yield cursor
            finally:
                await cursor.close()

    async def close(self):
        await self.conn.close()
```

关键变更：
- `sqlite3.connect()` → `aiosqlite.connect()`（异步连接）
- `threading.Lock` → `asyncio.Lock`（协程安全）
- `__exit__` context manager → `@asynccontextmanager`（异步上下文管理器）
- `cursor.fetchall()` → `await cursor.fetchall()`（所有数据库操作异步化）
- `main.py` 使用 `asyncio.run()` 启动；`web/server.py` 在 lifespan 中 `await db.open()`

---

## 10. 配置系统

> 完整配置字段说明见 [配置参考](config-reference.md) 和 [人格定制指南](personality-guide.md)。

优先级：环境变量（DEEPSEEK_API_KEY / DEEPSEEK_API_ENDPOINT / DEEPSEEK_API_MODEL / AI_FRIEND_* 系列） > config.json > Config dataclass（加载时校验并 clamp 越界值）

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "max_tokens": 512,
  "temperature": 0.8,
  "db_path": "data/ai_friend.db",
  "short_term_capacity": 500,
  "consolidation_interval": 5,
  "proactive_min_idle": 180.0,
  "proactive_max_interval": 600.0,
  "typing_speed": 0.005,
  "max_facts": 200,
  "max_experiences": 100,
  "max_reflections": 50,
  "max_tool_iterations": 5,
  "web_host": "0.0.0.0",
  "web_port": 8000,
  "log_level": "INFO",
  "monitor_enabled": true,
  "embedding_endpoint": "http://localhost:8080/v1/embeddings",
  "embedding_dim": 1024,
  "embedding_cache_size": 1000,
  "prompt_cache_ttl_seconds": 60,
  "conversation_examples_max_turns": 3,
  "allowed_origins": []
}
```

---

## 11. 部署说明

> 生产部署指南见 [部署手册](deployment.md)。

### 环境

```bash
pip install -r requirements.txt
# requests / tiktoken / plyer / fastapi / uvicorn / websockets==12.0 / numpy
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
| `personalities/*.json` | 角色定义 + 情绪状态持久化 | 否 |
| `data/ai_friend.db` | SQLite 数据库 | 是 |
| `config.json` | 用户配置 | 是 |

### Token 估算

使用 `tiktoken` 的 `cl100k_base` 编码（待替换为 DeepSeek 专用 tokenizer）。不可用时回退启发式：

```
CJK 字符: × 1.5
ASCII 字母: ÷ 4
数字: ÷ 3
其他: ÷ 8
```

注意：cl100k_base 与 DeepSeek 实际 tokenizer 存在约 15–30% 误差，属已知限制（M-14）。DeepSeek 没有对应的 tiktoken 编码，替换需引入 HuggingFace tokenizers 新依赖，暂不处理。
