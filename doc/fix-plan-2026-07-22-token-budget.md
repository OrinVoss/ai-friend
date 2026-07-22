# 修复方案：Token 节省三刀（Agent 1 指令瘦身 / Agent 3 历史预算 + 按需查历史）

> 依据：2026-07-22 实测（logs 07-18~22 共 622 次调用、tok_in 101 万）：
> - Agent 1 inner_drive 贡献 **61%** 输入 token（315 次调用，均值 1966）；其 prompt 中 66% 是指令文本本身
> - Agent 3 单条 chars_in 13-19k，大头是 messages 数组对话历史（system prompt 仅 ~2.4k）
> - memory_agent / Agent 2 / consolidation 占比合理，**不动**
>
> 面向执行者：每项给出根因（文件/行/现状代码）、修法、测试与验收。严格按项执行，不要做清单之外的"顺手优化"。
> 项目：D:/桌面/编程作品/AI朋友，Python 3.12，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **840 passed + 2 skipped**，全部改完后必须全绿。
> 完成后在 `changes/` 写变更记录（命名 `changes/2026-07-22-token-budget.md`）。

---

## T1：Agent 1 指令瘦身

### 根因

`prompts/instructions.py` 的 `INNER_DRIVE_INTRO` + `INNER_DRIVE_CHECKLIST` + `INNER_DRIVE_DECISION_PRINCIPLES` + `INNER_DRIVE_USER_PRIORITY_RULES` + `INNER_DRIVE_OUTPUT_FORMAT` 合计约 1429 chars，占 Agent 1 system prompt 的 66%，每次调用原样发送。

### 修法

1. **无损压缩**：把五段重写为一段紧凑版（目标 ≤ 800 chars），保留全部硬规则：R1 的"只判意图不判人格"、时间查询短路、指代规则、用户指令优先、JSON 输出格式。去重复修辞与重复条款（"用户指令优先"目前说了两遍——DECISION_PRINCIPLES 和 USER_PRIORITY_RULES 语义重复，合并为一处）。
2. **工具跟进规则按需注入**：`prompts/system.py::_build_inner_drive_instructions_block` 中 `{followup_rules}` 部分，仅当 `tool_call_history` 非空（最近真的用过工具）时注入；为空时整块省略并去掉引导句。**允许给该 block 函数新增可选参数**（`tool_call_history=None` 时保持现状=总是注入，保证旧调用方兼容）。
3. **红线**：所有现有测试关于这些文案的断言若因措辞变化失败，按"保留硬规则语义"原则更新断言，不得删除规则。R1 的"不要推断用户的人格"与"永远不需要为此调用工具"两条款必须一字保留。
4. **缓存注意**：指令文本在静态缓存块中，静态块按 personality 文件版本失效、**不随 instructions.py 变更失效**——本项改动重启进程后才生效，验证时别被旧缓存误导。

### 测试

- 压缩后 prompt 仍含全部硬规则关键词（列清单逐条断言）。
- tool_call_history 为空时 followup_rules 块不出现；非空时出现。
- 量化：同一 mock 装配下 Agent 1 prompt 长度 ≤ 改前 × 0.7。

---

## T2：Agent 3 对话历史预算

### 根因

`core/message_handler.py::_build_messages` 的历史预算用 `COMPRESS_THRESHOLD`（80 万 token），等于没有预算——历史无限增长，单条 chars_in 13-19k。

### 预期说明（重要）

预算定为 16000 chars（用户决策，原方案 8000 的翻倍），而实测当前历史约 11-17k chars——**本项的主要作用是封顶未来增长，不会大幅削减当前用量**（预期节省 0-15% 而非更多）。这是体验优先的取舍，验收标准与此一致；若日后想真降，调小该配置即可，无需再改代码。

### 修法

1. `config.py` / `config.example.json` 新增 `react_history_budget_chars: int = 16000`（约 8-10k tokens 中文），`doc/config-reference.md` 同步。
2. `_build_messages` 在现有的 COMPRESS_THRESHOLD 判断**之外**加第二道预算：历史累计字符超过 `react_history_budget_chars` 时，从最旧开始丢弃（即倒序累加到预算即停，与现有 running_total 逻辑同构）。**不触发** compress_context——丢弃部分由记忆系统兜底（facts/experiences/insights 已在慢变块）。
3. system prompt 中"最近对话"块（Block 9）若有独立截断逻辑，保持现状不动。
4. 打一行 debug 日志：`[msg] history budget: kept=N dropped=M`。

### 测试

- 构造 50 条历史（每条 500 字符）：最终 messages 中非系统消息总字符 ≤ 预算，且保留的是最近的；dropped 计数正确。
- 短历史不受影响；现有 `_build_messages` 测试（去重/error_fallback/sleep 过滤）不降级。

---

## T3：`history_search` 内部工具（砍历史后的按需找回通道）

### 根因

历史被预算裁剪后，Agent 需要能按需查原始对话。现有 `recall` 查的是提炼记忆（facts/experiences/insights），不查原始 turn。

### 修法

工具支持三种用法：**关键词精确搜、向量语义搜、按轮次批量读**。

**1. `storage/repository.py` 新增两个方法**（列名以建表语句为准；`memory/long_term.py` 加同步包装，仿现有方法）：

