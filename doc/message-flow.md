# 消息流转流程

> 从你输入一行字到看见 AI 回复，完整的内部路径。CLI 和 Web 双端分别走不同路径。

---

## 两阶段流水线总览

```
用户输入
    │
    ▼
┌──────────────────────────────────────────────┐
│  Phase 1: ToolAgent (core/tool_agent.py)      │
│  temp=0.3, 精简 prompt, 无人格/情绪/记忆        │
│  执行外部工具: web_fetch/web_search/read_file   │
│             glob/grep/music_play/notify          │
│  结果作为 <tool_result> 注入 Phase 2 上下文       │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  Phase 2: Roleplay Agent (core/agent.py)      │
│  temp=0.8, 完整人格 + 情绪 + 记忆              │
│  内部工具: recall / remember                    │
│  ReAct 循环: THINK → ACT → THINK → ...        │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
              后处理: Emotion → Memory → Reflection
```

## 状态机总览（Phase 2 内部）

```
BOOT ──▶ IDLE ──▶ PERCEIVE ──▶ THINK ──▶ ACT ──▶ REFLECT ──▶ IDLE
(启动)   (等待)    (理解输入+   (调用LLM)  (输出)    (更新状态+   (循环)
                   检索记忆)               │         记忆合并)
                                          │
                                    ┌─────┴──────┐
                                    │ 有 tool_call│
                                    └─────┬──────┘
                                          └──▶ THINK (多轮 ReAct 迭代, 仅 recall/remember)
```

## CLI 模式 vs Web 模式

| 阶段 | CLI | Web |
|------|-----|-----|
| 等待输入 | 守护线程读 stdin → Queue | WebSocket 协程等待 receive_text() |
| 处理消息 | 状态机 _on_think → _on_act → _on_reflect | 直接调 process_message() → _react_loop() |
| 输出 | 打字机效果逐字打印 | 全量获取 → 6 级分段 → 独立气泡推送 |
| 主动对话 | IDLE 状态内轮询 | asyncio.create_task(_proactive_loop) |
| 空闲检测 | time.sleep(0.1) 轮询 | await asyncio.sleep(5/15) 协程睡眠 |

---

## 逐步骤详解

### 1. IDLE — 等待输入

#### CLI 模式

```
                 ┌──────────────────────────┐
                 │  后台守护线程             │
                 │  sys.stdin.readline()     │
                 │  → 有输入则放入 Queue     │
                 └──────────┬───────────────┘
                            │
                 ┌──────────▼───────────────┐
                 │  主循环非阻塞出队         │
                 │  Queue.get_nowait()      │
                 │  → 有输入 → PERCEIVE     │
                 │  → 无输入 → 检查主动触发  │
                 │     └ 空闲>180s?          │
                 │       计算 proactivity   │
                 │       随机命中 → THINK   │
                 │       (跳过了 PERCEIVE)   │
                 └──────────────────────────┘
```

#### Web 模式

```
┌─ WebSocket 协程 ────────────────────────┐
│  await websocket.receive_text()         │
│  → 收到 "message" → process_message()  │
│  → 没有消息时协程挂起，不占用 CPU      │
└──────────────────────────────────────────┘

┌─ _proactive_loop 后台协程 ─────────────┐
│  15s tick:                               │
│    ├─ _get_sleep_state()                │
│    │   午睡 12-13 / 夜睡 23:00-01:00     │
│    │   醒来自动分享梦境                  │
│    ├─ idle > 情绪阈值?                   │
│    │   excited 60s / sad 900s           │
│    │   └─ 40% explore / 60% chat       │
│    │       探索 1/hr, 聊天 2/hr         │
│    └─ 睡着? → skip                      │
└──────────────────────────────────────────┘
```

---

### 1.5 自主行为循环（Web 后台协程）

