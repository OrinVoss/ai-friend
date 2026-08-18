# 消息流转流程

> 从你输入一行字到看见 AI 回复，完整的内部路径。CLI 和 Web 双端分别走不同路径。

> WebSocket/REST 协议参考见 [API 文档](api.md)。

---

## 三层流水线总览

编排器：CLI 与 Web 路径统一由 `MessageHandler`（core/message_handler.py）经 `ConversationEngine`（core/conversation_engine.py）编排三层流水线；CLI 仅剩输入循环与终端渲染（core/cli_controller.py）。时间驱动（睡眠/主动/探索）由 `RuntimeDriver`（core/runtime_driver.py）统一承担。

```
用户输入
    │
    ▼
┌──────────────────────────────────────────────┐
│  Agent 1: InnerDriveAgent (core/inner_drive.py)│
│  Perceive → 检索记忆 → 识别缺口 → 决策          │
│  内部工具: recall / remember (SQLite)          │
│  无需外部工具? → 直接跳过 Agent 2 (闲聊优化)      │
│  需外部工具? → 输出自然语言请求给 Agent 2        │
│  输出 summary + context_summary(记忆/关系摘要)  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼ (非闲聊路径)
┌──────────────────────────────────────────────┐
│  Agent 2: ToolAgent (core/tool_agent.py)       │
│  精简 prompt, 无人格/情绪/记忆                  │
│  ToolAttemptTracker: 3 retries/round, 3 rounds │
│  执行外部工具: web_fetch/web_search/read_file   │
│       file_tree/glob/grep/music_play/notify    │
│  成功 → Agent 1 review 是否还需工具(最多3轮)    │
│  失败 → 回报 Agent 1 重新决策                    │
│  结果作为 <tool_result> 注入 Agent 3 上下文       │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  Agent 3: Roleplay Agent (core/agent.py)       │
│  temp=0.8, 完整人格 + 情绪 + 记忆              │
│  接收 summary + context_summary + tool_results │
│  (复用 Agent 1 记忆/关系摘要, 不重复检索)        │
│  内部工具: recall / remember / history_search  │
│  ReAct 循环: THINK → ACT → THINK → ...        │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
              后处理: Emotion → Memory → Reflection
```

## 引擎与编排状态（ConversationEngine + MessageHandlerState）

统一管线 P0–P3 完成后，CLI 与 Web 共用同一条管线：用户输入经 `ConversationEngine.handle_message` 进入 `MessageHandler`；时间驱动（睡眠/主动/探索）由 `RuntimeDriver` 按同一节奏驱动两端。CLI 旧的内联状态机（BOOT/IDLE/PERCEIVE/THINK/ACT/REFLECT）已随 P3 移除。

`MessageHandler` 内部以轻量 `MessageHandlerState`（ASSESSING / EXECUTING_TOOLS / HANDLING_INTENT / GENERATING_RESPONSE / DONE 等）记录编排阶段，供观测与测试。

```
用户输入 ──▶ ConversationEngine.handle_message ──▶ MessageHandler
                                                      │
              ┌───────────────────────────────────────┼────────────────────────┐
              ▼                                       ▼                        ▼
        Agent 1 assess                          Agent 2 多轮工具           Agent 3 生成
        (全量推理)                             (3轮×3重试+review)         (含意图审批回路)
                                                      │
                                                      ▼
                                              事件: on_token / on_message_done
                                              / on_proactive / on_sleep_reply

时间 tick ──▶ RuntimeDriver.run() ──▶ engine.handle_proactive / handle_explore
                                      / get_sleep_state / generate_dream
```

## CLI 模式 vs Web 模式

| 阶段 | CLI | Web |
|------|-----|-----|
| 等待输入 | prompt_toolkit PromptSession（历史/补全/状态栏） | WebSocket 协程等待 receive_text() |
| 处理消息 | engine.handle_message → MessageHandler 编排三层 → _react_loop() | process_message() → MessageHandler 编排三层 → _react_loop() |
| 输出 | 打字机效果逐字打印 + 阶段状态提示（on_status） | 单条 segment 全量推送（分段代码已随 P3 删除，见第 4 节） |
| 主动对话 | RuntimeDriver 守护线程 | RuntimeDriver asyncio task |
| 空闲检测 | prompt_toolkit 阻塞读取（后台线程驱动主动行为） | await asyncio.sleep(5/15) 协程睡眠 |
| 封装层 | 无（直接操作 Agent） | `WebAgent` 封装 `Agent` 私有接口（#45） |

