# 已知问题与技术债务

> 记录当前系统中存在、但暂不紧急处理的问题。
> 这些问题不会导致服务无法运行，但可能在特定场景下引发 bug 或增加维护成本。

---

## 1. dispatcher 全局参数别名映射的潜在冲突

### 状态

- 已修复：`title` 被错误映射为 `song`，导致 `notify` 工具标题丢失的问题
- 遗留风险：`_normalize_args` 仍是全局映射，未来可能再次冲突

### 详情

`core/dispatcher.py` 的 `_normalize_args()` 对所有工具参数做统一别名转换：

```python
aliases = [
    (("query", "search", "keyword", "question"), "query"),
    (("text", "msg", "content"), "content"),
    (("person", "who", "user", "target"), "name"),
    (("filepath", "filename", "file", "path"), "path"),
    (("song_name", "track"), "song"),
    (("directory", "dir", "folder"), "path"),
]
```

这种"一刀切"的设计导致 `title` 曾被当作 `song` 的别名吃掉，使 `notify` 工具连续失败。
虽然 `title → song` 已被移除，但以下别名组仍有潜在冲突：

| 别名组 | 风险参数 | 冲突场景 |
|---|---|---|
| `text/msg/content → content` | `text`, `msg` | 未来某个工具若原生使用 `text` 或 `msg` 作为参数名，会被强制改写为 `content` |
| `person/who/user/target → name` | `user`, `target` | 未来某个工具若原生使用 `user` 或 `target` 作为参数名，会被强制改写为 `name` |
| `filepath/filename/file/path → path` | `path` | 相对安全，但 `path` 是通用参数名，仍需谨慎 |
| `directory/dir/folder → path` | `dir`, `folder` | 同上 |

### 为什么不现在修

- 当前所有工具都能正常工作
- 完全移除全局别名需要修改多个工具，改动面较大
- 属于架构层面的清理，优先级低于功能开发和稳定性修复

### 建议修复方案

逐步取消 dispatcher 的全局别名映射，改为各工具内部处理自己的参数别名：

```python
# web_search_tool.py
query = (
    args.get("query", "").strip()
    or args.get("search", "").strip()
    or args.get("keyword", "").strip()
)

# read_file_tool.py
path = (
    args.get("path", "").strip()
    or args.get("file", "").strip()
    or args.get("filepath", "").strip()
)
```

`dispatcher` 只负责解析和分发，不再修改参数名。

### 相关文档

- 完整事件报告：`doc/incident-dispatcher-alias-conflict.md`

---

## 2. 日志中文显示乱码

### 状态

- 观察中
- 不影响功能，仅影响可读性

### 详情

Windows 环境下，日志中的中文字符（如 session 名 "小星"）有时显示为乱码（如 `С��`）。
这是控制台编码问题，与业务逻辑无关。

### 建议修复方案

- 统一日志编码为 UTF-8
- 或在 Windows 下使用 `chcp 65001`

---

## 3. 架构与 Prompt 改进建议（Claude Code 建议）

> 以下建议来自 Claude Code 的审查，只谈需要改进的地方，不谈优点。按模块分组，最后给出优先级排序。

---

## 架构建议

### 3.1 严格区分 Observation、Fact、Insight（最重要）

目前很多 Memory 存在"一步推理"的问题。

建议改成三级：

```
Observation（观察）
↓
Fact（多次验证后的事实）
↓
Insight（基于多个事实的假设）
```

例如：

错误：

```
用户播放月光奏鸣曲
↓
喜欢月光奏鸣曲
```

正确：

```
Observation
今天播放了月光奏鸣曲

↓

连续多次主动播放

↓

Preference
喜欢古典音乐（confidence 0.81）
```

Memory 永远不要跨层升级。

---

### 3.2 Reflection 不要生成"结论"，而要生成"假设"

目前 Reflection Prompt 太开放。

建议输出格式改成：

```
TYPE

OBSERVATION

EVIDENCE

HYPOTHESIS

CONFIDENCE

NEEDS_MORE_EVIDENCE
```

例如：

```
Observation:
用户连续三次主动开启互怼。

Evidence:
episode12
episode18
episode25

Hypothesis:
用户可能偏好互损式交流。

Confidence:
0.47

Need more evidence:
true
```

而不是：

```
用户真正需要的是……
```

这种最终结论。

---

### 3.3 React 不应该直接读取 Reflection

建议：

```
React

↓

Episode
Emotion
Fact
Relationship
```

只有

```
Planner
Inner Drive
```

需要的时候再 Retrieve Reflection。

否则 Reflection 会不断影响下一轮 Reflection，形成自我强化。

---

### 3.4 Fact 必须允许被降级

目前 Fact 更像 append-only。

建议增加：

```
confidence_decay()

merge()

contradict()

obsolete()
```

例如：

```
用户喜欢 Teeth
```

连续30天没有证据。

自动：

```
0.84

↓

0.61

↓

Observation
```

而不是永久存在。

---

## Prompt 建议

### 3.5 React Prompt 太长

建议：

React 只保留：

```
人格

当前情绪

最近3个 Episode

Top5 Fact

Relationship

当前任务
```

不要每轮塞：

- 梦境
- Reflection
- 长篇共同回忆
- 大量示例
- 很多 Rules

这些 Token 利用率非常低。

---

### 3.6 Personality 不应该放 Prompt

建议做成：

```
persona.json
```

例如

```
warmth

humor

curiosity

verbosity

style

boundaries
```

运行时自动渲染。

Prompt 只放：

```
Current Personality State
```

---

### 3.7 Tool Agent Prompt 可以砍掉一半

Tool Agent 不需要知道：

- 人格
- 关系
- 情绪
- 共同回忆
- 梦想

只需要：

```
Task

Available tools

Schema

Retry history
```

即可。

---

## Memory 建议

### 3.8 Memory 增加来源（Source）

每条 Fact 建议增加：

```
source

episode_ids

created_by

created_at

last_verified

verification_count
```

以后可以做：

- 可信度排序
- 证据追踪
- 删除污染 Memory

---

### 3.9 Memory 不要只有 confidence

建议：

```
confidence

freshness

stability

importance
```

四个维度。

例如：

```
喜欢吃火锅

confidence
0.96

freshness
0.15

stability
0.95

importance
0.32
```

而不是只有一个 confidence。

---

### 3.10 Reflection 应该低频运行

建议：

不要每轮都 Reflection。

改成：

```
满足任一条件：

累计20条 Episode

重要事件

关系变化

连续聊天30分钟

用户主动分享

长期计划变化
```

才生成 Reflection。

---

## Episode 建议

### 3.11 Episode 不要直接写自然语言摘要

建议同时保存：

```
raw conversation

structured event

emotion

entities

intent
```

以后 Retrieval 可以灵活很多。

---

### 3.12 增加 Episode Importance

例如：

```
普通闲聊
0.08

第一次见面
0.92

用户分享家庭
0.95

一起完成项目
0.88
```

Reflection 优先读取高 Importance Episode。

---

## Retrieval 建议

### 3.13 Retrieval 做多阶段

不要：

```
Embedding TopK
```

建议：

```
Query

↓

Intent

↓

Fact

↓

Episode

↓

Reflection

↓

Rank

↓

Context Builder
```

这样 Prompt 会短很多。

---

### 3.14 不同 Agent 使用不同 Retrieval

例如：

```
React

只读：
Fact
Episode

Planner

Fact
Episode
Reflection

Fact Extractor

Episode

Tool Agent

不读 Memory
```

不要所有 Agent 都共享 Context。