```
_proactive_loop (15s tick)
    │
    ├──▶ _get_sleep_state()
    │    │ 检查是否在睡眠时间窗口
    │    │ 午睡: 12:00-13:00, 夜睡: 23:00-01:00
    │    │ 情绪驱动 sleepiness:
    │    │   sad/melancholy +0.4, low arousal +0.3
    │    │   excited/joyful -0.2, resentment +0.2
    │    │
    │    ├── 触发入睡 → 发睡前消息 → _generate_dream()
    │    │   LLM: 基于事实+经历+情绪 → 碎片化梦境(1-2句)
    │    │   存储: record_emotion_event("梦: ...")
    │    │
    │    └── 触发醒来 → 发梦境分享消息
    │        午醒: 13:10-16:00, 晨醒: 7:00-10:00
    │        arousal 高 → 醒得早, resentment 高 → 醒得晚
    │
    ├── ag._sleeping? → await sleep(30), continue
    │   (睡着的AI: 所有消息自动回复 "zzz...💤", 探索暂停)
    │
    ├── idle < 30s? → skip
    │
    ├── idle > 情绪阈值? → _calculate_proactivity()
    │    │ excited 60s, joyful 90s, engaged 180s
    │    │ neutral 360s, sad 900s, angry 480s
    │    │ resentment 额外 +300s
    │    │
    │    └── random < score?
    │         │
    │         ├── 40% → process_explore()
    │         │    │ _check_rate_limit("explore") → 1/hr
    │         │    │ prompt: explore_mode=True
    │         │    │ AI 自主: web_search, web_fetch, music_list...
    │         │    │ 有趣的? → 返回分享消息
    │         │    │ 没趣的? → 返回 None (安静)
    │         │
    │         └── 60% → process_proactive()
    │              │ _check_rate_limit("chat") → 2/hr
    │              │ prompt: is_proactive=True
    │              │ 主动搭话, 调侃, 分享日常
    │              │ add_to_history=False (不发到短期记忆)
    │
    └── 未命中 → await asyncio.sleep(15)
```

### 工具调用记录

每次 `_react_loop` 中执行工具后:
```
self._tool_call_history.append({
    "name": tool_name,
    "success": True/False,
    "output": result[:200],
    "time": time.time(),
})
```
最多保留 20 条, 注入下一次 prompt (`=== 你的工具调用记录 ===`)。

---

### 2. PERCEIVE — 理解输入（CLI 独占，Web 走 process_message）

```
用户输入 "你好"
    │
    ├──▶ ① ConversationBuffer.add_turn("user", "你好")
    │     短期记忆：deque 追加
    │
    ├──▶ ② repo.insert_turn(turn_count, "user", ...)
    │     SQLite conversation_turns 表永久存储
    │
    ├──▶ ③ MemoryRetriever.retrieve_for_query("你好")
    │      │
    │      ├── Layer 1: 取全部 active facts（SQLite）
    │      ├── Layer 2: 关键词评分 → LLM 重排序
    │      │   score = w₁×时效 + w₂×重要 + w₃×衰减 + w₄×关键词
    │      │   候选>15条 → 极小LLM调用重排
    │      └── Layer 3: 取最新 experiences + reflections
    │
    └──▶ ④ 打包成 MemoryContext
           { facts, experiences, reflections, relationship }
              │
              ▼ 状态 → THINK
```

**数据变更**：
| 位置 | 写入了什么 |
|------|-----------|
| ConversationBuffer | `{role:"user", content:"你好"}` |
| SQLite conversation_turns | 完整对话行 |
| MemoryContext（内存） | 检索到的相关记忆 |

---

### 3. THINK — 调用 LLM（两阶段）

先执行 Phase 1 ToolAgent，再执行 Phase 2 Roleplay Agent。

#### Phase 1: ToolAgent（纯工具调用）

```
用户输入 + 工具上下文
    │
    ▼
ToolAgent._build_prompt()  ── 精简 prompt, 仅含工具列表 + 当前时间
    │ 无人格描述, 无情绪状态, 无对话历史, 无工具调用记录
    │ temperature=0.3
    ▼
POST DeepSeek API  ── 模型决策是否使用工具
    │
    ├── 无 <tool_call> → 结果为空 → 直接进入 Phase 2
    │
    └── 有 <tool_call> → dispatcher 执行工具
        │  ≥ 1 轮 tool call results
        │  作为 <tool_result> 注入 Phase 2 上下文
        ▼
进入 Phase 2
```

#### Phase 2: Roleplay Agent（人格驱动回复）

THINK 可能执行多次（ReAct 循环），每次的流程相同：

