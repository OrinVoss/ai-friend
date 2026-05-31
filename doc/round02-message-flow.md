# AI Friend 消息处理数据流深度审查报告

> 审查范围：core/message_handler.py、core/dispatcher.py、core/agent.py（_react_loop）
> 关联文件：core/inner_drive.py、core/tool_agent.py、core/context_manager.py、prompts/system.py、memory/short_term.py、web/session.py、web/server.py
> 审查日期：2026-05-31
> 审查轮次：Round 02 — 数据流与状态管理

---

# 概述

本报告对 AI Friend 项目消息处理的数据流进行端到端审查，追踪一条用户消息从输入到输出的完整生命周期。审查聚焦于以下核心问题：

1. **MessageHandler.handle_message 的每一步数据转换是否可靠**
2. **三层 Agent 之间的数据传递格式是否一致**
3. **工具调用结果的格式化与注入流程是否存在信息丢失**
4. **_react_loop 中的消息累积和上下文膨胀风险**
5. **_build_messages 的 token 估算和压缩逻辑是否准确**
6. **数据流中是否存在信息丢失、格式不一致、循环引用等问题**

审查方法：逐文件静态代码分析 + 数据流追踪 + 边界条件推演。

---

## 数据流图（ASCII）

### 图 1：端到端消息流（Web 路径）

```
用户输入 "帮我查一下今天的天气"
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  web/server.py:websocket_endpoint() msg_type="message"                     │
│  web/session.py:WebAgent.process_message()                                 │
│  core/agent.py:Agent.process_message() → MessageHandler.handle_message()   │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  core/message_handler.py:handle_message() 第64-156行                        │
│                                                                             │
│  ① a.short_term.add_turn("user", user_input)           [memory/short_term.py]│
│  ② a.current_input = user_input                                             │
│  ③ a.last_activity_time = time.time()                                       │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Agent 1: InnerDriveAgent.assess()  [core/inner_drive.py:61-111]            │
│                                                                             │
│  输入: user_input + mem_ctx + conv_hist + tools                             │
│  输出: InnerDriveResult {                                                   │
│          needs_external_tools: bool,                                        │
│          reasoning: str,                                                    │
│          tool_requests: list[ToolRequest],                                  │
│          summary: str                                                       │
│        }                                                                    │
│                                                                             │
│  内部循环: recall/remember → execute_tool_calls → 结果追加到 messages       │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ├── needs_external_tools=False ──▶ 直接进入 Agent 3
    │
    └── needs_external_tools=True ──▶ Agent 2
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Agent 2: ToolAgent.run_with_request()  [core/tool_agent.py:142-224]        │
│                                                                             │
│  输入: tool_request (自然语言描述)                                          │
│  输出: ToolAgentResult {                                                    │
│          records: list[ToolCallRecord],                                     │
│          total_calls: int,                                                  │
│          success_count: int,                                                │
│          elapsed_ms: float                                                  │
│        }                                                                    │
│                                                                             │
│  内部循环: max_retries=3, 失败则重建 messages 重新请求                      │
│  每轮: provider.generate() → parse_tool_calls() → execute_tool_calls()    │
│        → _format_raw_results() → 追加到 messages                            │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Agent 1 Review / Re-decide  [core/message_handler.py:98-141]               │
│                                                                             │
│  成功 → inner_drive.review(combined_records) → 判断是否还需更多工具         │
│  失败 → inner_drive.re_decide(failure_log) → 调整策略                       │
│  最多 MAX_AGENT2_ROUNDS=3 轮                                                │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  合并所有轮次结果  [core/message_handler.py:144-153]                        │
│                                                                             │
│  tool_records = "\n".join(format_for_phase2(r) for r in all_tool_results)  │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Agent 3: _run_agent3()  [core/message_handler.py:243-272]                  │
│                                                                             │
│  ① mem_ctx = a.retriever.retrieve_for_query(user_input)                    │
│  ② a.ltm.repo.insert_turn_sync(turn_count, "user", ...)                    │
│  ③ conv_hist = a.short_term.format_for_prompt(max_chars=3000)              │
│  ④ tool_records = _tool_agent.format_for_phase2(tool_result)               │
│  ⑤ sys_prompt = build_system_prompt(...)                                   │
│  ⑥ messages = _build_messages(sys_prompt, user_input)                      │
│  ⑦ if tool_records: messages.insert(-1, {"role":"user","content":...})     │
│  ⑧ phase2_registry = _make_internal_registry() (仅 recall/remember)        │
│  ⑨ a._react_loop(messages, on_token, add_to_history=True, ...)             │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  core/agent.py:_react_loop() 第119-181行                                    │
│                                                                             │
│  for _idx in range(self._max_tool_iterations):  # 默认10次                  │
│      resp = provider.generate(messages, stream=(_idx==0), ...)             │
│      cleaned, calls = parse_tool_calls(resp)                                │
│      if not calls:                                                          │
│          if contains_fake_action(resp) and not tools_were_called:           │
│              → 追加纠错消息，continue                                         │
│          final_text = cleaned; break                                        │
│      tools_were_called = True                                               │
│      messages.append({"role":"assistant","content":resp})                   │
│      results = execute_tool_calls(registry, calls)                          │
│      → _tool_call_history.append(...)                                       │
│      messages.append({"role":"user","content":format_tool_results(results)})│
│                                                                             │
│  if final_text:                                                             │
│      if add_to_history: short_term.add_turn("assistant", final_text)       │
│      ltm.repo.insert_turn_sync(turn_count, "assistant", ...)               │
│      turn_count += 1                                                        │
│  _process_emotion()                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Web 输出: web/server.py:_send_segments()                                   │
│  CLI 输出: 已在 _react_loop 第0轮流式打印                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 图 2：三层 Agent 数据格式传递图

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Agent 1       │     │   Agent 2       │     │   Agent 3       │
│  InnerDrive     │────▶│  ToolAgent      │────▶│  Roleplay       │
│                 │     │                 │     │                 │
│ 输出格式:        │     │ 输入格式:        │     │ 输入格式:        │
│ InnerDriveResult│     │ 自然语言字符串   │     │ messages[]      │
│ {               │     │ (ToolRequest.   │     │ [{role,content}]│
│   needs_external│     │  description)   │     │                 │
│   reasoning     │     │                 │     │ 包含:            │
│   tool_requests │     │ 输出格式:        │     │ - system prompt │
│   summary       │     │ ToolAgentResult │     │ - 历史对话      │
│ }               │     │ {               │     │ - user_input    │
│                 │     │   records[]     │     │ - tool_records  │
│ ToolRequest {   │     │   total_calls   │     │                 │
│   description   │     │   success_count │     │ 输出格式:        │
│   suggested_tool│     │   elapsed_ms    │     │ 自然语言字符串  │
│   params_hint   │     │ }               │     │ (final_text)    │
│ }               │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                              │
         │                                              │
         └────────────── 直接传递 ──────────────────────▶
              (summary 注入 system prompt)
```