### WebAgent 封装层（#45）

Web 服务端不直接操作 `Agent` 实例，而是通过 `web/session.py` 中的 `WebAgent`：

```
WebSocket / REST 端点
    │
    ▼
SessionManager.get_or_create() → WebAgent
    │
    ├── process_message(content)      # 代理 Agent.process_message
    ├── process_proactive(intent)     # 代理 Agent.process_proactive
    ├── process_explore(intent)       # 代理 Agent.process_explore
    ├── emotion (property)            # 代理 personality.emotion.dominant_emotion
    ├── turn_count (property)         # 代理 agent.turn_count
    ├── last_activity (property)      # 代理 agent.last_activity_time
    ├── get_sleep_state()             # 代理 agent._get_sleep_state
    ├── generate_dream()              # 代理 agent._generate_dream
    └── close()                       # 释放 per-session 资源（SN-013）
```

`WebAgent` 内部负责：
- 为每个 session 创建独立的 `Personality` / `ConversationBuffer` / `LongTermMemory`
- 复用 `SessionManager` 共享的 `LLMProvider` 与 `EmbeddingEngine`（SN-005/006）
- 30s 防抖保存 `personalities/{role_id}.json`（#44）
- 在 session 移除/关闭时调用 `close()` 持久化情绪状态

---

## 逐步骤详解

### 1. IDLE — 等待输入

#### CLI 模式

```
                 ┌──────────────────────────┐
                 │  prompt_toolkit           │
                 │  PromptSession.prompt()   │
                 │  FileHistory/命令补全/    │
                 │  状态栏/bottom_toolbar    │
                 │  非控制台环境回退 input() │
                 └──────────┬───────────────┘
                            │
                 ┌──────────▼───────────────┐
                 │  主循环阻塞读取一行       │
                 │  ui.read_input()         │
                 │  → 有输入 →              │
                 │    engine.handle_message  │
                 │    (即 PERCEIVE)          │
                 │  patch_stdout 让后台主动 │
                 │  消息安全插入输入行上方   │
                 │  主动触发由 RuntimeDriver │
                 │  守护线程负责(见 1.5 节)  │
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
│    │   └─ Agent 1 LLM 决策:             │
│    │      chat / explore / silent       │
│    │       探索 1/hr, 聊天 2/hr         │
│    └─ 睡着? → skip                      │
└──────────────────────────────────────────┘
```

---

### 1.5 自主行为循环（RuntimeDriver 统一驱动）

