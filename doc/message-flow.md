# 消息流转流程

> 从你输入一行字到看见 AI 回复，完整的内部路径。

---

## 状态机总览

```
BOOT ──▶ IDLE ──▶ PERCEIVE ──▶ THINK ──▶ ACT ──▶ REFLECT ──▶ IDLE
(启动)   (等待)    (理解输入+   (调用LLM)  (输出)    (更新状态+   (循环)
                   检索记忆)               │         记忆合并)
                                          │
                                    ┌─────┴──────┐
                                    │ 有 tool_call│
                                    └─────┬──────┘
                                          └──▶ THINK (多轮 ReAct 迭代)
```

---

## 逐步骤详解

### 1. IDLE — 等待输入

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

**数据变更**：无

---

### 2. PERCEIVE — 理解输入

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

### 3. THINK — 调用 LLM

THINK 可能执行多次（ReAct 循环），每次的流程相同：

```
    ┌── 首次调用 ──────────────────────────────┐
    │                                          │
    │ ① build_system_prompt() 拼接 6 个区块    │
    │                                          │
    │    Block 1 — 身份核心                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 你是小星，一个有情感的AI朋友    │   │
    │    │ 你的特质：好奇心90% 温暖85%...   │   │
    │    │ 你的风格：温暖、自然、有点诗意   │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 2 — 当前情绪                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 你感到 满足。                    │   │
    │    │ （情绪积极，平静）               │   │
    │    │ 让这种感觉自然地影响你的语气。   │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 3 — 关系指标                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 信任: 0.3  熟悉度: 0.3           │   │
    │    │ 亲密: 0.3  趣味: 0.3             │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 4 — 长期记忆                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 你知道的关于用户的事:             │   │
    │    │ - 名字：小明                     │   │
    │    │ - 喜欢的摄影类型：街拍           │   │
    │    │                                  │   │
    │    │ 你们的共同回忆：                  │   │
    │    │ - [温暖] 分享宠物趣事            │   │
    │    │                                  │   │
    │    │ 可用工具：                       │   │
    │    │ - recall: 回忆信息               │   │
    │    │ - remember: 记住信息             │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 5 — 最近对话                     │
    │    ┌──────────────────────────────────┐   │
    │    │ 用户：你好                       │   │
    │    │ 你：你好呀！                     │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │    Block 6 — 指令                        │
    │    ┌──────────────────────────────────┐   │
    │    │ 保持对话感，1-3段               │   │
    │    │ 用户有个人信息时用remember       │   │
    │    │ 需要回忆时用recall               │   │
    │    └──────────────────────────────────┘   │
    │                                          │
    │ ② 构建 messages 数组                      │
    │    [system_prompt, 历史对话..., 用户输入]  │
    │    动态塞到 80% 上下文 (~210k tokens)      │
    │    超出阈值 → 压缩后再重试                 │
    │                                          │
    │ ③ POST https://api.deepseek.com/...      │
    │    模型: deepseek-v4-flash                │
    │    thinking: disabled                     │
    │    stream: true                           │
    │                                          │
    │ ④ SSE 流式解析                            │
    │    data: {"choices":[{"delta":{"content":"你"}}]}  │
    │    data: {"choices":[{"delta":{"content":"好"}}]}    │
    │    每收到一个字 → on_token() → 打印到终端  │
    │                                          │
    │ ⑤ parse_tool_calls()                     │
    │    检查回复里有没有 <tool_call>           │
    │    → 有：提取 XML 里的 JSON               │
    │    → 无：cleaned_text 就是最终回复         │
    │                                          │
    └──────────────────────────────────────────┘
```

**有工具调用时的额外流程**：

```
解析出 tool_call:
  {"name": "remember", "arguments": {"category": "identity", "key": "名字", "value": "小明"}}
    │
    ▼
ACT 阶段执行：
    execute_tool_calls(registry, [tool_call])
      → tools/memory_tools.py
      → ltm.store_fact("identity", "名字", "小明", 0.9)
      → SQLite user_facts 表插入
      → 返回 ToolResult("已记住: 名字 = 小明")
    │
    ▼
结果格式化为 <tool_result> 追加到 messages
    │
    ▼
状态 → THINK（继续下一轮 ReAct 迭代）
```

**无工具调用时的路径**：

```
cleaned_text = "你好呀！今天怎么样？"
    │
    └──▶ 这就是最终回复
         状态 → ACT
```

---

### 4. ACT — 输出回复

```
    ┌── 首次回复 ────────────────────────────┐
    │  已经在 THINK 阶段流式打印完了           │
    │  这里只做存储                           │
    ├─────────────────────────────────────────┤
    │  ① ConversationBuffer.add_turn("assistant", "你好呀！")  │
    │  ② repo.insert_turn(turn_count, "assistant", ...)        │
    │     SQLite conversation_turns                            │
    └─────────────────────────────────────────┘
```

**数据变更**：
| 位置 | 写入了什么 |
|------|-----------|
| ConversationBuffer | `{role:"assistant", content:"你好呀！"}` |
| SQLite conversation_turns | AI 回复原文 |

---

### 5. REFLECT — 更新状态