### 图 3：_react_loop 消息累积示意图

```
初始 messages (M0):
  [system, user1, assistant1, user2, ..., user_current]

迭代 1 (LLM 输出 tool_call):
  M0 + [assistant: "<tool_call>...</tool_call>"]
     + [user: "<tool_result>...</tool_result>"]

迭代 2 (LLM 再次输出 tool_call):
  M1 + [assistant: "<tool_call>...</tool_call>"]
     + [user: "<tool_result>...</tool_result>"]

迭代 N:
  M0 + N×(assistant_msg + user_msg)

每轮增加 ~2 条消息，10 轮最多 +20 条
每条 tool_result 可能包含数千字输出
```

### 图 4：_build_messages Token 估算与压缩决策

```
_build_messages(sys_prompt, user_input)
    │
    ├── messages = [{role:"system", content:sys_prompt}]
    │
    ├── for t in short_term.get_all_reversed():        ← 从新到旧遍历
    │       role = "assistant" if t.role=="assistant" else "user"
    │       if estimate_tokens(最近5条非system消息[:200]) + estimate_tokens(t.content) > 144000:
    │           overflow = True; break
    │       messages.insert(1, {role, content:t.content})  ← 插入到 system 之后
    │
    ├── if overflow and compressed_summary:
    │       messages.insert(1, {role:"system", content:"[对话历史摘要] "+summary})
    │
    ├── if user_input:
    │       msg_tokens = sum(estimate_tokens(m.content[:500]) for m in messages if role!="system")
    │       if msg_tokens + estimate_tokens(user_input) > 144000:
    │           context.compress(messages)
    │       messages.append({role:"user", content:user_input})
    │
    └── return messages
```

---

## 详细发现

### 发现 1：CLI 与 Web 双路径数据流不一致（严重程度：高）

**位置：**
- `core/cli_controller.py` 第 60-295 行（CLI 路径）
- `core/message_handler.py` 第 64-291 行（Web 路径）
- `core/agent.py` 第 104-111 行（入口委托）

**问题描述：**

CLI 和 Web 两条路径的消息处理逻辑存在显著差异，导致相同输入可能产生不同行为。

**CLI 路径（状态机）：**
```
_on_perceive() → _on_think() → _on_act() → _on_reflect()
```

在 `_on_perceive`（第 118-135 行）：
- 先调用 `a.short_term.add_turn("user", user_input)`
- 再调用 `a.retriever.retrieve_for_query(user_input)`
- 再调用 `a.ltm.repo.insert_turn_sync(...)`
- 然后执行 Agent 1 `inner_drive.assess()`

在 `_on_think`（第 137-236 行）：
- Agent 2 仅执行 **单轮** `run_with_request()`，无循环
- 无 Agent 1 review/re-decide 机制
- `_tool_records` 直接注入 messages

**Web 路径（MessageHandler）：**
```
handle_message() → Agent 1 → [Agent 2 循环 3 轮] → Agent 3
```

在 `handle_message`（第 64-156 行）：
- 先调用 `a.short_term.add_turn("user", user_input)`
- 然后执行 Agent 1 `inner_drive.assess()`
- Agent 2 有 **多轮循环**（最多 3 轮），支持 Agent 1 review
- `_run_agent3` 中再次调用 `a.retriever.retrieve_for_query(user_input)`（第 249 行）
- 再次调用 `a.ltm.repo.insert_turn_sync(...)`（第 251-252 行）

**关键差异：**

| 行为 | CLI | Web |
|------|-----|-----|
| Agent 2 轮次 | 单轮 | 最多 3 轮 + review |
| 记忆检索次数 | 1 次（PERCEIVE） | 2 次（Agent 1 + Agent 3） |
| SQLite 写入次数 | 1 次（PERCEIVE） | 2 次（handle_message + _run_agent3） |
| 失败重试策略 | 无 | 有（re_decide） |
| tool_registry 过滤 | 有（_make_internal_registry） | 有 |

**风险分析：**

1. **重复 SQLite 写入**：Web 路径中同一条用户消息被写入 `conversation_turns` 两次（第 75 行附近的 short_term.add_turn 触发隐式写入 + 第 251 行显式 insert_turn_sync）。实际上 short_term.add_turn 并不触发 SQLite 写入，但 _run_agent3 中的 insert_turn_sync 与 handle_message 开头没有协调，导致同一 turn_count 可能被重复记录。

2. **检索开销翻倍**：Web 路径中 `retrieve_for_query` 被调用两次（Agent 1 一次、Agent 3 一次），增加了延迟和 API 成本。

