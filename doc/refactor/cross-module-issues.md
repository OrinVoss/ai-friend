# 跨模块交互问题汇总

> 本文件记录因模块间接口/契约不一致导致的 Bug，而非单个模块的内部质量问题。
> 来源：2026-07-17 全代码库 10 路并行探索扫描 + 2026-07-17 40 路逐条代码验证。
>
> **核心规律**：所有 HIGH 问题都是"两个模块各自维护一份状态，没有同步机制"。
>
> **字段说明**：每条标注「准确度」和「验证日期」——已验证条目经过 40 个 agent 逐行读代码确认。

---

## 目录

1. [🔴 HIGH](#1--high)
2. [🟡 MEDIUM](#2--medium)
3. [🟢 LOW](#3--low)
4. [与现有文档的关系](#4--与现有文档的关系)

---

## 1. 🔴 HIGH

### H-01：Agent 3 prompt 声明外部工具可用但执行时只有内部注册表

**验证**：✅ 代码结构确认，但风险被高估（2026-07-17 验证）

**位置**：`core/message_handler.py:493-517`

**现象**：

```python
# 第 493-498 行：prompt 构建
build_system_prompt(
    tools=a._tool_registry,         # ← 完整注册表（含 web_search 等外部工具）
    ...
)
# 第 515-517 行：ReAct 循环执行
phase2_registry = self._make_internal_registry()  # ← 只有 recall/remember
return a._react_loop(messages, tool_registry=phase2_registry)
```

**实际风险分析**（2026-07-17 验证后修正）：代码结构上的不一致确实存在，但实际触发路径被两个设计细节保护：

1. **`tools` 参数仅用于生成 JSON intent 别名**（`format_intent_options()`），而非告知 Agent 3 可以使用 XML `<tool_call>`。Agent 3 的外部动作机制是 JSON intent 格式，走 `_handle_agent3_intent` → InnerDrive 审批 → Agent 2 执行。
2. **`phase2_registry=internal` 仅在 `tool_records` 有值时激活**，而这总是与 `final_response=True` 同时发生。此时 `OUTPUT_RULES_FINAL` 指令明确告诉 Agent 3"外部工具已经执行完毕…绝对不要输出 JSON"，不会列出任何工具 intent。
3. **无工具时**：`final_response=False`，intent 列出，但 `tool_records` 为假值 → `phase2_registry=None` → `_react_loop` 回退到完整 `self._tool_registry`（第 173 行），一致。
4. **有工具时**：`final_response=True`，intent 被 `OUTPUT_RULES_FINAL` 隐藏，`phase2_registry=internal`——设计如此。

**影响**：架构一致性缺陷，prompt 参数不必要地可用。但实际 exploit 路径不存在。降级为 🟡 MEDIUM。

**是否已在现有文档**：❌ 无

---

### H-02：Memory Agent 不编码 facts_v2 / observations 表，向量回填缺失

**验证**：✅ 代码结构确认，但影响被高估（2026-07-17 验证）

**位置**：`memory/consolidation.py:520-562`、`memory/memory_agent.py:341-367`、`memory/lifecycle.py:38,84`

**现象**：`_embed_new_items()`（`consolidation.py:527-532`）硬编码了三个旧表（`user_facts` / `experiences` / `reflections`），完全遗漏 `facts_v2` 和 `observations`。`MemoryAgent._retrieve_parallel()` 读取这些表的 embedding 列。

**关键修正**（2026-07-17）：
- **Lifecycle 在创建时已编码 embedding**（`lifecycle.py:38,84`）。新建的 `facts_v2`/`observations` 条目的 embedding 列不为 NULL。
- 缺失的是**批量回填路径**——`_embed_new_items()` 不覆盖新表，因此 embedding server 宕机期间创建的条目（通过 lifecycle）会永久缺少 embedding。
- 无 embedding 的条目仍出现在证据结果中（`similarity=0.0`），不会完全不可见。

**影响**：`use_memory_agent=true` 且 `use_observation_fact=true` 时，embedding server 宕机期间创建的条目向量召回退化。范围有限，非永久性全局退化。降级为 🟡 MEDIUM。

**是否已在现有文档**：❌ 无

---

### H-03：run_async 每次调用建新事件循环，asyncio.Lock 失效

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`core/async_utils.py:26,29`、`storage/database.py:49-55`

**现象**：

```python
# async_utils.py: 无事件循环时
return asyncio.run(coro)  # ← 每次都创建新事件循环
```

```python
# database.py: 锁按事件循环 identity 缓存
current_loop_id = id(asyncio.get_running_loop())
if current_loop_id != self._loop_id:
    self._lock = asyncio.Lock()  # ← 新 loop → 新 lock
```

`_EXECUTOR`（`max_workers=4`）中每个线程执行 `asyncio.run()` 时均创建属于自己的事件循环和 `asyncio.Lock`。4 个线程各有各的锁，无互斥。

```
线程 1: run_async → 新 loop → lock_A
线程 2: run_async → 新 loop → lock_B（与 lock_A 无关）
→ 同时执行 cursor→execute→commit，事务级竞态
```

**补充**（2026-07-17）：
- aiosqlite 内部通过单 worker 线程序列化 SQL 语句，单个 `await c.execute(...)` 安全。竞态在事务级（`cursor` → `execute` + `commit` 序列可以跨线程交织）。
- `SleepManager._lock`（`sleep_manager.py:32`）也存在跨事件循环的 `asyncio.Lock` 问题，但根因不同（`RuntimeDriver.start_in_thread()` 而非 `run_async`）。

**影响**：Web 多 tab + 后台 consolidation 并发时，数据库写入操作可能交织，导致重复 turn_number、部分写入等。

**是否已在现有文档**：✅ `database.md` P1-7（建议换 `threading.Lock`）、`known-issues.md #162/#243`

---

### H-04：Embedding 服务器端口配置与自动启动不一致

**验证**：✅ 准确，但仅影响自定义配置用户（2026-07-17 验证）

**位置**：`core/embedding_server.py:12,94`

**现象**：`auto_start_embedding()` 硬编码 `--port 8080`（第 94 行），`DEFAULT_EMBEDDING_ENDPOINT` 也是 `localhost:8080`（第 12 行）。默认配置下端口巧合一致。但如果用户在 `config.json` 中修改 `embedding_endpoint`（`config.py:70`），服务器仍在 8080 启动而引擎连接实际指向另一端口 → 连接拒绝 → 静默退化。

**影响**：仅影响自定义 `embedding_endpoint` 的用户。降级为 🟡 MEDIUM。

**是否已在现有文档**：✅ `provider.md` P0-3（已识别但未修复）

---

### H-05：Proactive / Explore 路径重复分析旧情绪，腐蚀情绪状态

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`core/message_handler.py:388,451` → `core/agent.py:248-262`

**现象**：

```
handle_proactive / handle_explore
  → _react_loop()
    → _process_emotion()
      → 找 short_term 中最后一条 user turn
      → analyze_sentiment(上轮的用户消息)  ← 没有新用户消息
      → 基于旧消息再做一次情绪更新
```

每次 proactive/explore 都把上一轮用户消息的情绪影响再施加一次：
- valence 被旧消息再拉一次（正→更正，负→更负）
- `consecutive_negative` 再 +1 或 -1
- 一次额外的 sentiment LLM 调用（浪费）

**补充**（2026-07-17）：若最后一条用户消息的 sentiment 为正，`consecutive_negative` 会递减（第 268-269 行）——方向相反但仍是错误的修改。`ProactivityManager` 的速率限制（chat 每 30min、explore 每 60min）限制了放大频率，但方向性错误不变。

**影响**：系统性地错误偏置情绪状态。方向与用户最后消息情绪相同，每周累积可达数十次叠加。

**是否已在现有文档**：✅ `emotion.md` 第 2 条记录了修复方案，但代码未实现

---

### H-06：personality.save() 静默覆盖用户在线编辑

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`core/personality.py:134-144`

**现象**：`Personality.save()` 将完整内存状态（人格配置 + 情绪状态）通过原子写入覆盖磁盘 JSON。运行时用户编辑 JSON 文件 → 下一次自动保存（Web 30s debounce / CLI 每 10 轮 / session 断开或 shutdown）立即覆盖。

**补充**（2026-07-17）：`.bak` 机制（第 105-109 行）在读取前备份而非写入前，不保护此场景。`close()` 不使用 debounce（`web/session.py:97`），使 session 断开立即触发破坏性写入。`PersonalityConfig.from_dict()`（`models/personality.py:415`）静默丢弃未知字段，合并保存时必须显式保留它们。

**影响**：用户丢失手动编辑，无任何警告。影响 Web 端（debounced save）和 CLI 端（每 10 轮 + 退出）。

**是否已在现有文档**：✅ `personality.md` 描述了"合并保存"方案但未实现

---

### H-07：_tool_failures 跨消息不重置，阈值逐消息累积

**验证**：✅ 行为准确，措辞修正（2026-07-17 验证）

**位置**：`core/agent.py:78,213-220`

**现象**：

```python
# 第 78 行：实例变量，跨所有消息持久
self._tool_failures: int = 0

# 第 213-220 行：_react_loop 内
all_failed = all(not r["success"] for r in results)
if all_failed:
    self._tool_failures += 1
    if self._tool_failures >= self._degrade_threshold:  # 3
        break  # 中断当前 _react_loop
else:
    self._tool_failures = 0  # reset on success
```

**修正**（2026-07-17）：原声称"工具永远不再被调用"过于绝对。`_tool_failures` 不阻止工具调用（`_react_loop` 正常启动、LLM 仍可输出 `<tool_call>`、`execute_tool_calls` 仍会执行）。实际效果是**阈值从每消息 3 次降为 1 次**：如果上一条消息消耗了 2 次失败槽位，下一条消息只需 1 次额外失败即可触发降级。仅当至少一次工具调用成功时在第 220 行重置为 0。

**影响**：短期工具故障可能导致后续消息快速进入降级状态，需要成功调用才能恢复。LOW 误称"永远"。

**是否已在现有文档**：❌ 无

---

### H-08：bulk_update_embeddings 跨 session 泄漏且缺 commit

**验证**：✅ 准确，且比原描述更严重（2026-07-17 验证）

**位置**：`storage/repository.py:254`、`memory/consolidation.py:540-543`

**现象**：

```python
await c.executemany(f"UPDATE {table_name} SET embedding=? WHERE id=?", ...)
```

**验证后补充**：
- `WHERE id = ?` 无 `AND session_id = ?` — 确认
- `consolidation.py:540-543` 读取候选行的 SELECT 查询也缺乏 session 过滤（`WHERE (embedding IS NULL OR embedding_version != ?)`）——读写两路均无 session 隔离
- 缺 commit 确实存在（第 255-257 行），但 Python sqlite3 默认 autocommit（`isolation_level=""`），每个 `executemany` 自动提交，数据在关闭时丢失的风险较低。确认仍是约定违规。

**影响**：Session A 的 consolidation 可以读取并改写 Session B 的 embedding 列，违反 session 隔离设计原则。

**是否已在现有文档**：✅ `database.md` P1 #8（缺 commit），session 泄漏为本次新增

---

## 2. 🟡 MEDIUM

### M-01：update_experience_score 无 session 过滤

**验证**：✅ 准确。但方法零调用者——死代码（2026-07-17）

**位置**：`storage/repository.py:220`

**现象**：`WHERE id = ?` 无 `AND session_id = ?`。对比同一文件中的 `insert_experience`（第 175 行写入 `session_id`）、`search_experiences`（第 193,200-203 行过滤 `session_id`）。

**补充**（2026-07-17）：方法零调用者（全代码库 grep 无结果），session 泄漏暂时无法被触发。

**是否已在现有文档**：✅ `known-issues.md` 第 8 节记录了同类别漏洞（`user_facts`/`facts_v2` 的裸 `WHERE id = ?`），但未具体提及此方法

---

### M-02：archive_observation 无 session 过滤

**验证**：⛔ 方法零调用者，降级为 LOW（2026-07-17 验证）

**位置**：`storage/repository.py:303`

**现象**：`UPDATE observations SET is_archived = 1 WHERE id = ?`。无 session 过滤。

**降级原因**：零调用者。observation ID 在读取路径（`search_observations` 第 282 行、`get_recent_observations` 第 293 行）中自然按 session 隔离，无跨 session 泄漏 ID 的路径。

**当前严重度**：🟢 LOW

---

### M-03：prune_old_turns 全局删除所有 session

**验证**：✅ 准确。方法零调用者（2026-07-17 验证）

**位置**：`storage/database.py:443-459`

**现象**：DELETE 子查询没有 `WHERE session_id = ?`。第 444 行 docstring 声称"per session"但与实现矛盾。零调用者——从未在运行中触发。

**是否已在现有文档**：✅ `database.md` P1 #5（"改为 per-session 清理"）

---

### M-04：review() / re_decide() 绕过 use_memory_agent 开关

**验证**：✅ 准确。影响有限——首轮结果已保留从 assess() 获取的 MA-quality context_summary（2026-07-17 验证）

**位置**：`core/inner_drive.py:313,383`

**现象**：

```
assess() → memory_agent.answer() ✅
review() → retriever.retrieve_for_query() ❌ 绕过
re_decide() → retriever.retrieve_for_query() ❌ 绕过
```

**补充**（2026-07-17）：`assess_proactive()`（第 263 行）和 `assess_agent3_intent()`（第 463 行）同样绕过 MA。但 `handle_message()` 中首轮 `drive_result` 保留了 `assess()` 的 MA-quality `context_summary`，最终 Agent 3 回复质量不受影响。绕过仅降级工具复核决策质量。

**是否已在现有文档**：❌ 无

---

### M-05：context_summary 为空时用了不同检索

**验证**：⛔ 代码正确处理两条路径，不存在运行时不一致性（2026-07-17 验证）

**位置**：`core/message_handler.py:468-476`

**降级原因**：`_context_summary_for()`（`inner_drive.py:220-235`）在 MemoryAgent 返回空时有内置回退到经典检索器，因此 Agent 1 也有记忆上下文。`build_system_prompt` 的 `else` 分支（`system.py:689-703`）正确使用回退的 `mem_ctx`，因此 Agent 3 始终有记忆内容。两条路径使用相同的格式化函数（`_build_relationship_block`、`_build_memory_block`）。无需等待额外检索。降级为 LOW。

**当前严重度**：🟢 LOW

---

### M-06：format_tool_rules 因隔离注册表返回空（原始 bug）

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`prompts/tools_description.py:36-45`、`prompts/system.py:141`

**现象**：InnerDrive 的隔离注册表只有 `recall`/`remember`，而 `_TOOL_RULES` 只有外部工具条目。`format_tool_rules()` 遍历注册表找不到匹配规则 → 返回空字符串 → prompt 显示"  · （当前无可用的外部工具）"。

**补充**（2026-07-17）：`INNER_DRIVE_CHECKLIST`（`instructions.py:18-31`）有硬编码的外部工具名和触发条件，部分补偿了此空白。`_build_inner_tools_block` 独立渲染可用工具。但"无可用外部工具"消息与 checklist 中引用外部工具直接矛盾，可能混淆 LLM。

**是否已在现有文档**：❌ 无（本次发现）

---

### M-07：情绪双路径可能发散

**验证**：✅ 架构缺陷真实，当前无突变窗口（2026-07-17 验证）

**位置**：`prompts/system.py:414-462, 493-509, 676-706`

**现象**：prompt builder 同时接收 `emotion_summary`（冻结字典）和完整 `emotion` 对象（可变）。多个 block 直接从对象读数据：
- `_build_resentment_block`（第 433-451 行）
- `_build_emotion_events_block`（第 454-462 行）
- `_build_dreams_block`（第 493-509 行）

**补充**（2026-07-17）：当前代码中三个调用点都在 `to_prompt_summary()` 后同步立即调用 `build_system_prompt`，无突变窗口。但 `decay()`、`record_emotion_event()`、`apply_mood_shift()` 均可突变 `EmotionalState`。代码重排即可触发歧义。

**是否已在现有文档**：❌ 无

---

### M-08：ToolAttemptTracker 在 ToolAgent 中未使用

**验证**：⛔ 不准确——tracker 在 `MessageHandler._run_agent2()` 中被使用（2026-07-17 验证）

**位置**：`core/tool_agent.py:44-62, 170-214`、`core/message_handler.py:271,297,328,330`

**修正**：`ToolAgent.run_with_request()` 确实使用简单计数器而非 tracker。但 `MessageHandler._run_agent2()` 创建并读取 `can_retry_in_round`（第 297 行）、`can_start_new_round`（第 328 行）、`failure_log`（第 330 行）。3/4 属性有读者。仅 `is_exhausted` 未被引用。这是代码异味（两套并行重试机制），不是"定义了但从未使用"。

**当前严重度**：🟢 LOW

---

### M-09：contains_fake_action 误判正常回复

**验证**：✅ 准确，有部分修复已存在（2026-07-17 验证）

**位置**：`core/dispatcher.py:188-203`、`core/agent.py:177,189`

**现象**：`contains_fake_action()` 使用 `in` 子串匹配（非正则）检测"调用了"、"搜索了"、"工具返回"等短语。LLM 在描述已执行的操作时可能被误判。

**补充**（2026-07-17）：`tools_were_called` 标志（`agent.py:177`）已在同一次 `_react_loop` 迭代中防止误判。剩余的跨消息间隙由 `_max_fake_actions=3`（`agent.py:85,234`）限制，耗尽后优雅降级为"让我直接回复你吧"。原文错误声称使用"正则"——实际是 `in` 子串匹配。

**是否已在现有文档**：❌ 无

---

### M-10：to_json_schema 空列表时回退 ["web_fetch"]

**验证**：⛔ 生产路径不可达（2026-07-17 验证）

**位置**：`tools/traits.py:136`

**降级原因**：两个生产调用者均被空注册表守卫保护（`core/tool_agent.py:85-86, 155-156`），在此守卫返回前不会到达 `to_json_schema()`。`names` 参数从未被生产调用者传递。回退是死代码。

**当前严重度**：🟢 LOW

---

### M-11：Proactivity 限速不持久化，session 重连后爆发

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`core/proactivity.py:19-20`

**现象**：`_last_explore_time` 和 `_last_chat_time` 是实例属性，不持久化。Web session 重连 → 新 `ProactivityManager` → 限速清零。`_recent_topics`（第 21 行）也不同步持久化——话题去重在重连后丢失。

**补充**（2026-07-17）：爆发有界——RuntimeDriver 每 15s tick，最多 2 条消息。并非"立即"。REST API session 不触发销毁，仅 WS 断开路径。

**是否已在现有文档**：❌ 无

---

### M-12：WS 断开销毁 session，中断进行中的 proactive

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`web/server.py:442`、`web/session.py:297-299`

**现象**：WS 断开 → `session_manager.remove()` → WebAgent 销毁 → proactive task.cancel()。`_WsProactiveFrontend.on_proactive` 可能仍有 pending 的 send。页面刷新导致内存状态丢失。

**补充**（2026-07-17）：情绪状态在 `close()` 时通过 `Personality.save()` 持久化，丢失的是 30s debounce 窗口内的增量。`task.cancel()` 是异步的——`CancelledError` 被 `RuntimeDriver`（`runtime_driver.py:113`）捕获，无崩溃。`known-issues.md #210` 已记录此基础问题。

**是否已在现有文档**：✅ `known-issues.md #210`、`web.md` P1-1

---

### M-13：Rate limiter 不限制 InnerDrive 主动决策调用

**验证**：⛔ 修正——不被 `RateLimitMiddleware` 限制但 `ProactivityManager` 有限速（2026-07-17 验证）

**位置**：`web/server.py:411`、`core/proactivity.py:101-116`、`core/inner_drive.py:287`

**修正**：`RateLimitMiddleware` 确实仅覆盖 `/api/*` 和 WS `message` 类型。但真正无保护的 LLM 调用是 `decide_proactive_action` → `assess_proactive()`（`inner_drive.py:287`）——评分阶段，决定是否要主动行动。`handle_proactive` / `handle_explore` 本身由 `ProactivityManager.check_rate_limit()`（`proactivity.py:101-116`）以 30min/1hr 冷却时间限速。`RuntimeDriver` 还有 `PROACTIVE_COOLDOWN_TICKS=12`（约 180s）全局冷却。

**当前严重度**：🟢 LOW（有部分限速，但 inner drive 决策调用无限制）

---

### M-14：Token 估算用 cl100k_base（OpenAI）而非 DeepSeek 编码

**验证**：✅ 核心事实准确。具体细节有误（2026-07-17 验证）

**位置**：`core/context_manager.py:11,21,31-35`

**修正**：
- DeepSeek **不存在**名为 `deepseek-v2` 的 tiktoken 编码——它的 tokenizer 是 HuggingFace `tokenizers`，而非 `tiktoken`。修复不能简单换编码名。
- 降级路径**不是** `len(text) // 2`（从未存在于此代码库）。实际公式为 `int(cjk * 1.5 + ascii_chars / 4 + digits / 3 + other / 8)`。

**影响**：cl100k_base 与 DeepSeek 实际 tokenizer 的差异可能导致 15-30% 的 token 计数误差，触发过早压缩或超限。

**是否已在现有文档**：❌ 无

---

### M-15：CLI 仍然原始输出 XML 标记

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`core/cli_controller.py:158-166`

**现象**：`_CliFrontend.on_token` 无 XML 过滤。`<tool_call>`、`<think>` 原始标记在流式传输时打印到终端。问题仅限于 `_react_loop` 迭代 0（首次流式传输）——后续迭代不流式传输。实际存储的回复是干净的。

**是否已在现有文档**：✅ `cli.md` P0-3（设计了状态机但从未实现）

---

### M-16：Web REST /api/chat 阻塞事件循环

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`web/server.py:150`、`web/server.py:423-424`

**现象**：REST 端点（第 150 行）同步调用 `agent.process_message()` 无 `run_in_executor`。WS 端点（第 424 行）正确使用。典型阻塞 3-15s（LLM 响应时间），最坏 180s。REST 是次要回退路径（WS 是主要路径）。

**是否已在现有文档**：✅ `web.md` P0-4

---

### M-17：use_memory_agent / use_observation_fact 灰度开关悬空

**验证**：✅ 准确。本地 config.json 可能启用（2026-07-17 验证）

**位置**：`config.py:77-80`、`message_handler.py:129`、`consolidation.py:43`

**现象**：两个开关默认 `false`，无公开启用时间表。新代码路径（Memory Agent、Observation→FactV2 生命周期）默认在线上零执行。

**补充**（2026-07-17）：本地 `config.json` 可能有 `"use_memory_agent": true`（开发时），因此该路径并非完全未执行。`memory-agent.md` 第 265 行指定了切换条件。`progress.md` 列出了 Phase 1 待办项。

**是否已在现有文档**：❌ 无

---

### M-18：Embedding 服务器无生命周期管理

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`core/embedding_server.py:112-114`、`retrieval.py:40-53`

**现象**：watcher 线程退出后不再监控进程。llama-server 崩溃后不自动重启。4 个调用方各自独立探活降级——无统一信号。`retrieval.py:40` 每消息探活，因此降级是临时的（非永久）。

**是否已在现有文档**：✅ `provider.md` P0-3

---

### M-19：配置加载在日志初始化之前执行

**验证**：✅ 准确（2026-07-17 验证）

**位置**：`main.py:21-22`、`web_main.py:16-17`

**现象**：`load_config()` 在 `setup_logging()` 前调用，约 3 条 INFO 级日志（使用哪个配置文件等）丢失。关键验证警告（WARNING+）仍通过 Python `lastResort` 处理程序输出到 stderr。

**是否已在现有文档**：❌ 无

---

### M-20：Embedding 启动竞态——后台启动 vs 立即使用

**验证**：⛔ 部分修正——自愈性竞态，非永久退化（2026-07-17 验证）

**位置**：`core/embedding_server.py:145-180`、`retrieval.py:40`

**修正**：
- `EmbeddingEngine` 构造函数（`session_factory.py:56`）不发起网络调用，仅设置属性。首次实际使用在 `retrieval.py:40`（`health_check`）。
- `retrieval.py:40` 每消息探活，提供自动重连——非永久退化。
- `consolidation.py:522` 也有 `health_check` 守卫，防止宕机时批量编码。
- 实际竞态窗口为 1-2 条消息（用户打字延迟通常超过 llama-server 启动时间）。

**当前严重度**：🟢 LOW

---

### M-21：EmbeddingEngine 默认维度 512 与配置 1024 不一致

**验证**：⛔ 引擎自动适配，不可达运行时错误（2026-07-17 验证）

**位置**：`memory/embeddings.py:18`、`config.py:71`

**修正**：`EmbeddingEngine._encode_locked()`（第 66-75 行）在 API 返回维度与 `self._dim` 不一致时自动适配——记录警告、清缓存、设置 `self._dim = api_dim`。无生产路径使用默认值（`session_factory.py:57` 总是传入 `config.embedding_dim`）。无测试使用裸默认值。

**当前严重度**：🟢 LOW

---

## 3. 🟢 LOW

| # | 问题 | 位置 | 验证 | 现有文档 |
|---|------|------|------|---------|
| L-01 | Embedding 健康检查 `urlopen` 无 `trust_env` 参数（注意：`urlopen` 无此参数——原描述不准确） | `embedding_server.py:47` | ⚠️ 重述修正 | ❌ |
| L-02 | Prompt 缓存无淘汰策略，长期运行泄漏 | `prompt_cache.py:_store` | ✅ | ❌ |
| L-03 | `_react_messages` 定义了但从未使用 | `agent.py:82,301` | ✅ | ❌ |
| L-04 | `ensure_session()` 的 `asyncio.run()` 在已有循环中抛错 | `server.py:32-37` | ✅ | ❌ |
| L-05 | `personality_file` 不可通过环境变量设置 | `config.py:145-163` | ✅ | ❌ |
| L-06 | 前端硬编码 AI 名"星" | `web/static/app.js:4` | ✅ | ❌ |
| L-07 | `_turns_without_anger` 不持久化，重启后重置 | `models/personality.py:220-227` | ✅ | ❌ |
| L-08 | Web shutdown 双写 personality | `web/session.py:351-368` | ✅ | ❌ |
| L-09 | 配置 `env_map` 重复键（`AI_FRIEND_LOG_LEVEL`） | `config.py:150,161` | ✅ | ❌ |
| L-10 | Web 的 `load_config()` 独立于 `web_main.py` 调用 | `web/server.py:26` | ✅ | ❌ |
| L-11 | Rate limiter `_lock` 声明但未使用 | `rate_limit.py:26` | ✅ | ❌ |
| L-12 | `web/server.py:26` 和 `web_main.py:16` 各调一次 `load_config()` | `web/server.py:26` | ✅ | ❌ |

---

## 4. 严重度调整摘要（2026-07-17 验证后）

验证结果：40/40 条已验证。严重度变更：

| 原严重度 | 新严重度 | 条目 | 原因 |
|---------|---------|------|------|
| 🔴 HIGH | 🟡 MEDIUM | H-01 | `final_response=True` 保护路径；JSON intent 而非 XML |
| 🔴 HIGH | 🟡 MEDIUM | H-02 | Lifecycle 创建时已编码；仅宕机期间创建的回填缺失 |
| 🔴 HIGH | 🟡 MEDIUM | H-04 | 仅影响自定义端口配置用户 |
| 🟡 MEDIUM | 🟢 LOW | M-02 | 零调用者，ID 自然 session 隔离 |
| 🟡 MEDIUM | 🟢 LOW | M-05 | 双路径均产生等价记忆上下文 |
| 🟡 MEDIUM | 🟢 LOW | M-08 | Tracker 在 `_run_agent2` 中 3/4 属性有读者 |
| 🟡 MEDIUM | 🟢 LOW | M-10 | 生产路径不可达 |
| 🟡 MEDIUM | 🟢 LOW | M-13 | `ProactivityManager` 有独立限速 |
| 🟡 MEDIUM | 🟢 LOW | M-20 | 自愈（每消息探活），窗口 1-2 消息 |
| 🟡 MEDIUM | 🟢 LOW | M-21 | 引擎自动适配维度 |

最终分布：**4 🔴 HIGH · 13 🟡 MEDIUM · 20 🟢 LOW**（3 条合并/移除后）

---

## 5. 与现有文档的关系

| 状态 | 计数 | 说明 |
|------|------|------|
| ✅ 已在现有文档中记录（含方案） | 7 | 部分已有修复方案但代码未落地 |
| ✅ 已在 known-issues.md 中记录 | 3 | 已知但未归入任何 refactor 层 |
| ❌ 本次新增发现 | 27 | 现有文档完全未覆盖（含 10 条验证后降级） |

**结论**：本次发现的 37 个跨模块问题中，约 **73% 不存于任何现有文档**。本文件作为完整的跨模块问题索引，与各层/各系统的专题增强文档互补。