```
    ┌─────────────────────────────────────────┐
    │  ① 情感分析                             │
    │     consolidator.analyze_sentiment("你好") │
    │     → {sentiment: 0.3, personal_sharing: false, topic_energy: 0.5} │
    │                                          │
    │  ② 情绪更新                             │
    │     personality.apply_emotional_shift(0.3, false, 0.5)  │
    │       ├ valence 增加 0.09 (0.4→0.49)    │
    │       ├ arousal 增加 0.05 (0.3→0.35)    │
    │       └ 然后 decay 趋向 baseline         │
    │                                          │
    │  ③ 记忆合并检查（5轮触发一次）           │
    │     should_consolidate() → True?         │
    │       │                                  │
    │       ├── ▶ LLM 抽取 facts               │
    │       │    "从对话中提取用户事实..."      │
    │       │    → FACT|identity|名字|小明|0.9  │
    │       │    → upsert user_facts           │
    │       │                                  │
    │       ├── ▶ LLM 总结体验                 │
    │       │    "将这段对话总结为体验..."      │
    │       │    → SUMMARY: 分享了养宠物的趣事  │
    │       │    → insert experiences          │
    │       │                                  │
    │       ├── ▶ 每 3 次合并生成反思          │
    │       │    "回顾最近的互动产生新洞察..." │
    │       │    → insert reflections          │
    │       │                                  │
    │       └── ▶ 更新关系指标                  │
    │            familiarity += 0.02           │
    │            if sentiment>0.3: trust +=    │
    │            if personal_sharing: intimacy+=│
    │                                          │
    │  ④ 定期保存                             │
    │     每10轮 → personality.save()          │
    │                                          │
    └─────────────────────────────────────────┘
```

**数据变更**：
| 位置 | 写入了什么 |
|------|-----------|
| EmotionalState（内存） | valence 和 arousal 更新 |
| SQLite user_facts | 抽取到的新事实 |
| SQLite experiences | 对话总结体验 |
| SQLite reflections | 反思洞察 |
| SQLite relationship_metrics | trust/familiarity/intimacy 微调 |
| personality.json | 每10轮持久化 |

---

## 完整数据流图

```
你输入 "你好"
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  IDLE                                                        │
│  非阻塞输入线程 → Queue → 出队成功                           │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  PERCEIVE                                                    │
│  ① ConversationBuffer.add("user", "你好")                    │
│  ② SQLite: INSERT conversation_turns                        │
│  ③ MemoryRetriever.retrieve_for_query("你好")                │
│     ├ 读取 SQLite: user_facts                               │
│     ├ 读取 SQLite: experiences                               │
│     ├ 读取 SQLite: reflections                               │
│     └ 读取 SQLite: relationship_metrics                      │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  THINK (第1轮)                                               │
│  ① 组装 system prompt (读 ConversationBuffer + MemoryContext) │
│  ② 估算 token，动态塞最近对话到 80% 阈值                      │
│  ③ POST https://api.deepseek.com/v1/chat/completions        │
│  ④ 流式接收 SSE → 实时打印                                  │
│  ⑤ parse_tool_calls()                                       │
│     ┌── 没有 <tool_call> ─────────────────────┐              │
│     │  cleaned_text = "你好呀！今天怎么样？"   │              │
│     └─────────────────────────────────────────┘              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  ACT                                                         │
│  ① ConversationBuffer.add("assistant", "你好呀！今天怎么样？") │
│  ② SQLite: INSERT conversation_turns                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  REFLECT                                                     │
│  ① 情感分析 → {sentiment: 0.3, ...}                         │
│  ② 情绪更新 → valence 0.4→0.49, arousal 0.3→0.35           │
│  ③ 合并检查 → 不满足条件，跳过                               │
│  ④ 状态 → IDLE                                              │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
                     回到 IDLE，等下一轮输入

================================================================
  有工具调用时的 ReAct 额外路径 (在 THINK→ACT 之间循环):
================================================================

THINK ─── 解析出 <tool_call> ───▶ ACT (执行工具)
  ▲                                │
  │                                ├ tools/traits.py 查找工具
  │                                ├ tools/memory_tools.py 执行
  │                                └ SQLite 写入 user_facts
  │                                │
  │                                ▼
  │                          结果格式化为 <tool_result>
  │                          追加到 messages 数组
  │                                │
  └────────── 状态 → THINK ◀───────┘
```

---

## 关键数据存储一览

| 存储 | 位置 | 生命周期 | 存储内容 |
|------|------|----------|----------|
| ConversationBuffer | 内存 deque | 进程生命周期 | 最近 500 轮对话原文 |
| SQLite conversation_turns | 硬盘 | 永久 | 全部对话历史 |
| SQLite user_facts | 硬盘 | 永久（可归档） | 用户事实（名字、偏好等） |
| SQLite experiences | 硬盘 | 永久（可归档） | 共享体验总结 |
| SQLite reflections | 硬盘 | 永久 | AI 的反思洞察 |
| SQLite relationship_metrics | 硬盘 | 永久 | trust/familiarity/intimacy |
| EmotionalState | 内存 + personality.json | 进程 + 持久化 | 当前情绪 valence/arousal |
| Token 估算 | 动态计算 | 每轮 | 控制上下文不超过 80% |