3. **行为不一致**：CLI 用户无法享受 Agent 2 的多轮工具执行能力，某些需要搜索→获取→再搜索的复杂查询在 CLI 下会失败。

**建议：**
- 统一两条路径的核心逻辑，将 CLI 的 `_on_think` 重构为调用 `MessageHandler.handle_message`
- 或至少将 Agent 2 的多轮循环逻辑提取为共享函数
- 移除 Web 路径中 _run_agent3 的重复 `insert_turn_sync`，改为在 handle_message 入口处统一写入

---

### 发现 2：Agent 1 → Agent 2 数据传递存在信息丢失（严重程度：高）

**位置：**
- `core/message_handler.py` 第 100 行
- `core/inner_drive.py` 第 23-37 行
- `core/tool_agent.py` 第 142-224 行

**问题描述：**

Agent 1 输出 `InnerDriveResult` 包含丰富的结构化信息（`reasoning`、`tool_requests`、`summary`、`params_hint`），但传递给 Agent 2 时仅使用了 `tool_requests[0].description`：

```python
# core/message_handler.py:100
request_text = drive_result.tool_requests[0].description if drive_result.tool_requests else user_input
```

**丢失的信息：**
1. `suggested_tool` — Agent 1 推荐的工具类型被忽略
2. `params_hint` — Agent 1 提取的参数（如 URL、搜索关键词）被忽略
3. `reasoning` — Agent 1 的推理过程未被传递给 Agent 2
4. 多个 `tool_requests` — 仅使用第一个请求，其余被丢弃

**后果：**
- Agent 2 需要重新解析自然语言描述来推断工具名和参数
- 如果 Agent 1 明确建议 `web_fetch` 并提供了 `params_hint={"url": "..."}`，Agent 2 完全不知道这些信息
- 多工具并行请求被串行化（只取第一个）

**代码证据：**

```python
# core/tool_agent.py:162-166
messages = [
    {"role": "system", "content": sys_prompt},
    {"role": "user", "content": (
        f"Agent 1 的内驱推理请求：\n{tool_request}\n\n"
        "请根据以上请求，输出 JSON 格式的工具调用。"
    )},
]
```

Agent 2 看到的只是自然语言字符串，没有任何结构化提示。

**建议：**
- 将 `ToolRequest` 的完整字段传递给 Agent 2：
  ```python
  tool_request_enriched = {
      "description": req.description,
      "suggested_tool": req.suggested_tool,
      "params_hint": req.params_hint,
      "reasoning": drive_result.reasoning,
  }
  ```
- 在 Agent 2 的 prompt 中注入这些结构化信息
- 支持多个 tool_requests 的批量处理

---

### 发现 3：_react_loop 消息累积导致上下文爆炸（严重程度：高）

**位置：**
- `core/agent.py` 第 119-181 行

**问题描述：**

`_react_loop` 是 Agent 3 的核心推理循环，在每次迭代中将 LLM 的完整响应和工具结果追加到 `messages` 列表中：

```python
# core/agent.py:159-170
messages.append({"role": "assistant", "content": resp})
results = execute_tool_calls(registry, calls)
# ...
messages.append({"role": "user", "content": format_tool_results(results)})
```

**累积效应分析：**

假设一次典型的 ReAct 流程：
- 初始 messages：system prompt (~3000 tokens) + 10 轮历史 (~4000 tokens) = ~7000 tokens
- 每轮 ReAct 增加：
  - assistant 消息：LLM 输出含 tool_call (~200 tokens)
  - user 消息：tool_result 可能非常大
    - web_fetch 返回网页全文：可能 3000-8000 tokens
    - web_search 返回 10 条结果：可能 2000-4000 tokens
    - read_file 返回文件内容：可能 1000-10000 tokens

最坏情况下，10 轮迭代后：
```
7000 + 10 × (200 + 8000) = 7000 + 82000 = 89,000 tokens
```

这已超过 180K 上下文窗口的 50%，如果初始历史更大，很容易触及 144K 压缩阈值。

**更严重的问题：**

`_react_loop` 内部没有任何 token 估算或压缩机制。`COMPRESS_THRESHOLD` 仅在 `_build_messages` 中检查一次（构建初始 messages 时），一旦进入 `_react_loop`，消息列表只会单向增长。

**流式输出与迭代的矛盾：**

```python
# core/agent.py:129-133
resp = self.provider.generate(
    messages, stream=False if _idx > 0 else True,
    on_token=on_token if _idx == 0 else None,
    max_tokens=max_tok if _idx == 0 else max(384, max_tok * 2 // 3),
)
```

- 第 0 轮：stream=True，用户能看到打字机效果
- 第 1+ 轮：stream=False，用户看不到任何中间思考过程
- 如果 ReAct 迭代多轮，用户会经历明显的"卡顿"

**建议：**
1. 在 `_react_loop` 每轮迭代前检查消息总 token 数，超过阈值时进行截断或压缩
2. 对 tool_result 设置上限（如每轮最多保留 2000 tokens 的工具结果摘要）
3. 考虑将早期的 ReAct 轮次摘要化后替换原始消息
4. 为非第 0 轮也提供某种进度反馈（如"思考中..."）

---

### 发现 4：_build_messages Token 估算逻辑存在多处缺陷（严重程度：高）

**位置：**
- `core/message_handler.py` 第 274-291 行
- `core/context_manager.py` 第 27-35 行

**问题 4a：循环条件估算对象错误**

```python
# core/message_handler.py:280
if estimate_tokens(" ".join(m["content"][:200] for m in messages[-5:] if m["role"] != "system")) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
    overflow = True
    break
```