```
_proactive_loop (15s tick)
    │
    ├──▶ await _get_sleep_state()      # SL-002: asyncio.Lock 保护 _sleeping 过渡
    │    │ 检查是否在睡眠时间窗口
    │    │ 午睡: 12:00-13:00, 夜睡: 23:00-01:00
    │    │ 情绪驱动 sleepiness:
    │    │   sad/melancholy +0.4, low arousal +0.3
    │    │   excited/joyful -0.2, resentment +0.2
    │    │
    │    ├── 触发入睡 → 发睡前消息 → await _generate_dream()   # SL-010: async, 非阻塞
    │    │   LLM: 基于事实+经历+情绪 → 碎片化梦境(1-2句)
    │    │   存储: record_emotion_event("梦: ...") + store_experience("梦境: ...")
    │    │   状态持久化: .sleep_state.{session_id} (SL-001 每会话一文件)
    │    │
    │    └── 触发醒来 → 发梦境分享消息
    │        午醒: 13:10-16:00, 晨醒: 7:00-10:00
    │        10:00-11:00 仍未醒 → 强制醒来兜底 (SL-011)
    │        arousal 高 → 醒得早, resentment 高 → 醒得晚
    │
    ├── ag._sleeping? → await sleep(30), continue
    │   (睡着的AI: 消息自动回复随机睡语(4种), 照常入库 #185, 探索暂停)
    │
    ├── idle < 30s? → skip
    │
    ├── idle > 情绪阈值? → _calculate_proactivity()
    │    │ excited 60s, joyful 90s, engaged 180s
    │    │ neutral 360s, sad 900s, angry 480s
    │    │ resentment 额外 +300s
    │    │
    │    └── random < score? (Stage 1 轻量预筛选)
    │         │
    │         └── InnerDrive Agent 1 决策 (Stage 2 LLM推理, #125)
    │              │ assess_proactive(idle) → ProactiveIntent
    │              │
    │              ├── action="chat" → process_proactive(intent=intent)
    │              │    │ check_rate_limit("chat") → 2/hr
    │              │    │ prompt: is_proactive=True
    │              │    │ 主动搭话, 调侃, 分享日常
    │              │    │ add_to_history=True (回复入短期记忆)
    │              │
    │              ├── action="explore" → process_explore(intent=intent)
    │              │    │ check_rate_limit("explore") → 1/hr
    │              │    │ prompt: explore_mode=True
    │              │    │ AI 自主: web_search / web_fetch 等外部工具
    │              │    │ 有趣的(>30字且非"搜索"开头)? → 返回分享消息
    │              │    │ 没趣的? → 返回 None (安静)
    │              │
    │              └── action="silent" → 不操作 (不消耗频率限制)
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
    ├──▶ ② repo.insert_turn_sync(turn_count, "user", ...)
    │     SQLite conversation_turns 表永久存储
    │
    ├──▶ ③ MemoryRetriever.retrieve_for_query("你好")
    │      │
    │      ├── Layer 1 热记忆: active facts(≤50) + 最新
    │      │   experiences(5) + reflections(3) + 关系指标
    │      ├── Layer 2 混合检索: 语义×0.6 + 关键词×0.4
    │      │   (无 embedding 时退化为纯关键词评分)
    │      │   候选>15条 → 极小LLM调用重排
    │      └── Layer 3 按需: AI 输出 [回忆: xxx] 时触发检索
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

### 3. THINK — 调用 LLM（三层）

先执行 Agent 1 InnerDrive，需要时再执行 Agent 2 ToolAgent，最后 Agent 3 Roleplay。Web 与 CLI 路径均由 `MessageHandler.handle_message` 串联全程（含 PromptCache、context_summary 复用、Agent 3 意图回路）；CLI 经 `ConversationEngine` 进入同一入口（统一管线 P3 后，CliController 内联实现已删除）。同一条消息内 Agent 1 的 assess / review / re_decide 共享 `_cs_memo` 记忆摘要缓存，`memory_agent.answer()` 每轮至多一次（R1，2026-07-20）。Agent 1 决策时使用 `CognitiveState`（Phase 1+2）：输入去重过滤、error_fallback 跳过重复、决策温度 0.3；装配后不再修改 `memory_summary` / `memory_confidence` / `memory_answer`（WS-27/28，2026-07-26），Agent 3 的轻量记忆视图统一由 `render_memory_light()`（core/cognitive_state.py）渲染，有摘要时 `_run_agent3` 不再冗余 `retrieve_for_query`。`InnerDriveState`（core/inner_drive_state.py，内驱状态池二期）参与主动沉思循环——独处时 `surface()` 浮现挂念条目，对话时 `surface_for_query()` 按语义相关浮现。

#### Agent 1: InnerDriveAgent（自主推理决策）

```
用户输入 + 记忆上下文
    │
    ▼