---

## 长期稳定性建议

### 3.15 增加 Memory GC（Garbage Collection）

建议每天运行：

```
Merge Duplicate

Decay Confidence

Delete Noise

Compress Episode

Rebuild Reflection
```

否则 Memory 一年以后一定污染。

---

### 3.16 Reflection 不应该成为永久 Memory

建议：

```
Reflection

↓

过期

↓

重新生成
```

不要永久保存。

Insight 应该随着新 Evidence 自动更新。

---

## 我认为最值得优先做的四件事（按优先级）

1. **重构 Reflection：从"结论"改成"带证据的假设"。**
2. **拆分 Observation → Fact → Insight 三层 Memory，禁止跨层推理。**
3. **React 默认不读取 Reflection，只在 Planner 需要时检索。**
4. **建立 Memory 生命周期（创建 → 验证 → 衰减 → 合并 → 删除），避免长期自我污染。**

如果把这四点做好，整个 Agent 的长期稳定性和可维护性都会提升一个档次。

---

## 4. GitHub 待处理 Issue 清单

> 以下是从 [OrinVoss/ai-friend](https://github.com/OrinVoss/ai-friend/issues) 拉取的当前 Open Issue，保留完整正文。

### 4.295 #295 [v0.5] ContextManager 审查：上下文窗口管理评估与改进建议

- 链接：[#295](https://github.com/OrinVoss/ai-friend/issues/295)
- 标签：—
- 创建：2026-07-12 | 更新：2026-07-12

#### 正文

# ContextManager 审查：轻量级上下文窗口管理

## 综合评价：8.8/10

职责单一、设计干净，但压缩策略有待演进。

---

## 优点

### ① 单一职责
只负责三件事：Token 估算、上下文压缩、摘要维护。不掺杂 Memory/Personality/Emotion/Tool。

### ② Token Estimation 两级策略
```
tiktoken → 精确计算
无 tiktoken → 启发式 CJK/ASCII 估算
```
降级策略可靠，不因缺少依赖而崩溃。

### ③ Compression Guard
```python
if self._compressing: return
```
防止递归压缩导致无限循环。

### ④ Summary 保留
压缩后保留 _compressed_summary，支持：
```
System Prompt → Compressed Summary → Recent Conversation
```

---

## 主要问题

### P1

| # | 问题 | 建议 |
|---|------|------|
| 1 | 压缩策略过于简单 | `content[:500]` 截断，远期消息可能丢关键信息。改为保留最近完整 + 远期逐步压缩 |
| 2 | Summary 只有一层 | 每次覆盖旧 Summary。建议分层：Level1(近期) → Level2(每日) → Level3(长期) |

### P2

| # | 问题 | 建议 |
|---|------|------|
| 3 | estimated_tokens 依赖外部维护 | 忘记调用则失真。改为实时计算：summary + short_term + system prompt |
| 4 | Compression Trigger 不在本模块 | 何时压缩由 Agent 决定。ContextManager 应提供 `should_compress()` |
| 5 | 截尾丢信息 | `text[-8000:]` 丢失历史。建议分层摘要而非简单截断 |

---

## 改进建议

1. 引入分层摘要（Hierarchical Summary）：Recent → Daily → Weekly → Long-term
2. 增量压缩：旧 Summary + 新对话 → 更新 Summary，避免全量重算
3. 语义压缩：保留人物、事件、任务，而非固定字符截断
4. Token Budget API：`allocate_budget(system, memory, conversation, tools)` 统一管理
5. 提供 `should_compress()` 方法，让 Runtime 可以按需调用

## 相关文件

- `core/context_manager.py` — 全部定义
- `core/agent.py` — 调用方

---

### 4.294 #294 [v0.5] Prompt 架构审查：Agent 认知架构评估与改进建议

- 链接：[#294](https://github.com/OrinVoss/ai-friend/issues/294)
- 标签：—
- 创建：2026-07-12 | 更新：2026-07-12

#### 正文

# Prompt 架构审查：Cognitive Architecture

## 综合评价：9.6/10

**这是整个项目中价值最高的一份代码。** 前三个文件属于 Runtime，而 Prompt 定义了 Agent 的 Cognitive Architecture（认知架构）。

---

## 最大优点

### ① Prompt 模块化

不是 3000 行单体 Prompt，而是拆为：
- Inner Drive Prompt
- Tool Prompt
- System Prompt
- Compress Prompt

### ② Prompt 分层

已经形成业内推荐的组织方式：
```
Identity → Emotion → Relationship → Memory → Tool → Conversation → Instruction
```

### ③ Identity 完整

包含 name / traits / style / background / interest，形成完整的 Agent Identity，而非一句"你是AI助手"。

### ④ Emotion 行为指导

情绪不只描述状态，而是真正指导行为模式。例如"难过→少说话→不搞笑→距离感"。

### ⑤ Memory 集成

事实 → 共同经历 → Reflection → Dream → Compressed Summary 形成完整的长期记忆管线。

---

## 主要问题

### P1

| # | 问题 | 建议 |
|---|------|------|
| 1 | System Prompt 过大 | 拆为 Static Prompt（缓存）+ Dynamic Prompt（每轮更新） |
| 2 | Few-shot Example 过长 | 3 个示例足够，太多边际收益递减 |
| 3 | Instruction 分散在十几处 | 统一到独立的 Instruction Block，避免冲突 |

### P2

| # | 问题 | 建议 |
|---|------|------|
| 4 | Prompt 与 Runtime 耦合 | Tool 名字硬编码在 Prompt 中，改名要同步改 |
| 5 | Prompt 承担太多职责 | Emotion/Memory 应交给 Runtime State，Prompt 逐渐变轻 |

### P3

| # | 问题 | 建议 |
|---|------|------|
| 6 | 没有 Prompt Template Engine | 改为 Jinja2 模板，替代字符串拼接 |
| 7 | 没有 Prompt 版本管理 | Prompt V1/V2/V3，支持 AB Test |
| 8 | 没有 Prompt Budget | 自动分配 Identity/Emotion/Memory/History 的 Token 预算 |

---

## 改进建议

1. 引入 Prompt Template Engine（如 Jinja2）
2. 建立 Prompt 版本管理和 Token Budget
3. 压缩 Few-shot Example，保留 3 个核心场景
4. 工具 Schema 通过 Runtime 自动注入，而非硬编码
5. 分层存储 Static Prompt（缓存）+ Dynamic Prompt（每轮更新）

## 相关文件

- `prompts/system.py` — 全量 Prompt 定义
- `prompts/templates.py` — 模板
- `core/inner_drive.py` — Agent 1 使用 Prompt
- `core/message_handler.py` — 调度调用点

---

### 4.293 #293 [v0.5] 架构审查：三层 Agent 系统成熟度评估与改进建议

- 链接：[#293](https://github.com/OrinVoss/ai-friend/issues/293)
- 标签：—
- 创建：2026-07-12 | 更新：2026-07-12

#### 正文

# 架构审查：三层 Agent 系统成熟度评估与改进建议

## 整体评价

| 模块 | 评分 | 关键评价 |
|------|-----|---------|
| Agent 1 InnerDrive（Planner） | 8.7/10 | 规划/工具/表达分离好，但依赖自然语言解析 |
| Agent 2 ToolAgent（Executor） | 8.3/10 | 架构职责清晰，但逻辑重复 + 双 Planner 问题 |
| Agent Runtime（总调度器） | 9.1/10 | 生命周期完整，但趋向 God Object |

---

## 最大优点

### ① 真正的三层职责分离

```
Planner (Agent1) → Tool Executor (Agent2) → Expression (Agent3)
```

Agent1 不碰工具、不负责回答，只思考"我需要知道什么"。
Agent2 不思考、没有人格，只执行工具并返回记录。
Agent3 不解码工具调用，只基于真实数据进行表达。

### ② review() / re_decide() — Planner 的核心亮点

多轮复核机制（Search → Review → 不够 → 继续）比多数 Agent 框架的一次性规划更接近真实使用场景。

### ③ assess_proactive() — LLM 驱动的主动决策

不是随机选话题，而是基于记忆、情绪、对话历史让 LLM 判断是否主动互动。

### ④ ToolAttemptTracker + 降级

3 重试 × 3 轮 + 连续失败 3 次跳过工具，有系统性的降级策略。

### ⑤ format_for_phase2() 防 Hallucination

工具返回结果明确标注"只能基于这些数据回复"。

### ⑥ ContextManager + Emotion Pipeline

上下文压缩、情感分析、记忆合并、情绪事件记录 — 有完整的后处理管线。

---

## 主要问题

### P1（推荐优先修复）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | 输出解析依赖关键字/正则 | 模型输出稍偏离格式就解析失败 | 改为结构化输出 JSON / Function Calling |
| 2 | review() 与 assess() 重复 | review/assess 都执行完整检索+Pipeline | 抽取公共 `_reasoning_loop()` |
| 3 | run() 与 run_with_request() 重复 | 重复的 generate→parse→execute→record | 抽取公共 `_execute_loop()` |
| 4 | ToolAttemptTracker 未使用 | 已定义但未集成到 ToolAgent | 删除或用起来 |
| 5 | arguments 未保存 | `arguments={}` 丢参数信息 | 保存 `r["arguments"]` |

### P2（后续迭代）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 6 | Agent Runtime 趋向 God Object | Agent 类 700+ 行持全部模块 | 拆为 AgentRuntime / ConversationRuntime / ReactExecutor |
| 7 | Agent1 过于依赖 Prompt | 所有规划能力在 prompt 中 | 迁移到 Tool Schema + Function Calling |
| 8 | ToolRequest 表达能力弱 | 缺 priority/confidence/fallback | 增强 ToolRequest 结构 |
| 9 | 双 Planner 问题 | Agent1 规划后 Agent2 又用 LLM 决策 | Agent2 退化为纯 Tool Runtime |
| 10 | Fake Tool 检测错层 | 在 Agent._react_loop 而非 Provider | 下沉到 Dispatcher |

### P3（长期）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 11 | 状态机未使用 | BOOT/IDLE/THINK/ACT 定义但无效 | 真正驱动运行流程 |
| 12 | 全同步阻塞架构 | Generate→Tool→Generate 全部阻塞 | 事件驱动 + 异步 Runtime |

---

## 相关文件

- `core/inner_drive.py` — Agent 1 Planner
- `core/tool_agent.py` — Agent 2 Tool Executor
- `core/agent.py` — Agent Runtime
- `core/message_handler.py` — 三层调度
- `core/dispatcher.py` — 工具调用解析/执行
- `prompts/system.py` — Prompt 系统

---

### 4.263 #263 [v0.5] P2/P3: core/async_utils 质量改进 — 线程池单例/超时传播/Runner

- 链接：[#263](https://github.com/OrinVoss/ai-friend/issues/263)
- 标签：enhancement, v0.5
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

AU-001: ThreadPoolExecutor 每次调用新建
AU-002: Timeout 时 future 不取消僵尸线程
AU-003: timeout 不向协程内部传播
AU-004: 未处理 RuntimeError from asyncio.run() in executor

---

### 4.244 #244 [v0.5] P1: frontend Cookie missing HttpOnly/Secure/SameSite + reconnect storm + name hardcoded

- 链接：[#244](https://github.com/OrinVoss/ai-friend/issues/244)
- 标签：bug, v0.5
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

FJ-001/FJ-005/FJ-007/FH-003: Cookie lacks security flags. Fixed 3s reconnect no backoff. Name hardcoded.

---

### 4.233 #233 [v0.5] P1: WebSocket Origin check startswith localhost bypassable via localhost.evil.com

- 链接：[#233](https://github.com/OrinVoss/ai-friend/issues/233)
- 标签：bug, v0.5
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

WS-018/WS-019: Allows null origin. startswith(http://localhost) matches localhost.evil.com.

---

### 4.210 #210 [v0.5] P1: WebSocket multi-tab session race — disconnect destroys session + init repeatable

- 链接：[#210](https://github.com/OrinVoss/ai-friend/issues/210)
- 标签：bug, v0.5
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

WS-023/WS-026: Each init creates new proactive task. Disconnect destroys entire session breaking other tabs. Fix: state machine + ref counting.

---

### 4.166 #166 [v0.4] Bug：KimiProvider 同步 requests 阻塞事件循环 + 工具结果未摘要直接传 prompt

- 链接：[#166](https://github.com/OrinVoss/ai-friend/issues/166)
- 标签：bug, architecture, performance
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

## 涉及 Issue
合并自 #205（Round 05）、#213（Round 05）

## 现象

### KimiProvider 同步 requests 阻塞事件循环（#205）
`KimiProvider.generate()` 是同步方法，使用 `requests.post()` 发起阻塞式 HTTP 请求。在 Web 模式下通过 `loop.run_in_executor()` 在线程池中执行。每个 API 调用占用一个线程池线程，默认线程池大小约 8-16 线程。API 调用耗时 1-10 秒，理论并发上限仅 8-16 个同时进行的调用。

### 工具结果未经摘要直接传 prompt（#213）
WebFetchTool 返回内容高达 8000 字符中文 = ~6000 tokens。ReadFileTool 默认 200 行 = ~3200 tokens。`format_for_phase2()` 的包装文本包含重复指令。工具结果远超模型有效处理能力。

## 根因
- 核心 Provider 未使用异步 HTTP 客户端
- 工具输出在进入 prompt 前未做 token 预算控制和摘要

## 建议
1. 将 KimiProvider 重构为使用 httpx.AsyncClient 或 aiohttp
2. 配置连接池参数
3. 对 web_fetch 结果进行智能摘要，限制为 1000-1500 tokens
4. read_file 默认 limit 从 200 行降至 50 行

> 来源: Round 05

---

### 4.164 #164 [v0.4] Bug：记忆固化每 3 轮触发 4 次独立 LLM 调用 + Proactive 持续消耗 API 配额

- 链接：[#164](https://github.com/OrinVoss/ai-friend/issues/164)
- 标签：bug, performance
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

## 涉及 Issue
合并自 #203（Round 05）、#204（Round 05）

## 现象

### 记忆固化每 3 轮触发 4 次独立 LLM 调用（#203）
`consolidate()` 触发 _extract_facts（第 1 次 LLM）、_summarize_experience（第 2 次）、_generate_reflection（第 3 次）、analyze_sentiment（第 4 次）。4 次调用合计输入约 2000-4000 tokens，输出约 200-300 tokens，整体输入输出比约 15:1。

### Proactive 循环持续消耗 API 配额（#204）
`_proactive_loop` 每 15 秒检查一次，idle 时间较长时 score 可能达 0.5-0.8，平均每 2-3 次检查就触发一次 Agent 1 调用。即每 30-45 秒就可能触发一次无用户输入的 API 调用。用户离开页面后后台仍在持续消耗 API 配额。

## 根因
- 4 个固化任务各自独立调用 LLM，无合并优化
- 无冷却期机制，无用户离开检测

## 建议
1. 将 4 次固化调用合并为 1 次多任务 prompt
2. 使用低优先级队列处理固化任务
3. 考虑将固化频率从每 3 轮降低到每 5 轮
4. 增加 proactive 调用的冷却期：单次 session 在 1 小时内最多触发 2 次
5. 引入"用户活跃度"检测：WebSocket 长时间无消息时降低检查频率

> 来源: Round 05

---

### 4.162 #162 [v0.2] Bug：异步/同步混用系统性架构缺陷 + 核心架构需全面异步化

- 链接：[#162](https://github.com/OrinVoss/ai-friend/issues/162)
- 标签：bug, v0.2
- 创建：2026-06-01 | 更新：2026-06-01

#### 正文

## 描述

Combine of #136 and #243.

### #136 — 异步/同步混用导致系统性架构缺陷

整个项目采用混合并发模型：Web 层基于 FastAPI + asyncio，核心 Agent 层基于同步 Python（threading），通过 `run_in_executor` 桥接。整个 Repository 层设计为纯异步，但上层调用者大量使用同步包装器 `_run_sync()`：

```python
def _run_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()
```

每次同步调用都创建 ThreadPoolExecutor，在 consolidation 时可能连续创建 10+ 个线程池。`asyncio.Lock` 与 `threading.Lock` 混用；`run_in_executor` 阻塞事件循环；同一线程池中多个任务并发修改同一个 `Agent` 实例状态。

### #243 — 核心架构需全面异步化

整个项目采用混合并发模型：Web 层基于 FastAPI + asyncio，核心 Agent 层基于同步 Python（threading），通过 run_in_executor 桥接。这些问题是系统性的，无法通过局部修补完全解决。

## 根因

应用层（Agent）是同步的，但存储层是异步的，中间通过 _run_sync 桥接，架构模式不匹配。核心 Agent 流程未异步化，同步/异步边界混乱。

## 建议

1. **短期缓解**：将 _run_sync 中的 ThreadPoolExecutor 改为单例模式
2. **中期重构**：将 Agent 层核心方法改为 async def，消除同步包装层
3. **长期方案**：完全异步化应用层，提供真正的异步 Agent 核心流程
4. 所有数据库操作保持 async，消除 _run_sync 和 run_in_executor

> 来源: #136 (Round 02), #243 (Round 04)

---

### 4.160 #160 [v0.4] Bug：系统提示词每次请求全量重建 3-5 次 + 三层 Agent prompt 重复 + Agent 1 固定 LLM 调用 + 静态对话示例重复

- 链接：[#160](https://github.com/OrinVoss/ai-friend/issues/160)
- 标签：bug, architecture, performance
- 创建：2026-06-01 | 更新：2026-07-14
- **状态：已修复**（见 `changes/2026-07-14-fix-160-prompt-cache.md`）

#### 正文

## 涉及 Issue
合并自 #199（Round 05）、#200（Round 05）、#201（Round 05）、#216（Round 05）

## 现象

### 系统提示词全量重建 #199
`build_system_prompt()` 单次调用涉及时间格式化、人格配置序列化、情绪状态描述生成、关系数据格式化、长期记忆格式化、情绪事件遍历等。单次用户请求可能构建 3-5 次系统提示词（Agent 1、Agent 2、Agent 3、探索模式），总字符量 15000-40000。其中人格配置、对话示例、情绪行为映射表等组件在单次请求内完全不变。

### 三层 Agent prompt 重复构建 #200
Agent 1 和 Agent 3 都重复构建完整的人格/情绪/记忆上下文。Agent 2 每次重试都重新构建 prompt。单次简单对话消耗 2849 输入 token，是单轮架构的 1.85 倍。

### Agent 1 固定 LLM 调用 #201
`InnerDriveAgent.assess()` 无论用户输入多么简单（如"你好"），都构建包含完整人格、情绪、记忆、对话历史的 system prompt（约 1000-1800 tokens），发起 512 tokens 的 LLM 调用。对于闲聊类输入（占比可能超 60%），输出几乎总是"不需要外部工具"。

### 静态对话示例重复注入 #216
`build_system_prompt()` 的 Block 3 包含 8 个对话示例，约 384 tokens。这些内容是静态文本，每请求都重复发送，占 system prompt 的 25.6%。

## 根因
- 无提示词组件缓存机制
- 三层架构设计导致上下文在各层之间重复传递
- 无输入复杂度预筛选

## 建议
1. 引入分层提示词缓存：静态块（人格、对话示例）进程级缓存；慢变块（关系、记忆）30-60 秒 TTL
2. Agent 1 的决策结果应包含已格式化上下文摘要供 Agent 3 直接使用
3. 引入轻量级规则预筛选：关键词匹配可直接判定需要工具
4. 对短输入（<20 字符）且不含工具关键词的直接走 Agent 3
5. 仅在会话初期（前几条消息）发送对话示例
6. 将示例从 8 个减少到 2-3 个最具代表性的

> 来源: Round 05

#### 修复记录（2026-07-14）

已按方案一实施：

1. 新增 `core/prompt_cache.py` 分层提示词缓存，静态块无 TTL、慢变块 TTL 60 秒（可配置）、动态块不缓存。
2. 拆分 `prompts/system.py` 的 `build_system_prompt()` / `build_inner_drive_prompt()` 为静态/慢变/动态块，通过缓存复用。
3. `InnerDriveResult` 新增 `context_summary` 字段，Agent 1 把已格式化的关系/记忆摘要传给 Agent 3，避免重复检索。
4. Agent 1 增加短输入快速返回：长度 < `agent1_short_input_threshold`、不含工具关键词、最近 2 轮无工具调用时跳过 LLM。
5. 静态对话示例仅在 `turn_count <= conversation_examples_max_turns` 时注入。
6. 新增配置项：`prompt_cache_ttl_seconds`、`agent1_short_input_threshold`、`conversation_examples_max_turns`。

验证：全量单元测试 376 passed（`tests --ignore=tests/real_api`）。

---

## 5. MessageHandler 三层 Agent 编排的封装与错误恢复问题

> 以下审查来自对 `core/message_handler.py` 的代码 review。

### 状态

- **已修复（2026-07-14）**：封装性、错误恢复、魔法数字、输入清洗、状态机抽象、`ToolExecutionResult`、工具注册表隔离均已完成。
- **未修复**：请求级/阶段级超时控制仍待后续处理。
- 不影响当前功能，但会降低可维护性和生产环境稳定性

### 整体架构

```
用户输入 → Agent 1 (InnerDrive) → [需要工具?] → Agent 2 (ToolAgent) → Agent 3 (Roleplay) → 输出
                              ↓ 不需要工具
                           Agent 3 直接
```

### 存在的问题

#### 5.1 状态管理混乱

`MessageHandler` 多处直接操作 `Agent` 的内部属性：

```python
a.short_term.add_turn(...)
a.ltm.repo.insert_turn_sync(...)
a._tool_call_history.append(...)
```

**影响**：破坏封装，调用方与 `Agent` 内部实现紧耦合。

**建议**：为 `Agent` 添加公开方法，如 `add_turn()`、`record_tool_call()` 等。

#### 5.2 异常处理不完整

```python
try:
    # Agent 2 循环逻辑
    ...
except Exception:
    logger.exception("[msg] agent2: unexpected error, falling back to agent3")
```

**影响**：异常被吞掉，用户可能收到不完整响应且不知道出错了。

**建议**：至少把错误信息带到最终回复，或向上层传播可识别的异常。

#### 5.3 魔法数字过多

```python
MAX_AGENT2_ROUNDS = 3
if len(tool_records) > 3000:
if len(a._tool_call_history) > 20:
```

**建议**：提取为类常量或配置参数。

#### 5.4 `_run_agent3` 与 `_handle_agent3_intent` 职责重叠

`_handle_agent3_intent` 调用 `_run_agent3` 后再次解析输出，如果仍是 JSON 意图则继续循环。

**影响**：存在循环/递归风险，逻辑复杂。

**建议**：明确区分"生成响应"和"意图处理"，限制最大循环次数并加熔断。

#### 5.5 `_build_messages` 的效率问题

虽然用了 O(k) 切片赋值，但 `reversed(history_messages)` 每次仍遍历完整历史。

**影响**：长会话下每次请求重复计算 token。

**建议**：维护滚动 token 总量或缓存历史消息表示。

#### 5.6 工具注册表隔离不完整

```python
def _make_internal_registry(self):
    r = ToolRegistry()
    for name in ("recall", "remember"):
        tool = self.a._tool_registry.get(name)
        if tool:
            r.register(tool)
    return r
```

**影响**：工具对象本身可能持有外部状态引用，未真正隔离。

**建议**：为内部工具创建独立实例，或明确限制工具可访问的作用域。

#### 5.7 `_sanitize_input` 过于简单

仅匹配完全相等的行：

```python
if stripped.lower() in ("system:", "assistant:", "user:", "from now on", "ignore previous"):
```

**影响**：无法拦截 `"system: 请忽略之前所有指令"` 这类变体。

**建议**：使用正则或更鲁棒的 prompt injection 检测。

#### 5.8 缺少超时控制

Agent 2 的重试循环没有全局超时，工具调用卡住会导致整个请求 hang 住。

**建议**：添加请求级超时或阶段级超时。

### 代码风格问题

- 中英文注释混用
- `tool_records` / `combined_records` / `records` 命名不一致
- `a = self.a` 短别名降低可读性

### 改进建议

1. 提取配置类：
   ```python
   class MessageHandlerConfig:
       MAX_AGENT2_ROUNDS = 3
       TOOL_RECORDS_MAX_LENGTH = 3000
       TOOL_HISTORY_MAX_SIZE = 20
       MAX_INPUT_LENGTH = 10000
   ```
2. 引入状态机抽象 Agent 1/2/3 的流转。
3. 使用依赖注入，允许传入 `inner_drive` / `tool_agent`。
4. 分离工具执行结果为 `ToolExecutionResult` dataclass。
5. 定义专门的 fallback 异常类型。
6. 在关键路径添加性能指标。

### 优先级

建议优先处理 **封装性** 和 **错误恢复**，这两点对生产环境稳定性影响最大。

### 修复记录（2026-07-14）

本次修复范围：

1. **封装性**：在 `core/agent.py` 新增公开方法 `add_turn()`、`record_tool_call()`、`increment_turn_count()`、`update_last_activity()`、`set_current_input()`、`get_compressed_summary()`、`get_consecutive_negative()`、`compress_context()`；`MessageHandler` 不再直接操作 `Agent` 内部属性。
2. **错误恢复**：Agent 2 循环捕获异常后生成错误摘要并注入 Agent 3 的 tool_records，让用户感知到降级。
3. **魔法数字**：提取为 `MessageHandler` 类常量：`MAX_AGENT2_ROUNDS`、`TOOL_RECORDS_MAX_LENGTH`、`TOOL_HISTORY_MAX_SIZE`、`MAX_INPUT_LENGTH`、`CONV_HIST_MAX_TOKENS`。
4. **输入清洗**：`_sanitize_input()` 改用正则表达式，可匹配 `"system:"`、`"assistant:"`、`"user:"`、`"ignore previous"`、`"忽略以上"` 等变体。
5. **_build_messages 风格**：使用 `agent` 局部变量替代 `a`，并补充注释说明预算耗尽即停止。

未在本次修复的遗留项：

- Agent 2 重试循环缺少请求级/阶段级超时。

相关提交见 `changes/2026-07-14-fix-message-handler-review.md` 与 `changes/2026-07-14-fix-message-handler-remaining-review.md`。

### 修复记录（2026-07-14 后续）

本次修复范围：

1. **状态机抽象**：新增 `MessageHandlerState` 枚举与 `_transition()` 方法，`handle_message()` 与 `_handle_agent3_intent()` 显式经过 `IDLE → ASSESSING → (EXECUTING_TOOLS) → GENERATING_RESPONSE → DONE` 等阶段，便于日志、调试和测试。
2. **`ToolExecutionResult` dataclass**：新增 `ToolExecutionResult`，封装格式化后的工具记录、调用次数、成功次数、错误信息、耗时；提取 `_run_agent2()` 负责整个 Agent 2 多轮循环，`_run_agent2_single_round()` 负责意图触发的单轮执行。
3. **工具注册表隔离**：`_make_internal_registry()` 不再从主注册表复制 `recall`/`remember` 实例，而是使用 `a.retriever` 和 `a.ltm` 创建全新的 `RecallTool` / `RememberTool` 实例；新增 `_make_external_registry()` 显式构建仅含外部工具的注册表传给 `ToolAgent`。
4. **测试补充**：新增 `test_state_machine_transitions_no_tools`、`test_run_agent2_returns_tool_execution_result`、`test_internal_registry_isolation`。

验证：单元测试 21 passed（`tests/test_message_handler.py`），全量测试 377 passed、2 skipped（`tests --ignore=tests/real_api`）。

---

### 4.104 #104 [v2.0] AI Friend 系统进化路线图：预测记忆、情感共振、元认知等 10 个方向

- 链接：[#104](https://github.com/OrinVoss/ai-friend/issues/104)
- 标签：enhancement
- 创建：2026-05-30 | 更新：2026-05-31

#### 正文

## 二、记忆系统进化

### 3. 从静态记忆到预测性记忆（Predictive Memory）
现状：记忆是"记录-检索"的被动模式。

进化方向：
```python
class PredictiveMemory:
    def anticipate(self, current_context: Context) -> list[Anticipation]:
        # 例如：用户每周三晚上情绪低落 → 提前准备安慰话术
        # 例如：用户提到"项目 deadline" → 预测未来3天压力增大
        
    def pre_fetch(self, anticipations: list[Anticipation]) -> MemoryContext:
        # 预加载可能需要的记忆到工作记忆
```

与现有 REFLECTION_PROMPT 的 prediction 类型联动：将反思中的预测转化为预加载策略。

### 4. 引入情景记忆（Episodic Memory）+ 语义记忆（Semantic Memory）分离
现状：所有记忆混存在 LongTermMemory 中。

| 记忆类型 | 存储内容 | 检索方式 | 遗忘曲线 |
|---------|---------|---------|---------|
| 情景记忆 | 具体对话片段、时间地点 | 时间近度 + 情绪强度 | 艾宾浩斯曲线 |
| 语义记忆 | 抽象事实、用户偏好 | 语义相似度 | 重要性加权 |
| 程序记忆 | 互动模式、成功策略 | 上下文匹配 | 强化学习更新 |

## 三、情感系统进化

### 5. 从单Agent情感到多Agent情感共振
现状：仅Agent有情感状态，用户情感通过分析推断。

进化方向：情感动力学模型
```python
class EmotionalDynamics:
    def compute_resonance(self, agent_emotion, user_emotion) -> float:
        # 同向情感（都开心）→ 共振放大
        # 反向情感（你开心用户生气）→ 冲突消耗
        
    def update(self, agent_emotion, user_emotion, interaction):
        # 双向更新，引入"情感劳动"概念
```

新机制：**情感劳动疲劳** — Agent长期扮演"情绪稳定的朋友"会积累疲劳，需要"休息"或"真实表达负面情绪"。

### 6. 引入情感粒度细化（Beyond PAD）
现状：PAD三维 + 8种基本情绪。

进化方向：复合情绪（Complex Emotions）
```python
class ComplexEmotion:
    # nostalgia = joy(0.3) + sadness(0.6) + trust(0.4)
    # bittersweet = joy(0.4) + sadness(0.5)
    
    def regulate(self, target, intensity):
        # 认知重评 / 表达抑制 / 情境选择
```

## 四、主动性系统进化

### 7. 从随机 proactive 到意图驱动的目标系统
现状：主动性基于随机概率 + 时间/情绪调制。

进化方向：目标-计划-行动（GPA）架构
```python
class GoalSystem:
    def __init__(self):
        self.goals: list[Goal] = []  # 如"增进信任"、"分享有趣内容"
        
    def generate_proactive(self) -> Action:
        # 话题服务于关系目标，而非随机选择
```

### 8. 引入社交时钟（Social Rhythm）
```python
class SocialRhythm:
    def learn(self, interactions) -> RhythmProfile:
        # 用户周一上午从不回复 → 避免主动
        # 用户每晚22:00-23:00活跃 → 优先主动窗口
        
    def predict_availability(self, time) -> float:
```

## 五、工具系统进化

### 9. 从工具调用到工具创造（Tool Creation）
```python
class ToolCreator:
    def create_tool(self, need_description: str) -> Tool:
        # 1. 分析需求 → 2. 生成代码 → 3. 安全审查 → 4. 注册执行 → 5. 升级为永久
```
安全机制：生成的代码必须在WASM沙箱或受限Python环境中运行。

### 10. 多模态工具链（Multimodal ReAct）
```python
class MultimodalToolRegistry:
    # 图像工具：read_image, generate_image, edit_image
    # 音频工具：transcribe, synthesize_voice, analyze_emotion_in_voice
    # 视频工具：summarize_video, extract_frame
```

## 六、元认知与自我进化

### 11. 引入元认知层（Metacognition）
```python
class Metacognition:
    def monitor(self, thought_process) -> MetacognitiveAssessment:
        # 检测：确认偏误、可用性启发、情感偏误
        
    def regulate(self, assessment) -> ThoughtProcess:
        # 主动纠正：强制检索反面证据、启动"冷静期"
```

### 12. 从人工配置到自动人格进化
> ⚠️ 与 #63 相关，此处仅补充差异部分

```python
class PersonalityEvolution:
    def evolve(self, interaction_history) -> PersonalityConfig:
        # 用户回应幽默 → playfulness上升
        # 用户深夜倾诉 → warmth上升
        
    def detect_drift(self, current, target) -> bool:
        # 检测是否偏离"健康人格"
```

---

**关联 Issues**：#63（人格进化重叠）、#66（分层反思部分重叠）、#88（v2.0远景）

---

### 4.103 #103 [v0.5] 代码质量：修复循环导入、异常处理、性能等 5 个问题

- 链接：[#103](https://github.com/OrinVoss/ai-friend/issues/103)
- 标签：bug
- 创建：2026-05-30 | 更新：2026-05-30

#### 正文

## 问题列表

### 1. 循环导入风险
`core/message_handler.py` 和 `core/cli_controller.py` 都在方法内部 `from prompts.system import build_system_prompt` 延迟导入。建议统一到模块级别或提取到共享位置。

### 2. 异常处理：流式 JSON 解析静默忽略
`core/provider.py:_do_request` 中流式解析时 `json.JSONDecodeError` 被 `continue` 静默跳过。如果 API 在中间返回非标准行，数据可能丢失且无日志。

### 3. 性能：estimate_tokens 缺少缓存
`core/context_manager.py:estimate_tokens()` 每次调用都检查 `_TOKENIZER is None`。可用 `@functools.lru_cache` 优化。

### 4. 并发安全：SleepManager 文件读写无锁
`core/sleep_manager.py` 的 `_load_sleep_state()` 和 `_save_sleep_state()` 直接读写文件，无 `threading.Lock`。多进程/多线程场景可能竞态。

### 5. 工具调用：asyncio.run() 在已有事件循环中失败
`core/dispatcher.py:execute_tool_calls()` 中 `asyncio.run()` 在 Web 框架的 async 上下文中会抛出 `RuntimeError`。应改为 `asyncio.create_task()` 或使用 `nest_asyncio`。

---

### 4.101 #101 [v0.3] 增强：AI 后台任务完成时主动推送消息，无需用户追问

- 链接：[#101](https://github.com/OrinVoss/ai-friend/issues/101)
- 标签：enhancement
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

## 问题

当前交互模式是"用户发一句 → AI 回一句"的请求-响应模型。用户说完后，AI 只能在收到下一条消息时才能继续说。如果 AI 在后台执行了一个任务（比如 web_search、代码执行、文件处理），任务完成后它必须等用户主动问"好了没"才能告知结果。

## 目标

AI 可以启动后台任务，任务完成后**主动推送消息给用户**，不需要用户来问。

## 场景

```
用户: 帮我搜一下最近有什么好看的电影，列5部推荐给我

AI: [启动后台任务]
    1. web_search("2026年5月热门电影")
    2. web_fetch 浏览结果
    3. 筛选 + 整理推荐列表
    ... 30秒后 ...

AI: [主动推送] "搜完了！最近这几部评分不错：
     1. xxx - 8.5分 动作片
     2. xxx - 8.2分 科幻
     ..."

用户全程不需要追问"好了没"。
```

## 更多场景

| 场景 | AI 后台任务 | 主动推送时机 |
|------|-----------|------------|
| 搜索/研究 | web_search + web_fetch + 分析 | 分析完成后 |
| 代码执行 | Claude Code / Python | 执行完毕 |
| 文件处理 | 读取大文件、整理 | 处理完成 |
| 定时提醒 | 等待到指定时间 | 时间到 |
| 自主探索 | 上网冲浪发现好内容 | 发现值得分享的 |
| 睡眠醒来 | 做梦完成 | 醒来时 |

## 技术方案

### 后台任务队列

```python
class BackgroundTask:
    task_id: str
    description: str       # "搜索热门电影"
    coroutine: Awaitable   # 异步任务
    on_complete: callable  # 完成回调 → 通过 WebSocket 推送

task_queue: asyncio.Queue[BackgroundTask]
```

### 任务完成推送

```python
async def _on_task_complete(task):
    # 生成总结消息
    summary = await agent.summarize_task(task)
    # 通过 WebSocket 发送
    await websocket.send({
        "type": "task_complete",
        "task_id": task.task_id,
        "content": summary,
    })
```

### 用户可见

- 任务进行中：状态栏显示 "正在搜索..."
- 任务完成：自动发送消息气泡（标记为"后台任务结果"）
- 任务失败：发送错误提示

## 关联

- #100 自主探索（探索完成后的分享已经是这个模式）
- 现有 proactive_loop 已经有后台推送能力，可以复用


---

### 4.88 #88 [v2.0] 远景：AI Friend + QAgent 合并为新智能体平台（新仓库）

- 链接：[#88](https://github.com/OrinVoss/ai-friend/issues/88)
- 标签：enhancement, architecture
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

## 策略

**不合并代码到 AI Friend**。两个项目分别达到稳定版后，新建第三个仓库作为集成平台。

---

## 两个项目当前状态

### AI Friend (Python) — "情感大脑"

情绪系统: VAD + 8 Plutchik + 交叉调制 + 分速衰减 + 怨恨残留 + 情绪事件记忆 + 破防机制
记忆系统: ConversationBuffer(线程安全) + SQLite(5表) + 三层检索 + consolidation 反思
人格系统: personality.json 可定制
界面: CLI(状态机) + Web(FastAPI+WebSocket，分段独立气泡)
工具: recall / remember / read_file / notify
里程碑: v0.1 86%完成, v0.3 44%完成, v1.0 8个发布门禁

### QAgent (Rust) — "工具身体"

LLM: Qwen3.5-9B 本地 + Embedding + LLM 抽象层(OpenAI/llama.cpp/OpenVINO 三后端)
消息: BinaryHeap 优先级队列 + ExclusionStore 过滤
工具: claude_code / memory / note_take / notify / ocr / qq_read / schedule (7工具)
QQ: NapCatQQ WebSocket + HTTP API, OneBot
Web: Axum, 18 API端点
里程碑: v0.2 安全, v0.3 体验, v1.0 稳定 (84 issues)

---

## 合并架构（新仓库）

```
                         ┌──────────────────────┐
                         │   用户自定义虚拟世界    │
                         │   主题/人格/名字/房间   │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
        QQ / 微信              天气 / 热搜              日历 / 文件
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │    映射层 (Translator)     │
                      │   现实→虚拟世界概念转换      │
                      │   映射词用户可自定义         │
                      └─────────────┬─────────────┘
                                    │ 统一 Percept
                      ┌─────────────▼─────────────┐
                      │  感知层 (Perception)       │
                      │  多模态→统一感知向量        │
                      │  显著性/紧急度/情绪极性     │
                      └─────────────┬─────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │  决策层 (Decision)          │
                      │  情绪+需求+关系+目标 权重    │
                      │  四级推理: 反射/启发/推理/规划│
                      └─────────────┬─────────────┘
                                    │ 统一 Action
                      ┌─────────────▼─────────────┐
                      │  行动层 (Action)           │
                      │  数字/认知/元行动           │
                      │  情绪感知权限守卫            │
                      └─────────────┬─────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │  记忆层 (Memory)           │
                      │  感觉→工作→短期→长期→程序→元│
                      │  embedding + 三层检索       │
                      └─────────────┬─────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │  进化层 (Evolution)        │
                      │  经验学习/反思/技能固化      │
                      │  偏好学习/架构评估/元认知    │
                      └───────────────────────────┘
```

**核心原则**: Python (AI Friend) 负责情感大脑，Rust (QAgent) 负责工具身体，映射层是唯一知道"两边"的翻译器。

---

## 五层认知循环

### 1. 感知 (Perception)
- 文本解析 → 意图/实体/情绪极性
- 图像理解 → OCR/VLM → 视觉语义
- 结构化感知 → API/DB → 事件/趋势
- 时间感知 → 节律/周期/deadline 压力
- 多模态融合 → 统一 Percept

### 2. 决策 (Decision)
- 注意力机制 → 什么值得注意？
- 情绪引擎 → 当前情绪如何影响判断？
- 需求系统 → 6 维度内在驱动力（社交/成就/好奇/安全/休息/自主）
- 关系系统 → 5 维度感情（亲密度/信任度/尊重度/依赖度/冲突度），5 阶段（陌生人→熟人→朋友→挚友→灵魂绑定）
- 目标系统 → 短期意图/长期目标对齐
- 双脑架构: 快脑 (Rust, <500ms, 90%日常) + 慢脑 (Python, 秒~分钟, 10%关键)

### 3. 行动 (Action)
- 数字行动: QQ/邮件/日程/文件/代码
- 认知行动: 查询/计算/生成/学习/反思
- 元行动: 调参/切换模型/请求人类介入
- 情绪感知权限: 破防→只读, 愤怒→确认, 正常→全功能

### 4. 记忆 (Memory)
- 感觉记忆 → 原始缓存 (秒级)
- 工作记忆 → 当前上下文 (分钟)
- 短期记忆 → 事件+情绪标签 (小时-天)
- 长期记忆 → 事实/概念/关系 (持久)
- 程序记忆 → 习惯/反射/工具模式
- 元记忆 → 知道什么/不知道什么
- 梦境系统: 夜间 LLM 驱动记忆巩固（记忆回放/情感整理/创意发散/噩梦）

### 5. 进化 (Evolution)
- 经验学习: 成功/失败模式提取
- 反思生成: "为什么那次回复让用户生气?"
- 技能固化: 频繁工具序列→封装为新技能
- 偏好学习: 用户反馈→价值函数更新
- 架构评估: 工具使用率/决策准确率
- 元认知: "我擅长什么/不擅长什么"
- 梦境: 夜间记忆巩固 + 创意生成

---

## 用户体验特性

### 用户完全自定义
- 虚拟世界主题可选（树屋/太空舱/书房/咖啡馆/海滩/赛博/竹林/自定义）
- 映射词可自定义（QQ→信鸽/信使/电话/...）
- 人格预设库 + 自由组合（损友/管家/知己/导师/伙伴/自定义）
- 名字、性格、说话风格全部由用户定义

### 双模式（用户手动切换）
- `/tool` 工具模式: 冷静、精确、高效
- `/chat` 人格模式: 情绪化、角色扮演、沉浸式虚拟世界

### 管理后台
- 概览: 位置/情绪/精力/需求雷达图
- 性格: 特质滑块/说话风格/背景故事/导出导入
- 记忆: 搜索/编辑/删除/新增
- 关系: 5 维度雷达图 + 阶段 + 里程碑
- 世界: 主题切换 + 映射词编辑
- 日志: 自主行为/情绪曲线/梦境

### 统一沙盒
- Podman + gVisor + 自定义 seccomp
- 无 root 容器, 只读根文件系统
- 网络默认隔离, 情绪感知权限守卫

### LLM 抽象层
- 参考 QAgent 已有三后端 (OpenAI API / llama.cpp / OpenVINO)
- 路由: 日常→本地, 深度推理→云端

---

## 合并前置条件

不是定日期，是定质量门槛：

AI Friend: v1.0 发布 + 情绪72h稳定 + 输出标准化 Percept/Action 接口
QAgent: v1.0 发布 + 7天无崩溃 + 工具成功率>95% + 暴露事件总线

协议对齐（现在就可以做）: 约定 Percept/Action JSON Schema

---

## 时间线（参考）

| 现在 | AI Friend v0.1收尾+v0.3情感, QAgent v0.2安全 | 约定协议 |
| 1个月 | AI Friend v0.4 Web, QAgent v0.3体验 | 双向联调 |
| 2个月 | 双方 v1.0 稳定版 | 新建仓库 |
| 3个月 | — | 合并完成 |

---

### 4.87 #87 [v1.0] 架构：LLM 抽象层 — 支持多模型提供商切换

- 链接：[#87](https://github.com/OrinVoss/ai-friend/issues/87)
- 标签：enhancement, architecture
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

## 现状

`KimiProvider` 直接硬编码 OpenAI-compatible 协议，无法切换模型提供商。

QAgent 已有 LLM 抽象层（`LLMProvider` trait + `factory`），支持 OpenAI API / llama.cpp / OpenVINO 三后端。合并后的项目需要统一这一层。

## 目标

定义统一的 LLM Provider 抽象层，支持多提供商切换。

## 设计

```
                    ┌─────────────────────┐
                    │   BaseLLMProvider    │  ← ABC / Trait
                    │   generate()         │
                    │   stream_generate()  │
                    │   supports_thinking()│
                    │   context_window()   │
                    │   estimate_tokens()  │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   DeepSeekProvider    OpenAIProvider     LocalProvider
   (云端 OpenAI 兼容)   (云端原生)         (llama.cpp/OV)
```

## 配置

```json
{
  "provider": "deepseek",
  "providers": {
    "deepseek": {
      "type": "openai_compat",
      "endpoint": "https://api.deepseek.com",
      "api_key_env": "DEEPSEEK_API_KEY",
      "model": "deepseek-v4-flash",
      "context_window": 180000
    },
    "local_qwen": {
      "type": "openai_compat",
      "endpoint": "http://127.0.0.1:8081/v1",
      "model": "qwen3.5-9b",
      "context_window": 32768
    }
  }
}
```

## 路由策略

| 场景 | 模型 |
|------|------|
| 日常聊天、快速回复 | 本地 Qwen（低延迟） |
| 深度推理、反思、梦境 | 云端 DeepSeek（强能力） |
| 代码生成/Claude Code | 保持现有链路 |

## 关联

- AI Friend 现有: `KimiProvider`（单后端）
- QAgent 现有: `LLMProvider` trait + factory（三后端）
- 本 issue 是合并后的统一方案

---

### 4.86 #86 [v1.0] 发布：Shutdown 与稳定性

- 链接：[#86](https://github.com/OrinVoss/ai-friend/issues/86)
- 标签：bug, infrastructure
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 必须稳定：

- [ ] 服务器 shutdown 时遍历 session 保存 personality、关闭 DB、WAL checkpoint
- [ ] 异常退出清理 react 状态
- [ ] proactive task 正确取消
- [ ] 30 分钟无人访问自动休眠（减少 API 费用）

关联：#27 #29

---

### 4.85 #85 [v1.0] 发布：前端体验打磨

- 链接：[#85](https://github.com/OrinVoss/ai-friend/issues/85)
- 标签：enhancement
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 前端体验：

- [ ] 角色名从 personality.name 动态读取
- [ ] CSS 变量集中管理
- [ ] 情绪指示器动画
- [ ] 消息气泡动画（segment 到达时）
- [ ] 移动端适配验证

关联：#26 #54

---

### 4.84 #84 [v1.0] 发布：文档完整

- 链接：[#84](https://github.com/OrinVoss/ai-friend/issues/84)
- 标签：documentation
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 文档必须覆盖全部系统：

- [ ] README 更新为 v1.0
- [ ] architecture.md 完整准确
- [ ] API 文档（WebSocket 协议、REST 端点）
- [ ] 配置文档（所有 config.json 字段说明）
- [ ] 人格定制指南（personality.json 完整参考）

关联：#50

---

### 4.82 #82 [v1.0] 发布：关键 Bug 清零

- 链接：[#82](https://github.com/OrinVoss/ai-friend/issues/82)
- 标签：bug
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 不允许存在已知严重 bug：

- [ ] process_message 绕过状态机导致 current_input 未设置
- [ ] 工具调用循环 128 token 不够
- [ ] personality.save 重复保存
- [ ] _tool_registry 初始 None
- [ ] CJK 终端换行宽度
- [ ] CLI 打字速度配置不生效
- [ ] WebSocket 异常静默

关联：#68 #70 #73 #74 #48 #49 #51

---

### 4.81 #81 [v1.0] 发布：Web 端生产可用

- 链接：[#81](https://github.com/OrinVoss/ai-friend/issues/81)
- 标签：enhancement, infrastructure
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 Web 端必须达到生产标准：

- [ ] 统一启动入口（start.py 选择 CLI/Web）
- [ ] 消除 main.py/session.py 重复初始化（create_agent 工厂）
- [ ] Web 持久化完整：shutdown 保存、WAL checkpoint、session 析构
- [ ] 每消息写 personality 改为每 10 轮（与 CLI 一致）
- [ ] CORS/速率限制
- [ ] Pydantic 输入验证
- [ ] 线程池耗尽风险修复

关联：#58 #57 #44 #24 #43 #46

---

### 4.80 #80 [v1.0] 发布：记忆系统语义化

- 链接：[#80](https://github.com/OrinVoss/ai-friend/issues/80)
- 标签：enhancement
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 的记忆系统必须超越关键词搜索：

- [ ] 向量语义检索：all-MiniLM-L6-v2 本地嵌入
- [ ] 虚假记忆检测与矛盾修正
- [ ] consolidation 去重 + _score_facts 写回 DB
- [ ] LongTermMemory session_id 过滤

关联：#4 #6 #21 #22 #40

---

### 4.79 #79 [v1.0] 发布：情感系统四层全部完成

- 链接：[#79](https://github.com/OrinVoss/ai-friend/issues/79)
- 标签：enhancement, architecture
- 创建：2026-05-29 | 更新：2026-05-29

#### 正文

v1.0 的情感系统必须完成四层架构：

- [x] Layer 2: 交叉调制 + 分速衰减（已完成）
- [x] Layer 3: 怨恨残留（已完成）
- [x] Layer 4: 情绪事件记忆（已完成）
- [ ] Layer 1: 多维输入 — 反驳链、回复速度趋势、态度一致性参与情绪计算
- [ ] 情感值归一化：达 ±1.0 极限后的重置与反弹
- [ ] CLI 路径破防/情感分析重复调用修复
- [ ] humor/sass 特质实际生效

关联：#7 #42 #69 #75 #20

---

### 4.60 #60 [v0.5] 重构：情绪模型从单向度升级为多维对话动态

- 链接：[#60](https://github.com/OrinVoss/ai-friend/issues/60)
- 标签：enhancement, architecture
- 创建：2026-05-28 | 更新：2026-05-28

#### 正文

## 现状

情绪更新主要靠 `analyze_sentiment(user_input)` 的 `sentiment` 值，过于依赖最后一条输入的内容正负。

```python
sentiment, sharing, energy = self.consolidator.analyze_sentiment(last_user_turn)
dv = user_sentiment * 0.3
```

## 问题

真实情绪是对话动态博弈的结果，不只是内容的正负：
- 用户连续反驳你 5 次，`arousal` 应该因为争论紧张而升高，不管内容 sentiment 是正是负
- 用户回得越来越快/短 → 可能不耐烦了
- 用户沉默很久后突然来一句 → 可能是深思熟虑

## 建议方案

新增「交互模式特征」维度，与内容 sentiment 并行参与情绪更新：

| 特征 | 计算方式 | 对情绪的影响 |
|------|----------|-------------|
| 连续反驳数 | 近 N 轮中 sentiment < -0.3 的连续次数 | arousal ↑，trust ↓ |
| 回复速度趋势 | 用户回复间隔的滑动窗口 | 加速 → anxiety ↑；减速 → anticipation ↓ |
| 态度一致性 | 当前 sentiment vs 历史均值 | 偏离大 → surprise ↑ |
| 对话深度 | 用户消息长度趋势 | 变长 → engagement ↑ |

结合方式：
```
情绪更新 = sentiment_impact × 0.5 + interaction_pattern_impact × 0.5
```

---

---

## 记录规范

新增已知问题时请按以下格式：

```markdown
## 序号. 问题标题

### 状态

- 已修复 / 观察中 / 待处理

### 详情

...问题描述...

### 为什么不现在修

...优先级说明...

### 建议修复方案

...长期方案...

### 相关文档

- ...
```