这里估算的是 `messages[-5:]`（最近已处理的 5 条消息）的 token 数加上当前遍历的 `t.content`。但 `messages` 列表在循环中是从头开始构建的，初始只有 system 消息，所以 `messages[-5:]` 在循环早期几乎总是只有 1 条消息。这导致：

- 早期循环：估算值很小，大量历史消息被插入
- 后期循环：估算值突然跳变，可能提前 break
- 从未真正准确估算整个消息列表的 token 数

**问题 4b：字符截断导致 token 估算失真**

```python
estimate_tokens(m["content"][:200] for m in messages[-5:])
```

只取前 200 个字符估算，但一条消息可能有 3000 字符，截断后的估算严重偏低。

**问题 4c：CJK 字符估算公式粗糙**

```python
# core/context_manager.py:31-35
cjk = sum(1 for c in text if '一' <= c <= '鿿' or '　' <= c <= '〿')
ascii_chars = sum(1 for c in text if c.isascii() and c.isalpha())
digits = sum(1 for c in text if c.isdigit())
other = len(text) - cjk - ascii_chars - digits
return max(1, int(cjk / 1.5 + ascii_chars / 4 + digits / 3 + other / 8))
```

- 未包含韩文、日文、阿拉伯文等字符范围
- `other / 8` 的假设对 emoji、特殊符号等不准确
- 当 tiktoken 不可用时，估算误差可能达 30-50%

**问题 4d：user_input 的 token 检查重复计算**

```python
# core/message_handler.py:287-290
msg_tokens = sum(estimate_tokens(m["content"][:500]) for m in messages if m["role"] != "system")
if msg_tokens + estimate_tokens(user_input) > COMPRESS_THRESHOLD:
    a._context.compress(messages)
messages.append({"role": "user", "content": user_input})
```

这里又截断到 500 字符估算，且 `compress()` 会调用 LLM 生成摘要，然后 `short_term.clear()`，但此时 `messages` 列表中已包含所有历史消息。压缩后这些历史消息仍留在 `messages` 中，只是追加了一个摘要 system 消息。

**实际行为：**
```python
# core/context_manager.py:72-96
def _do_compress(self, messages):
    # 提取非 system 消息，截断到 500 字符
    # 生成摘要
    self._compressed_summary = result.strip()
    self._estimated_tokens_used = 0
    self._short_term.clear()  # 清空短期记忆
```

压缩后 `messages` 列表没有清理，仍然包含所有历史消息。下次 `_build_messages` 被调用时，会从 `short_term`（已清空）重新构建，但当前这次调用的 `messages` 仍然是膨胀的。

**建议：**
1. 重写 token 估算逻辑，使用完整消息内容而非截断版本
2. 在 `_build_messages` 中维护一个 running total，避免重复估算
3. 压缩后应重建 messages 列表，只保留 system + 摘要 + 当前输入
4. 考虑使用 tiktoken 作为必需依赖，移除粗糙的 fallback 估算

---

### 发现 5：工具调用结果格式化存在双重标准（严重程度：中）

**位置：**
- `core/dispatcher.py` 第 153-169 行
- `core/tool_agent.py` 第 226-249 行
- `core/tool_agent.py` 第 252-258 行

**问题描述：**

Agent 2 内部循环和 Agent 3 注入使用不同的结果格式化函数：

**Agent 2 内部使用（_format_raw_results）：**
```python
# core/tool_agent.py:252-258
def _format_raw_results(results: list[dict]) -> str:
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        parts.append(f"工具 {r['name']} 执行{tag}:\n{r['output']}")
    return "\n\n".join(parts)
```

**Agent 2 → Agent 3 传递使用（format_for_phase2）：**
```python
# core/tool_agent.py:226-249
def format_for_phase2(self, result: ToolAgentResult) -> str:
    parts = [
        "=== 系统已获取的真实数据（你只能基于这些数据回复，不得编造任何内容） ===",
        f"共执行 {result.total_calls} 个工具...",
        # ...
    ]
    for i, r in enumerate(result.records, 1):
        parts.append(f"[工具 {i}] {r.name}（{status}，{entry_count} 条结果）:\n{r.output[:6000]}\n")
    # ...
```

**Agent 3 ReAct 循环使用（format_tool_results）：**
```python
# core/dispatcher.py:153-169
def format_tool_results(results: list[dict]) -> str:
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        parts.append(
            f'<tool_result name="{r["name"]}">\n'
            f"工具 {r['name']} 执行{tag}:\n"
            f"{r['output']}\n"
            f"</tool_result>"
        )
    parts.append("=== 铁律 ===\n以上是工具返回的真实内容...")
    return "\n".join(parts)
```

**问题：**

1. **三种不同格式**：Agent 2 内部、Agent 2→Agent 3、Agent 3 ReAct 分别使用三种不同的格式，LLM 需要理解多种格式
2. **截断不一致**：`format_for_phase2` 截断到 6000 字符，`format_tool_results` 不截断
3. **约束提示不一致**：`format_for_phase2` 说"只能基于这些数据回复"，`format_tool_results` 说"必须逐字如实汇报"
4. **XML 标签不一致**：Agent 3 使用 `<tool_result>` 标签，Agent 2 不使用

**建议：**
- 统一工具结果格式，定义一个标准的 `ToolResultFormatter` 类
- 所有路径使用相同的格式模板
- 截断策略统一配置（如每工具最多 3000 tokens）

---

### 发现 6：Agent 1 的 review 和 re_decide 存在消息累积问题（严重程度：中）

**位置：**
- `core/inner_drive.py` 第 154-264 行
- `core/message_handler.py` 第 98-141 行

**问题描述：**

Agent 1 的 `review()` 和 `re_decide()` 方法每次都重建 `messages`：