```
    ┌── 首次调用 ──────────────────────────────┐
    │ ① build_system_prompt() 拼接 7 个区块    │
    │                                          │
    │    Block 1 — 当前时间                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 当前时间：2026-05-28 12:00       │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 2 — 身份核心                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 你是小星，一个有情感的AI朋友    │   │
    │    │ 你的特质：playfulness 95%...    │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 3 — 情绪状态                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 你感到 满足，心底有一丝喜悦      │   │
    │    │ 情绪积极，平静                   │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 4 — 关系指标                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 信任: 0.3  熟悉度: 0.3           │   │
    │    │ 亲密: 0.3  趣味: 0.3             │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 5 — 长期记忆                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 关于用户: 名字=小陈 摄影=街拍   │   │
    │    │ 共同回忆: [温暖] 分享宠物趣事   │   │
    │    │ 工具: recall / remember          │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 6 — 对话示例                     │
    │    Block 7 — 最近对话 + 指令              │
    │                                          │
    │ ② 构建 messages 数组                      │
    │    [system_prompt, 历史对话..., 当前输入]  │
    │    动态算 token，塞到 80% 阈值             │
    │                                          │
    │ ③ POST https://api.deepseek.com/...      │
    │    model: deepseek-v4-flash               │
    │    max_tokens: 随情绪动态调整              │
    │    stream: true                           │
    │                                          │
    │ ④ SSE 流式解析                            │
    │    CLI: on_token() → 打印到终端            │
    │    Web: 全量获取 → 6 级分段 → 独立气泡     │
    │                                          │
    │ ⑤ parse_tool_calls()                     │
    │    检查 <tool_call> 标签                   │
    │    → 有 → ACT 执行工具 → 继续 THINK       │
    │    → 无 → cleaned_text 为最终回复          │
    └──────────────────────────────────────────┘
```

**ReAct 多轮迭代（Phase 2，仅 recall/remember）**：

```
THINK ─── 解析出 <tool_call> {"name": "recall", "arguments": {...}}
    │
    ▼
ACT: execute_tool_calls(registry, calls)
    │  tools/memory_tools.py → ltm.store_fact(...)
    │  → SQLite user_facts
    ▼
结果格式化为 <tool_result name="recall">
    │  \n找到 2 条：\n- 名字: 小陈\n- 摄影: 街拍\n
    ▼
追加到 messages → THINK（下一轮，最多 10 次）
    │
    ▼
无 tool_call → 结束迭代
```

---

### 4. ACT — 输出

#### CLI 模式

已在 THINK 阶段流式打印完成，ACT 只做存储：
- ConversationBuffer.add_turn("assistant", ...)
- SQLite conversation_turns 写入

#### Web 模式 — 分段推送

```
response = agent.process_message(content)
    │
    ▼
_split_segments(response)
    │  6 级 fallback：
    │    ① 标点（。！？.!?\n，含引号括号尾随）
    │    ② 逗号（，,；;，40 字以上长段）
    │    ③ 空格
    │    ④ 语气词（啊吗呢了吧么呀哦嘛哇）
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
    │
    ▼
前端 JS: 每个 segment 创建独立 assistant 气泡
    ▼
await ws.send({"type": "done", "emotion": "engaged", "turn": 5})
```

客户端 REST fallback 时 `splitSegments()` 使用相同 6 级策略，`setTimeout` 模拟分段延时。

**延迟计算公式**：

```
delay = base[emotion] × (1 + seg_len/80) × random(0.8, 1.3)
```

| 情绪 | 基础延时 |
|------|----------|
| excited / surprised | 0.7~0.8s |
| joyful / anticipating | 0.9s |
| trusting | 1.1s |
| engaged | 1.3s |
| content | 1.5s |
| neutral | 1.7s |
| melancholy | 2.2s |
| sad | 2.5s |

---

### 5. REFLECT — 更新状态