InnerDriveAgent.assess()
    │ build_inner_drive_prompt(): 当前时间 + 身份 + 记忆 + 工具列表
    │   (静态/慢变块走 PromptCache, TTL=prompt_cache_ttl_seconds=60, #160)
    │ recall_query → 内部 recall 检索循环(最多5轮)
    ▼
POST DeepSeek API  ── JSON Schema 结构化决策 (#ID-001)
    │
    ├── 闲聊/无需工具 → 输出 summary + context_summary
    │   → 跳过 Agent 2 → 直接进入 Agent 3 (1 次 LLM 调用)
    │
    └── 需要外部工具 → 输出自然语言工具请求给 Agent 2
        ▼
进入 Agent 2
```

#### Agent 2: ToolAgent（外部工具执行）

```
Agent 1 的自然语言请求
    │
    ▼
ToolAgent.run_with_request(request)
    │ build_tool_agent_prompt(): 精简 prompt, 仅工具列表+规则
    │ ToolAttemptTracker: 每轮 3 次重试, 最多 3 轮 (9 总尝试)
    ▼
POST DeepSeek API  ── 模型决策并执行工具
    │
    ├── 执行成功 → Agent 1 review 结果是否足够
    │   → 还需工具 → 下一轮 (最多 3 轮)
    │   → 足够 → 结果注入 Agent 3 上下文
    │
    └── 全部尝试失败 → 回报 Agent 1 重新决策 (re_decide)
        ▼
Agent 1 重新评估 → 调整策略或放弃外部工具
```

工具结果归因（MH-002，2026-07-26）：每条 `ToolCallRecord` 带 `request` 字段记录所属自然语言请求（截断 80 字符）；`run_with_requests` 多请求并发合并后，`format_for_phase2` 在存在两个及以上不同 `request` 时按请求分组渲染（小标题 `【请求：…】`，铁律段仅末尾一次）再注入 Agent 3，Agent 3 因此能说清"哪件事没办成"；单请求时格式不变。

#### Agent 3: Roleplay Agent（人格驱动回复）

接收 Agent 1 的 summary + context_summary + Agent 2 的 tool_results。可能执行多次 ReAct 循环：

```
    ┌── 首次调用 ──────────────────────────────┐
    │ ① build_system_prompt(...) 按静态/慢变/动态分层拼接 (#160)    │
    │    静态+慢变块走 PromptCache (TTL=60s)     │
    │                                          │
    │    Block 1 — 当前时间                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 当前时间：2026-05-28 12:00       │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 2 — 身份核心 (静态, 缓存)         │
    │    ┌──────────────────────────────────┐   │
    │    │ 你是小星，一个有情感的AI朋友    │   │
    │    │ 你的特质：playfulness 95%...    │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 3 — 情绪状态 (动态)               │
    │    ┌──────────────────────────────────┐   │
    │    │ 你感到 满足，心底有一丝喜悦      │   │
    │    │ 情绪积极，平静                   │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 4 — 关系指标 (慢变, TTL缓存)      │
    │    ┌──────────────────────────────────┐   │
    │    │ 信任: 0.3  熟悉度: 0.3           │   │
    │    │ 亲密: 0.3  趣味: 0.3             │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 5 — 长期记忆 (慢变, TTL缓存)      │
    │    ┌──────────────────────────────────┐   │
    │    │ 关于用户: 名字=小陈 摄影=街拍   │   │
    │    │ 共同回忆: [温暖] 分享宠物趣事   │   │
    │    └──────────────────────────────────┘   │
    │    ※ Agent 1 已生成 context_summary 时     │
    │      Block 4+5 直接复用, 不再二次检索      │
    │                                          │
    │    Block 6 — 对话示例 (仅前3轮注入,         │
    │              conversation_examples_max_turns)│
    │    Block 7 — 最近对话 + 指令 + 输出规则     │
    │    (动态块按需插入: Agent 1 判断 / 工具记录 │
    │     / 怨恨·破防状态 / recall·remember 工具)│
    │                                          │
    │ ② 构建 messages 数组（#130 跳过舞台指示）  │
    │    [system_prompt, 历史对话..., 当前输入]  │
    │    跳过"（调用..."等 AI 表演型工具调用     │
    │    动态算 token，塞到 80% 阈值             │
    │                                          │
    │ ③ POST https://api.deepseek.com/...      │
    │    model: deepseek-v4-flash               │
    │    max_tokens: 随情绪动态调整              │
    │    stream: true                           │
    │                                          │
    │ ④ SSE 流式解析                            │
    │    CLI: on_token() → 打印到终端            │
    │    Web: 全量获取 → 单条 segment 推送       │
    │                                          │
    │ ⑤ parse_tool_calls()                     │
    │    检查 <tool_call> 标签                   │
    │    → 有 → ACT 执行工具 → 继续 THINK       │
    │    → 无 → cleaned_text 为最终回复          │
    └──────────────────────────────────────────┘
```

**ReAct 多轮迭代（Agent 3，仅内部工具 recall/remember/history_search）**：

```
THINK ─── 解析出 <tool_call> {"name": "recall", "arguments": {...}}
    │
    ▼
ACT: execute_tool_calls(registry, calls)
    │  tools/memory_tools.py → ltm.store_fact(...)
    │  → SQLite facts_v2（旧方法名适配，user_facts 已随 schema v6 物理删除）
    ▼
结果格式化为 <tool_result name="recall">
    │  \n找到 2 条：\n- 名字: 小陈\n- 摄影: 街拍\n
    ▼
追加到 messages → THINK（下一轮，最多 max_tool_iterations=5 次）
    │
    ▼
无 tool_call → 结束迭代
```

**Agent 3 意图回路（MessageHandler 路径）**：Agent 3 也可以不直接回复，而是输出 JSON 意图（`reply_to_user` / `intent` / `intent_description` / `intent_target` 四字段，intent 如 play_music / search_web）→ Agent 1 `assess_agent3_intent` 审批（结合用户原始输入与情绪判断，`INTENT_TO_TOOL` 给出建议工具映射）→ 批准则 Agent 2 单轮执行 → Agent 3 生成最终回复（最多循环 2 次）；拒绝则返回过渡性回复。

工具声明与执行的一致性（#301，2026-07-26）：Agent 3 prompt 的「可用工具」块只渲染内部 registry（recall / remember / history_search，与 ReAct 执行 registry 严格一致）；外部动作不出现在工具块中，只能经上述 intent 回路发起——`build_system_prompt(tools=内部 registry, rule_tools=全量 registry)`，输出规则块的 intent 选项由 `rule_tools` 派生（Agent 1 侧 M-06 同款模式）。主动搭话（handle_proactive）与自由探索（handle_explore）路径同样按此传参。

---

### 4. ACT — 输出

#### CLI 模式

已在 THINK 阶段流式打印完成，ACT 只做存储：
- ConversationBuffer.add_turn("assistant", ...)
- SQLite conversation_turns 写入

#### Web 模式 — 推送（分段当前禁用）

```
response = agent.process_message(content)
    │
    ▼
_send_segments(): 整条回复作为单个 segment 发送
    │  (server.py 留有 TODO: markdown 流式稳定后恢复分段)
    ▼
{"type": "segment", "content": 完整回复}
{"type": "done", "emotion": "engaged", "turn": 5}
    │
    ▼
前端 JS: 单气泡渲染; REST 模式同样全量返回 response
```

原保留代码 `_split_segments()`（6 级 fallback）与 `_calc_delay()`（情绪基础延时 0.7~2.5s × 长度系数 × 随机 0.8~1.3）已随统一管线 P3 收尾删除（2026-07-16，含唯一调用方 tests/test_segmentation.py）；分段推送若要恢复，可从 git 历史找回。

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
    │     2d. decay() — 分速衰减 + 时间衰减     │
    │         surprise 3t, anger 15t, trust 25t │
    │         resentment 3%/turn 慢衰减          │
    │         decay_elapsed 按真实时间衰减（A6）│
    │         软边界限制（_valence_boundary_count）│
    │     2e. record_emotion_event()            │
    │         强情绪自动记录（为什么生气）       │
    │                                          │
    │  ③ 记忆合并检查                          │
    │     should_consolidate() → True?          │
    │       │                                  │
    │       ├── ▶ 统一固化（consolidation_unified_call=on）│
    │       │    事实提取+体验总结+L1 insight 合并为 1 次 LLM │
    │       │    → Observation（整批对话文本，无新增 LLM）  │
    │       │    → FACT|cat|key|val|conf|imp|type          │
    │       │    → promote 为 FactV2（单写 facts_v2）      │
    │       │    → FactChecker 矛盾检测 (#6)               │
    │       │      同 key 不同 value → 直接矛盾            │
    │       │      语义相似 >0.65 → LLM 复核，复述否决保留  │
    │       │    → SUMMARY:/TONE: 分块（分享宠物趣事·温暖）→ experiences │
    │       │    → L1 洞察（hypothesis/evidence/confidence）│
    │       │       → insert insights_v2                  │
    │       │                                              │
    │       ├── ▶ L2 行为模式（每 3 次）/ L3 深度洞察（每 10 次）│
    │       │    → 同样结构化 JSON → insights_v2           │
    │       │                                              │
    │       ├── ▶ 矛盾向上传播                             │
    │       │    Fact 被推翻 → 引用它的 active Insight      │
    │       │    → needs_more_evidence=1, confidence×0.5   │
    │       │                                              │
    │       └── ▶ 更新关系指标                              │
    │            familiarity += 0.02                        │
    │            if sentiment>0.3: trust +=                │
    │                                                      │
    │  ④ 修剪超量记忆                                      │
    │     facts_v2 ≤ 200, experiences ≤ 100               │
    │     insights_v2 ≤ 50                                 │
    │                                                      │
    │  ⑤ 每 10 轮保存 personalities/{role_id}.json          │
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
│  CLI: PromptSession 阻塞读取一行 → engine.handle_message      │
│  Web: 协程收到 "message" → process_message()                  │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  PERCEIVE / process_message                                  │
│  ① ConversationBuffer.add("user", 输入)                      │
│  ② SQLite: INSERT conversation_turns                        │
│  ③ MemoryRetriever.retrieve_for_query()                     │
│     ├ 读 SQLite: facts_v2 + experiences + insights_v2       │
│     └ 读 SQLite: relationship_metrics                        │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Agent 1: InnerDriveAgent (core/inner_drive.py)                │
│  ① 检索记忆 → 识别知识缺口 → 自主推理决策                       │
│  ② 闲聊/无需工具 → 直接进入 Agent 3 (1 次 LLM 调用)             │
│  ③ 需外部工具 → 输出自然语言请求给 Agent 2                      │
│  输出 summary + context_summary 供 Agent 3 复用                 │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Agent 2: ToolAgent (core/tool_agent.py)                       │
│  精简 prompt, ToolAttemptTracker                                 │
│  ① 接收 Agent 1 自然语言请求 → POST API → 执行外部工具           │
│  ② 成功 → 结果注入 Agent 3 上下文                               │
│  ③ 失败 → 回报 Agent 1 重新决策                                 │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  Agent 3: THINK / _react_loop (core/agent.py)                 │
│  temp=0.8, 完整人格 + 情绪 + 记忆                              │
│  接收 summary + context_summary + tool_results                 │
│  ① 组装 system prompt（静态/慢变/动态分层, #160）               │
│  ② 估算 token，动态塞对话到 80%                               │
│  ③ POST DeepSeek API（max_tokens 随情绪调整）                  │
│  ④ 解析响应，检查 <tool_call>（仅 recall/remember/history_search）  │
│  ⑤ 有 tool_call → 执行 → 结果喂回 → 继续 THINK               │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  ACT（无 tool_call）                                          │
│  CLI: 已在 THINK 流式打印，只做存储                             │
│  Web: _send_segments 单条 segment 全量推送(分段暂禁用)        │
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
| SQLite facts_v2 | data/ai_friend.db | 永久 | 用户事实（Layer 1，旧 user_facts 归档表已随 schema v6 物理删除） |
| SQLite experiences | data/ai_friend.db | 永久 | 共享体验 |
| SQLite insights_v2 | data/ai_friend.db | 永久 | 洞察假设（二期替代 reflections） |
| SQLite relationship_metrics | data/ai_friend.db | 永久 | 关系指标 |
| SQLite conversation_turns | data/ai_friend.db | 永久 | 对话历史 |
| SQLite observations | data/ai_friend.db | 永久 | 原始观察（Layer 1 记忆生命周期） |
| EmotionalState | 内存 + personalities/{role_id}.json | 进程 + 持久化 | 当前情绪 |