```python
# core/inner_drive.py:172-195
mem_ctx = self._retriever.retrieve_for_query(user_input)
conv_hist = self._short_term.format_for_prompt(max_chars=2000)
sys_prompt = build_inner_drive_prompt(...)
messages = [
    {"role": "system", "content": sys_prompt},
    {"role": "user", "content": review_msg},
]
```

但 `review_msg` 包含了 `tool_records_text[:3000]`，在多轮 Agent 2 执行后，`combined_records` 可能非常长：

```python
# core/message_handler.py:121-123
combined_records = ""
for i, r in enumerate(all_tool_results):
    combined_records += self._tool_agent.format_for_phase2(r) + "\n"
```

如果每轮 Agent 2 返回 6000 字符（截断后），3 轮就是 18000 字符，加上 system prompt 和 conversation history，很容易超过 token 限制。

**更严重的问题：**

`review()` 方法中如果 LLM 输出了 tool_call（recall/remember），会执行这些内部工具并追加结果：

```python
# core/inner_drive.py:202-208
if calls:
    messages.append({"role": "assistant", "content": resp})
    results = execute_tool_calls(self._full_registry, calls)
    result_text = self._format_internal_results(results)
    messages.append({"role": "user", "content": result_text})
    resp = self._provider.generate(messages, stream=False, max_tokens=512)
```

这里追加了两条消息后再次调用 LLM，但没有检查 messages 长度。如果 review 被调用多次（多轮 Agent 2），messages 会持续累积。

**建议：**
1. 对 `combined_records` 设置总长度上限（如 6000 字符）
2. 在 `review()` 和 `re_decide()` 中对 messages 做长度检查
3. 考虑只传递最近一轮的结果给 Agent 1 review，而非全部累积结果

---

### 发现 7：tool_result 注入位置导致 system prompt 被挤到末尾（严重程度：中）

**位置：**
- `core/message_handler.py` 第 266-269 行
- `core/cli_controller.py` 第 179-181 行

**问题描述：**

工具结果被注入为 `user` 消息，且插入位置在 `messages[-1]` 之前：

```python
# core/message_handler.py:266-269
messages = self._build_messages(sys_prompt, user_input=f"用户输入：{user_input}")
if tool_records:
    messages.insert(-1, {"role": "user", "content": tool_records})
```

假设 `_build_messages` 返回：
```python
[
    {"role": "system", "content": sys_prompt},
    {"role": "user", "content": "历史消息1"},
    {"role": "assistant", "content": "历史回复1"},
    # ...
    {"role": "user", "content": "用户输入：xxx"}  # 最后一条
]
```

`insert(-1, ...)` 将 tool_records 插入到倒数第二条位置，即：
```python
[
    {"role": "system", ...},
    {"role": "user", "content": "历史消息1"},
    # ...
    {"role": "user", "content": tool_records},      # 插入到这里
    {"role": "user", "content": "用户输入：xxx"}     # 最后一条
]
```

**问题：**

1. 工具结果和用户输入成为两条独立的 user 消息，LLM 可能混淆哪个是"当前问题"
2. 如果历史消息很多，工具结果可能被推到远离 system prompt 的位置
3. 某些模型对消息位置敏感，system prompt 后的第一条 user 消息权重最高

**建议：**
- 将 tool_records 和用户输入合并为一条 user 消息：
  ```python
  combined_user = f"{user_input}\n\n{tool_records}"
  messages.append({"role": "user", "content": combined_user})
  ```
- 或确保 tool_records 紧跟在 system prompt 之后

---

### 发现 8：_react_loop 中 fake action 检测存在逻辑漏洞（严重程度：中）

**位置：**
- `core/agent.py` 第 136-155 行
- `core/dispatcher.py` 第 172-194 行

**问题描述：**

```python
# core/agent.py:139-155
if contains_fake_action(resp) and fake_action_count < 3 and not tools_were_called:
    fake_action_count += 1
    logger.warning(f"[react] fake tool action detected (attempt {fake_action_count}/3)")
    messages.append({"role": "assistant", "content": resp})
    messages.append({"role": "user", "content": "YOU DID NOT ACTUALLY CALL ANY TOOLS! ..."})
    continue
```

**漏洞 1：语言不匹配**

`contains_fake_action` 检测中文关键词（"已发送"、"已通知"、"调用web_fetch"等），但纠错消息是英文。如果 LLM 用中文"编造"工具结果，它收到的纠错消息是英文，可能不理解。

**漏洞 2：检测关键词过于宽泛**

```python
# core/dispatcher.py:179
completion_keywords = ["已发送", "已通知", "已经为你", "已经为您", "已为您", "已记住", "已回忆"]
```

用户正常输入中可能包含这些词（如"我已经为你准备好了"），但这里检测的是 LLM 输出，不是用户输入。不过如果用户引用了之前的对话，这些词可能出现在上下文中。

**漏洞 3：tools_were_called 标志不可靠**

```python
# core/agent.py:126
tools_were_called = False
# ...
if not calls:
    # ...
    if contains_fake_action(resp) and ... and not tools_were_called:
        # ...
    final_text = cleaned
    break
tools_were_called = True  # 第158行，在循环末尾设置
```

如果某轮 LLM 输出了 tool_call 但 `parse_tool_calls` 解析失败（返回空 calls），`tools_were_called` 不会被设置。后续轮次如果 LLM 用中文描述工具结果，`contains_fake_action` 可能误触发。

**建议：**
1. 将纠错消息改为中文，与检测语言一致
2. 细化检测逻辑，排除引用上下文的情况
3. 考虑使用更精确的检测方式，如检查是否同时包含工具名和"已"字

---

### 发现 9：handle_proactive 和 handle_explore 缺少错误处理（严重程度：中）

**位置：**
- `core/message_handler.py` 第 158-241 行

**问题描述：**