```python
async def search_turns(self, query: str, limit: int = 6) -> list[dict]:
    """关键词 LIKE 搜索原始对话。原始 turn 存的是原文，
    LIKE 对关键词有效（与 facts 的整句 LIKE 问题不同）。"""
    async with self.db.cursor() as c:
        await c.execute("""
            SELECT turn_number, role, content, created_at FROM conversation_turns
            WHERE session_id = ? AND content LIKE ?
            ORDER BY turn_number DESC LIMIT ?
        """, (self.session_id, f"%{query}%", limit))
        return [dict(r) for r in await c.fetchall()]

async def get_turns_range(self, turn_from: int, count: int = 10) -> list[dict]:
    """按轮次范围批量读取（定位后看上下文 / 无参时取最新 count 条）。"""
    async with self.db.cursor() as c:
        if turn_from > 0:
            await c.execute("""
                SELECT turn_number, role, content, created_at FROM conversation_turns
                WHERE session_id = ? AND turn_number BETWEEN ? AND ?
                ORDER BY turn_number ASC
            """, (self.session_id, turn_from, turn_from + count - 1))
        else:
            await c.execute("""
                SELECT turn_number, role, content, created_at FROM conversation_turns
                WHERE session_id = ? ORDER BY turn_number DESC LIMIT ?
            """, (self.session_id, count))
        rows = [dict(r) for r in await c.fetchall()]
        rows.sort(key=lambda r: r["turn_number"])
        return rows
```

**2. `tools/memory_tools.py` 新增 `HistorySearchTool`**（仿 RecallTool）：

- `name() = "history_search"`，`is_internal = True`，`timeout_seconds = 15.0`
- 参数 schema（全部可选，但至少给一个）：
  - `query`：搜索词
  - `mode`：`"keyword"`（默认，精确 LIKE）或 `"semantic"`（向量语义）
  - `turn_number`：批量读取的起始轮次（给了它就走批量模式，忽略 query）
  - `limit`：返回条数（默认 6，上限 15）
- **语义模式实现**（embedding 可用时；不可用自动降级关键词并在输出中注明）：
  1. 取最近 200 条 turn。**注意**：现有 `get_recent_turns()` 只 `SELECT role, content`，**不含 turn_number**——先把它扩展为同时返回 `turn_number, created_at`（dict 加字段，先 grep 现有调用方确认兼容；不放心就另写 `get_recent_turns_full()`），缓存键依赖它
  2. 逐条编码：工具实例上挂 `{turn_number: np.ndarray}` 缓存，只编码新 turn（内部注册表已缓存复用，缓存生命周期与 session 一致）
  3. embedding 引擎经 `retriever` 的公开属性获取；若只有私有 `_embed`，在 `memory/retrieval.py` 加一个公共只读属性（仿 `extract_keywords` 公共化的先例），不要直接摸私有成员
  4. 与 query 向量算余弦，取 top N（阈值 0.5，防止硬凑）
- **批量模式**：`turn_number > 0` → `get_turns_range(turn_number, limit)`；`turn_number` 缺省且 query 为空 → 最新 limit 条
- 输出统一格式：`[#turn_number] 用户/你 (created_at): 内容`，单条截 200 字符、总输出截 1500 字符；无结果返回"没找到相关对话"
- `ALIASES = {"query": ("search", "keyword"), "turn_number": ("turn", "from_turn", "start")}`
- `description()` 必须引导 LLM 传**关键词**而非整句（"用一两个关键词，如 '摄影'、'歌名'；想语义模糊查找用 mode=semantic"）——keyword 模式是 LIKE，整句自然语言会重蹈 recall 整句 LIKE 的覆辙

**3. `core/message_handler.py::_make_internal_registry` 注册**（Agent 1/3 自动获得——内部工具块已由 #281 改为按注册表渲染，prompt 无需手改）。

**4. `prompts/instructions.py` 的 `AGENT3_BASE_INSTRUCTIONS` recall 提示行补充**：

> 想找原话用 history_search（recall 查提炼记忆；history_search 查原始对话，支持关键词、语义搜索和按轮次批量读）

### 测试

- `tests/test_memory_tools.py` 新增：
  1. 关键词命中返回结果、session 隔离、输出截断；
  2. 语义模式：mock embed（encode_single/encode 返回构造向量），语义相近但不含关键词的 turn 被召回；embed 不可用降级关键词；
  3. 批量模式：`turn_number=10, limit=3` 返回第 10-12 轮且升序；无参返回最新 N 条；
  4. 编码缓存：两次语义搜索只对新增 turn 编码。
- `tests/test_repository.py`：`get_recent_turns` 扩展后仍含原有字段且新增 turn_number/created_at，现有调用方（short_term 恢复路径）测试不降级。
- `_make_internal_registry` 现含 recall/remember/history_search 三个工具。
- 全量不降级。

---

## 验收（量化）

1. 全量测试全绿。
2. 用真实 DB 离线构建（仿 `token_measure_blocks.md` 的脚本）：Agent 1 prompt ≤ 改前 × 0.7。
3. 重启后生产观察（写进变更记录的观察点）：`/api/monitor` 中 source=inner_drive 的 chars_in 均值降到 ~2000 以下；react 的 chars_in 在长会话下不超过 ~19k。

## 不要做的事

- 不要动 memory_agent / Agent 2 / consolidation（占比合理）。
- 不要恢复短输入跳过（7-16 已决策移除）。
- 不要改 COMPRESS_THRESHOLD 与 compress_context 的既有触发（80 万 token 的兜底压缩保留，T2 是额外的历史预算）。
- 不要给 conversation_turns 加新列（用现有结构）。
- 不要把 history_search 暴露给 Agent 2（`EXTERNAL_TOOL_NAMES` 不动，它是内部工具）。