```
    ┌─────────────────────────────────────────┐
    │  ① 情感分析（分析用户输入，非 AI 回复） │
    │     consolidator.analyze_sentiment("你好") │
    │     → {sentiment: 0.3, sharing: false, energy: 0.5} │
    │                                          │
    │  ② 情绪更新（四层处理）                 │
    │     2a. shift(dv, da, primary_deltas)    │
    │     2b. _cross_modulate()               │
    │         anger×0.6 → joy↓ trust↓          │
    │         sadness → joy↓ anticipation↓     │
    │         resentment 放大压制、锁 joy 天花板│
    │     2c. 怨恨累积 (anger>0.6 → resentment↑)│
    │     2d. decay() — 分速衰减                │
    │         surprise 3t, anger 15t, trust 25t │
    │         resentment 3%/turn 慢衰减          │
    │     2e. record_emotion_event()            │
    │         强情绪自动记录（为什么生气）       │
    │                                          │
    │  ③ 记忆合并检查                          │
    │     should_consolidate() → True?          │
    │       │                                  │
    │       ├── ▶ LLM 抽取 facts               │
    │       │    → FACT|identity|名字|小陈|0.9  │
    │       │    → upsert user_facts           │
    │       │                                  │
    │       ├── ▶ LLM 总结体验                 │
    │       │    → SUMMARY|温暖|分享宠物趣事   │
    │       │    → insert experiences          │
    │       │                                  │
    │       ├── ▶ 生成反思                     │
    │       │    → insert reflections          │
    │       │                                  │
    │       └── ▶ 更新关系指标                  │
    │            familiarity += 0.02            │
    │            if sentiment>0.3: trust +=    │
    │                                          │
    │  ④ 修剪超量记忆                          │
    │     facts ≤ 200, experiences ≤ 100       │
    │     reflections ≤ 50                     │
    │                                          │
    │  ⑤ 每 10 轮保存 personality.json          │
    └─────────────────────────────────────────┘
```

---

## 完整数据流

```
你输入 "你好"
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  IDLE（CLI）/ WebSocket（Web）                                │
│  CLI: 守护线程 → Queue → 出队成功 → PERCEIVE                  │
│  Web: 协程收到 "message" → process_message()                  │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  PERCEIVE / process_message                                  │
│  ① ConversationBuffer.add("user", 输入)                      │
│  ② SQLite: INSERT conversation_turns                        │
│  ③ MemoryRetriever.retrieve_for_query()                     │
│     ├ 读 SQLite: user_facts + experiences + reflections      │
│     └ 读 SQLite: relationship_metrics                        │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 1: ToolAgent (core/tool_agent.py)                     │
│  temp=0.3, 精简 prompt, 仅工具列表                            │
│  ① POST DeepSeek API → 模型决策是否使用外部工具                 │
│  ② 无 <tool_call> → 直接进入 Phase 2                          │
│  ③ 有 <tool_call> → 执行工具 → 结果注入 Phase 2 上下文          │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Phase 2: THINK / _react_loop (core/agent.py)                │
│  temp=0.8, 完整人格 + 情绪 + 记忆                              │
│  ① 组装 system prompt（含 Phase 1 工具结果）                   │
│  ② 估算 token，动态塞对话到 80%                               │
│  ③ POST DeepSeek API（max_tokens 随情绪调整）                  │
│  ④ 解析 SS，检查 <tool_call>（仅 recall/remember）              │
│  ⑤ 有 tool_call → 执行 → 结果喂回 → 继续 THINK               │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  ACT（无 tool_call）                                          │
│  CLI: 已在 THINK 流式打印，只做存储                             │
│  Web: _split_segments (6 级) → _calc_delay → 独立气泡推送     │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  REFLECT                                                      │
│  ① 情感分析 → 情绪更新 → decay                                 │
│  ② 记忆合并（5轮/高强度）→ 修剪上限                             │
│  ③ 状态 → IDLE                                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 关键数据存储

| 存储 | 位置 | 生命周期 | 内容 |
|------|------|----------|------|
| ConversationBuffer | 内存 deque | 进程级别 | 最近 500 轮 |
| SQLite user_facts | data/ai_friend.db | 永久 | 用户事实 |
| SQLite experiences | data/ai_friend.db | 永久 | 共享体验 |
| SQLite reflections | data/ai_friend.db | 永久 | 反思洞察 |
| SQLite relationship_metrics | data/ai_friend.db | 永久 | 关系指标 |
| SQLite conversation_turns | data/ai_friend.db | 永久 | 对话历史 |
| EmotionalState | 内存 + personality.json | 进程 + 持久化 | 当前情绪 |