```python
# core/message_handler.py:158-188
def handle_proactive(self, on_token=None, intent=None) -> str:
    # ...
    sys_prompt = build_system_prompt(...)
    messages = self._build_messages(sys_prompt, user_input=f"[主动开启对话] 主题方向：{topic}")
    # ...
    return a._react_loop(messages, on_token, add_to_history=False)
```

```python
# core/message_handler.py:189-241
def handle_explore(self, intent=None) -> str | None:
    # ...
    tool_result = self._tool_agent.run(explore_prompt)
    # ...
    result = a._react_loop(messages, on_token=None, add_to_history=False,
                          tool_registry=phase2_registry)
    if result and len(result.strip()) > 30 and not result.startswith("搜索"):
        return result
    return None
```

**问题：**

1. `handle_proactive` 和 `handle_explore` 都没有 try-except 块，如果 LLM API 调用失败（ConnectionError、Timeout 等），异常会直接抛出到上层
2. Web 路径中这些调用在 `run_in_executor` 中执行，异常会被包装为 `concurrent.futures.CancelledError` 或其他异常，可能导致 proactive 循环崩溃
3. `handle_explore` 中 `tool_result` 可能为 None 或空，但直接调用了 `format_for_phase2` 和 `has_results` 检查，虽然不会崩溃，但逻辑路径不清晰

**建议：**
1. 为 `handle_proactive` 和 `handle_explore` 添加异常捕获，返回空字符串或 None
2. 在 Web 的 `_proactive_loop` 中增加更细粒度的异常处理
3. 记录 proactive 失败的日志，便于调试

---

### 发现 10：Web 路径中 emotion 事件记录缺失（严重程度：中）

**位置：**
- `web/server.py` 第 39-54 行
- `web/server.py` 第 199-249 行

**问题描述：**

根据 CLAUDE.md 项目规则：
> Web 端每次请求结束时调用 `record_emotion_event()` 记录强情绪

但审查发现：

1. `chat_api`（REST 端点）和 `websocket_endpoint`（WebSocket）都没有在请求结束时调用 `record_emotion_event()`
2. `_process_emotion()` 在 `_react_loop` 中被调用，但 `record_emotion_event()` 只在情绪强度 > 0.6 时记录，不是"每次请求"
3. Web 路径的 emotion 记录完全依赖 `_react_loop` 末尾的 `_process_emotion()`，而 `_process_emotion()` 中的 `record_emotion_event()` 有强度阈值过滤

**代码证据：**

```python
# models/personality.py:239-262
def record_emotion_event(self, trigger: str, context: str = "") -> None:
    primary_intensity = max(self.anger, self.sadness, self.joy, ...)
    if primary_intensity < 0.6:
        logger.debug(f"[emotion] event_skip: intensity={primary_intensity:.2f} < 0.6")
        return
    # ... 记录事件
```

这意味着弱情绪事件不会被记录，与项目规则要求的"每次请求结束时记录"不符。

**建议：**
1. 在 Web 端请求处理完毕后显式调用 `record_emotion_event()`
2. 降低记录阈值或分两级记录（强情绪详细记录、弱情绪简单记录）
3. 在 `web/server.py` 的 `_send_segments` 完成后添加记录逻辑

---

### 发现 11：ToolRegistry.to_json_schema() 返回无效 schema（严重程度：高）

**位置：**
- `tools/traits.py` 第 82-95 行

**问题描述：**

```python
# tools/traits.py:82-95
def to_json_schema(self, names: list[str] | None = None) -> dict:
    tool_names = []
    for spec in self.list_specs():
        if names is not None and spec.name not in names:
            continue
        tool_names.append(spec.name)

    return {
        "type": "json_object",
    }
```

**问题：**

1. 函数收集了 `tool_names` 列表但完全没有使用
2. 返回的 schema 只有 `{"type": "json_object"}`，没有定义任何结构
3. DeepSeek 的 `json_object` 模式要求模型输出有效 JSON，但没有 schema 约束时，模型可能输出任意 JSON 结构
4. Agent 2 期望的格式是 `{"calls": [{"name": ..., "arguments": ...}]}`，但 schema 没有约束这个结构

**后果：**
- LLM 可能输出不符合预期的 JSON 格式
- `parse_tool_calls` 的 Tier 1 解析依赖 `"calls"` 数组，如果模型输出其他格式会回退到 Tier 2/3
- 增加了解析失败率和重试次数

**建议：**
- 返回完整的 JSON Schema：
  ```python
  return {
      "type": "json_object",
      "schema": {
          "type": "object",
          "properties": {
              "calls": {
                  "type": "array",
                  "items": {
                      "type": "object",
                      "properties": {
                          "name": {"type": "string"},
                          "arguments": {"type": "object"}
                      },
                      "required": ["name", "arguments"]
                  }
              }
          },
          "required": ["calls"]
      }
  }
  ```

---

### 发现 12：short_term 历史消息插入顺序错误（严重程度：中）

**位置：**
- `core/message_handler.py` 第 278-283 行
- `core/cli_controller.py` 第 171-178 行

**问题描述：**

```python
# core/message_handler.py:278-283
for t in a.short_term.get_all_reversed():
    role = "assistant" if t.role == "assistant" else "user"
    if estimate_tokens(...) > COMPRESS_THRESHOLD:
        overflow = True
        break
    messages.insert(1, {"role": role, "content": t.content})
```

`get_all_reversed()` 返回从新到旧的消息。每次 `insert(1, ...)` 将消息插入到 system prompt 之后。这意味着：

- 第一条插入的是最新的消息
- 最后一条插入的是最旧的消息
- 最终顺序：system, 最旧, ..., 最新

这是正确的对话顺序，但实现方式效率低下（每次 insert(1) 需要 O(n) 移动元素）。

**CLI 路径的问题：**

