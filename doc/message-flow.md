# 消息流转流程

> 从你输入一行字到看见 AI 回复，完整的内部路径。CLI 和 Web 双端分别走不同路径。

---

## 状态机总览

```
BOOT → IDLE → PERCEIVE → THINK → ACT → REFLECT → IDLE
                ↑          │
                │   有 tool_call
                └──── 继续迭代 ←───┘
```

## CLI 路径 vs Web 路径

| 阶段 | CLI | Web |
|------|-----|-----|
| 等待输入 | 守护线程读 stdin → Queue | WebSocket 协程 receive_text() |
| 处理消息 | 状态机 _on_think → _on_act → _on_reflect | process_message() → _react_loop() |
| 输出 | 打字机效果逐字 | 分段推送 + 情绪控制间隔 |
| 主动对话 | IDLE 内轮询 | asyncio.create_task(_proactive_loop) |

---

## 1. IDLE — 等待输入

### CLI 模式

```
守护线程 sys.stdin.readline()
    → 有输入则放入 Queue
    → 主循环非阻塞出队
    → 有输入 → PERCEIVE
    → 无输入 + 空闲 > proactive_min_idle
      → 计算 proactivity 分数
      → 随机命中 → THINK（主动发起）
```

### Web 模式

```
WebSocket 协程
    → await websocket.receive_text()
    → 收到 "message" → process_message()
    → 没有消息时协程挂起，不占用 CPU

后台 _proactive_loop 协程：
    while True:
        if idle > proactive_min_idle:
            score = agent._calculate_proactivity(idle)
            if random.random() < score:
                agent.process_proactive()
        await asyncio.sleep(15)
```

---

## 2. PERCEIVE — 理解输入（仅 CLI）

```
① ConversationBuffer.add_turn("user", 输入)
② repo.insert_turn(SQLite)
③ MemoryRetriever.retrieve_for_query(输入)
   ├ Layer 1: 取全部 active facts
   ├ Layer 2: 评分过滤 → LLM 重排序
   └ Layer 3: 取最新 experiences + reflections
④ 打包 MemoryContext → THINK
```

**Web 模式**：直接走 process_message()，不走 PERCEIVE 状态。

---

## 3. THINK — 调用 LLM

### 首次调用

```
① build_system_prompt() 拼接区块：
   当前时间 → 身份核心 → 情绪状态 → 关系指标
   → 长期记忆 → 工具列表 → 最近对话 + 指令

② 构建 messages 数组
   [system_prompt, 历史对话..., 当前输入]
   动态算 token，塞到 80% 阈值

③ POST https://api.deepseek.com/v1/chat/completions
   model: deepseek-v4-flash
   max_tokens: 随情绪动态变化（兴奋 768 / 平静 512 / 难过 256）

④ SSE 流式解析
   CLI: on_token() → 打印到终端
   Web: on_token() 弃用，改为全量获取 → 后端分段推送

⑤ parse_tool_calls()
   → 有 <tool_call> → ACT 执行工具 → 结果喂回 → 继续 THINK
   → 无 tool_call → cleaned_text 为最终回复
```

### ReAct 多轮迭代

```
THINK → 解析出 <tool_call>
    → ACT: execute_tool_calls(registry, calls)
    → 结果格式化为 <tool_result> 追加到 messages
    → THINK（下一轮，最多 5 次）
    → 无 tool_call 时结束
```

---

## 4. ACT — 输出

### CLI 模式

已在 THINK 阶段流式打印完成，ACT 只做存储。

### Web 模式

```
response = agent.process_message(content)

① _split_segments(response) 按句子拆分
   例: "你好呀！今天怎么样？我这边天气不错。"
   → ["你好呀！", "今天怎么样？", "我这边天气不错。"]

② _calc_delay(emotion, seg_len) 计算每条间隔
   情绪影响基础速度 × 长度因子 × 随机抖动
   excited=1.8s  neutral=4.0s  sad=6.0s

③ 逐条推送 WebSocket
   {"type": "segment", "content": "你好呀！"}  ← 独立气泡
   → sleep(delay) →
   {"type": "segment", "content": "今天怎么样？"}  ← 追加到同气泡
   → sleep(delay) →
   {"type": "segment", "content": "我这边天气不错。"}  ← 追加
   {"type": "done", "emotion": "engaged"}
```

前端收到 `segment` 追加到当前 assistant 消息气泡，收到 `done` 时清理状态。

---

## 5. REFLECT — 更新状态

```
① 情感分析 → {sentiment, personal_sharing, topic_energy}
② 情绪更新 → apply_emotional_shift(dv, da, primary_deltas)
③ 记忆合并检查：
   每 5 轮 / 情感强度 >0.7 / 积累够 10 条
   → LLM 抽取 facts → upsert user_facts
   → LLM 总结体验 → insert experiences
   → 生成反思 → insert reflections
   → 更新关系指标 (familiarity +0.02, etc.)
   → 修剪超量记忆 (facts ≤200, experiences ≤100, reflections ≤50)
④ 每 10 轮保存 personality.json
⑤ 状态 → IDLE
```

---

## 关键数据存储

| 存储 | 位置 | 生命周期 |
|------|------|----------|
| ConversationBuffer | 内存 deque | 进程级别 |
| SQLite conversation_turns | data/ai_friend.db | 永久 |
| SQLite user_facts | data/ai_friend.db | 永久（可归档） |
| SQLite experiences | data/ai_friend.db | 永久（可归档） |
| SQLite reflections | data/ai_friend.db | 永久 |
| SQLite relationship_metrics | data/ai_friend.db | 永久 |
| EmotionalState | 内存 + personality.json | 进程 + 持久化 |