```python
# core/cli_controller.py:171-178
for t in a.short_term.get_all_reversed():
    role = "assistant" if t.role == "assistant" else "user"
    msg_tokens = estimate_tokens(t.content)
    if a._context.estimated_tokens + msg_tokens > COMPRESS_THRESHOLD:
        break
    messages.append({"role": role, "content": t.content})
    a._context.add_estimate(msg_tokens)
messages = [messages[0]] + list(reversed(messages[1:]))
```

CLI 路径先 append 再 reverse，效率稍好，但两条路径实现不一致。

**建议：**
- 统一使用 `get_all()`（正序）然后直接 append
- 或优化为批量构建后一次性插入

---

### 发现 13：Agent 3 ReAct 循环中 max_tokens 动态调整不合理（严重程度：低）

**位置：**
- `core/agent.py` 第 129-133 行

**问题描述：**

```python
resp = self.provider.generate(
    messages, stream=False if _idx > 0 else True,
    on_token=on_token if _idx == 0 else None,
    max_tokens=max_tok if _idx == 0 else max(384, max_tok * 2 // 3),
)
```

- 第 0 轮：`max_tokens = max_tok`（情绪相关，256-768）
- 第 1+ 轮：`max_tokens = max(384, max_tok * 2 // 3)`

如果情绪是 sad（max_tok=256），第 1+ 轮：`max(384, 256*2//3) = max(384, 170) = 384`。

这意味着后续 ReAct 轮次反而比第 0 轮有更多 token，与直觉相反（后续轮次通常是工具调用，不需要长输出）。

**建议：**
- 后续轮次固定使用较小的 max_tokens（如 512）
- 或根据调用类型动态调整（tool_call 轮次用 512，最终回复用 max_tok）

---

### 发现 14：execute_tool_calls 中异步工具执行存在线程安全问题（严重程度：中）

**位置：**
- `core/dispatcher.py` 第 109-150 行

**问题描述：**

```python
# core/dispatcher.py:128-134
import asyncio
try:
    import inspect
    if inspect.iscoroutinefunction(tool.execute):
        result: ToolResult = asyncio.run(tool.execute(args))
    else:
        result: ToolResult = tool.execute(args)
```

**问题：**

1. 在已经存在事件循环的环境中（如 Web 端的 asyncio 环境），`asyncio.run()` 会抛出 `RuntimeError`
2. 每次调用都重新 `import asyncio` 和 `import inspect`，效率低下
3. 如果多个工具同时是异步的，串行执行 `asyncio.run()` 效率低

**建议：**
1. 将 import 移到模块顶部
2. 检测当前是否有事件循环，使用 `asyncio.get_event_loop().run_until_complete()` 或 `await`
3. 考虑并行执行多个异步工具

---

### 发现 15：handle_message 中 tool_result 变量在 Agent 3 调用时可能为 None（严重程度：低）

**位置：**
- `core/message_handler.py` 第 156 行

**问题描述：**

```python
# core/message_handler.py:155-156
# ── Agent 3: Emotional expression ──
return self._run_agent3(user_input, drive_result, tool_result, on_token=on_token)
```

`tool_result` 是在 Agent 2 循环内部定义的：
```python
# core/message_handler.py:105
tool_result = self._tool_agent.run_with_request(request_text)
```

如果 Agent 1 判断 `needs_external_tools=True` 但 Agent 2 循环因某种原因没有执行（如 `_tool_agent` 初始化失败），`tool_result` 可能未定义。

实际上 Python 会在这种情况下抛出 `UnboundLocalError`。

**建议：**
- 在函数开头初始化 `tool_result = None`
- 或在 Agent 2 循环前添加保护逻辑

---

### 发现 16：WebAgent.process_message 中 personality.save() 的调用位置（严重程度：低）

**位置：**
- `web/session.py` 第 84-89 行

**问题描述：**

```python
# web/session.py:84-89
def process_message(self, user_input: str) -> str:
    result = self.agent.process_message(
        user_input, on_token=self._on_token_callback,
    )
    self.personality.save(self.config.personality_file)
    return result
```

`personality.save()` 在每次消息处理后都同步写入磁盘。在高并发场景下：
1. 多个请求同时写入同一文件可能导致数据损坏
2. 同步 I/O 阻塞事件循环

**建议：**
1. 将 `personality.save()` 改为异步或批量保存
2. 使用文件锁保护并发写入
3. 或降低保存频率（如每 N 轮或定时保存）

---

### 发现 17：_react_loop 中 add_to_history=False 时仍增加 turn_count（严重程度：低）

**位置：**
- `core/agent.py` 第 172-177 行

**问题描述：**

```python
# core/agent.py:172-177
if final_text:
    if add_to_history:
        self.short_term.add_turn("assistant", final_text)
    self.ltm.repo.insert_turn_sync(self.turn_count, "assistant", final_text,
                              str(self.personality.emotion.to_dict()))
    self.turn_count += 1
```

当 `add_to_history=False`（如 proactive 和 explore 模式）：
- 不加入短期记忆（正确）
- 但仍写入 SQLite（`insert_turn_sync`）
- 仍增加 `turn_count`

这意味着 proactive 消息会占用 turn_count，但 short_term 中没有对应记录，导致 turn_count 和 short_term 长度不一致。

**建议：**
- 当 `add_to_history=False` 时，考虑是否也跳过 SQLite 写入和 turn_count 增加
- 或至少记录这种不一致的原因

---

### 发现 18：contains_fake_action 对"工具返回"的检测过于严格（严重程度：低）

**位置：**
- `core/dispatcher.py` 第 172-194 行

**问题描述：**

```python
narrative_patterns = [
    "调用web_fetch", "调用read_file", ...,
    "工具返回", "工具返回的原始内容",
    ...
]
```

如果 Agent 3 在 ReAct 循环中正确调用了工具，然后收到工具结果，下一轮 LLM 说"根据工具返回的内容..."，这会被 `contains_fake_action` 标记为 fake action（如果 `tools_were_called=False`）。

虽然 `tools_were_called` 标志在一定程度上缓解了这个问题，但如果某轮工具调用解析失败（`calls` 为空），后续轮次的合法引用会被误判。

**建议：**
- 将"工具返回"相关关键词从检测列表中移除，或仅在 `tools_were_called=False` 且是第 0 轮时检测

---

### 发现 19：MessageHandler._make_internal_registry 与 CliController._make_internal_registry 重复（严重程度：低）

**位置：**
- `core/message_handler.py` 第 55-62 行
- `core/cli_controller.py` 第 44-51 行

**问题描述：**

两个类中定义了完全相同的 `_make_internal_registry` 方法：

```python
def _make_internal_registry(self):
    from tools.traits import ToolRegistry
    r = ToolRegistry()
    for name in ("recall", "remember"):
        tool = self.a._tool_registry.get(name)
        if tool:
            r.register(tool)
    return r
```

这是代码重复，维护时需要同时修改两处。

**建议：**
- 提取为共享函数或基类方法

---

### 发现 20：context_manager.compress() 中 text 截断逻辑可能导致信息丢失（严重程度：中）

**位置：**
- `core/context_manager.py` 第 72-98 行

**问题描述：**

```python
# core/context_manager.py:75-86
for m in messages:
    if m["role"] == "system":
        continue
    content = m["content"]
    if len(content) > 500:
        content = content[:500] + "..."
    parts.append(f"{'用户' if m['role'] == 'user' else '你'}: {content}")
text = "\n".join(parts)
if not text.strip():
    return
if len(text) > 8000:
    text = text[-8000:]
```

**问题：**

1. 每条消息截断到 500 字符，可能丢失关键信息（如工具结果中的重要数据）
2. 总文本截断到 8000 字符，取最后 8000 字符而非最相关的 8000 字符
3. 压缩 prompt 要求"保留重要信息"，但截断逻辑是机械的，不区分重要性

**建议：**
1. 保留 system prompt 和最近 2-3 轮完整对话，只压缩更早的历史
2. 对长消息使用智能摘要而非机械截断
3. 优先保留用户输入和 AI 回复，压缩中间的工具调用细节

---

## 汇总统计

### 风险分级统计

| 风险等级 | 数量 | 发现编号 |
|----------|------|----------|
| 高 | 6 | 1, 2, 3, 4, 11, 14 |
| 中 | 8 | 5, 6, 7, 8, 9, 10, 12, 20 |
| 低 | 6 | 13, 15, 16, 17, 18, 19 |

### 按类别统计

| 类别 | 数量 | 相关发现 |
|------|------|----------|
| 数据流不一致 | 3 | 1, 5, 12 |
| 信息丢失 | 3 | 2, 6, 20 |
| 上下文膨胀 | 2 | 3, 4 |
| 错误处理缺失 | 2 | 9, 14 |
| 格式/协议问题 | 3 | 7, 8, 11 |
| 性能/效率 | 3 | 4, 13, 16 |
| 状态管理 | 2 | 10, 17 |
| 代码重复 | 1 | 19 |

### 核心文件问题密度

| 文件 | 发现问题数 | 代码行数 | 问题密度 |
|------|-----------|----------|----------|
| core/message_handler.py | 9 | 291 | 高 |
| core/agent.py | 6 | 255 | 高 |
| core/dispatcher.py | 3 | 213 | 中 |
| core/context_manager.py | 3 | 99 | 高 |
| core/inner_drive.py | 2 | 376 | 低 |
| core/tool_agent.py | 2 | 259 | 低 |
| tools/traits.py | 1 | 95 | 中 |
| web/session.py | 1 | 120 | 低 |
| web/server.py | 1 | 250 | 低 |

### 优先修复建议

**P0（立即修复）：**
1. 统一 CLI 和 Web 路径的 Agent 2 多轮循环逻辑（发现 1）
2. 修复 ToolRegistry.to_json_schema() 返回无效 schema（发现 11）
3. 在 _react_loop 中添加 token 检查和截断机制（发现 3）

**P1（本周修复）：**
4. 重写 _build_messages 的 token 估算逻辑（发现 4）
5. 丰富 Agent 1 → Agent 2 的数据传递（发现 2）
6. 修复 execute_tool_calls 的 asyncio 线程安全问题（发现 14）

**P2（下月修复）：**
7. 统一工具结果格式化（发现 5）
8. 优化 Agent 1 review 的消息累积（发现 6）
9. 添加 proactive/explore 的错误处理（发现 9）
10. 修复 Web 端 emotion 事件记录（发现 10）

---

## 附录：关键代码路径索引

### 消息入口
- Web: `web/server.py:223-234` → `web/session.py:84-89` → `core/agent.py:104-105`
- CLI: `core/cli_controller.py:99-116` → `core/agent.py:225-226`

### 三层 Agent 调用链
- Agent 1: `core/message_handler.py:78-79` → `core/inner_drive.py:61-111`
- Agent 2: `core/message_handler.py:90-141` → `core/tool_agent.py:142-224`
- Agent 3: `core/message_handler.py:243-272` → `core/agent.py:119-181`

### 数据持久化点
- short_term: `memory/short_term.py:23-35`
- SQLite turns: `storage/repository.py:218-226`
- SQLite facts: `storage/repository.py:34-68`
- personality.json: `core/personality.py:113-116`

### Token 管理
- 估算: `core/context_manager.py:27-35`
- 压缩: `core/context_manager.py:62-98`
- 阈值: `core/context_manager.py:8`
