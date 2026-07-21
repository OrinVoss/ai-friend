# Layer 3 多阶段 Retrieval 管线抽取与 Agent 3 轻量上下文

日期：2026-07-21

## 背景

Layer 3 设计（`doc/refactor/layer3-retrieval/README.md`）的五个组件约 70% 已建成，全部内嵌在 `memory/memory_agent.py` 中。本次改动把共享的检索/验证逻辑抽取为独立管线 `memory/retrieval_pipeline.py`，并新增 `ContextBuilder` 按 Agent Profile 渲染同一份记忆，使 Agent 3 获得轻量上下文、Agent 1 仍保留完整置信度标注。

## 设计映射表

| 设计组件 | 实现位置 | 说明 |
|----------|----------|------|
| QueryClues | `memory/retrieval_pipeline.py:QueryClues` | 原名 `MemoryClues`，保留别名 |
| Parallel Retriever | `retrieve_bundle()` | 五源串行查询（见下方设计偏离） |
| Cross Verifier | `cross_verify()` | 矛盾检测 + 批量一致性 |
| Reranker | `MemoryAgent` 置信度六维加权 | 逻辑未动，仅随本体保留 |
| Context Builder | `ContextBuilder` | agent1 全文 / agent3 轻量 / agent2 空 |

## 抽取清单

1. `memory/retrieval_pipeline.py` 新建：
   - 数据模型：`QueryClues`、`MemoryEvidence`
   - 常量：`SOURCE_QUALITY`、`STABLE_CATEGORIES`、`CONSISTENCY_SIM_THRESHOLD`、`WEIGHTS`、`RECALL_LIKE_INTENTS`、四个 `*_POOL`
   - 纯函数：`parse_time_ranges`、`check_timeline`、`check_freshness`、`_sim`
   - 异步函数：`retrieve_bundle(repo, clues, max_evidence, relevance_floor)`、`cross_verify(evidences, embed)`
   - 类：`ContextBuilder`

2. `memory/memory_agent.py` 改为薄封装：
   - `MemoryClues = QueryClues` 别名向后兼容
   - `_retrieve_parallel` 调用 `retrieve_bundle`
   - `_cross_verify` 调用 `cross_verify`
   - 保留 `MemoryAnswer`、编排 API、置信度算法、重构逻辑、指代改写、意图分类

3. `core/inner_drive.py`：
   - `_cs_memo` 缓存 `MemoryAnswer` 对象（不再是格式化字符串）
   - 新增 `_memory_answer_for(user_input)`，保证同一条消息内只调用一次 `memory_agent.answer()`
   - `_context_summary_for` 使用 `ContextBuilder.build("agent1", ma)` 渲染全文
   - `_format_memory_answer` 改为 `ContextBuilder.build("agent1", ma)` 薄封装
   - `assess()` 内为 Agent 3 单独计算 `cs_agent3 = ContextBuilder.build("agent3", ma)`，挂念浮现块仍拼接到 `cs_agent3`
   - 所有 `result.context_summary = cs` 改为 `= cs_agent3`

## Agent 3 轻量格式示例

输入证据：
- fact: `preference|最爱食物: 披萨`
- experience: `[开心] 一起聊歌单`
- relationship: `关系指标：trust=1.00，familiarity=0.80`

Agent 3 收到：

```
=== 相关记忆 ===
- preference|最爱食物: 披萨
- [开心] 一起聊歌单
关系：trust=1.00，familiarity=0.80
```

过滤规则：
- 剔除 `is_contradicted=True`
- 剔除 `source_type == "insight"` 和 `source_type == "observation"`
- fact 最多 3 条、experience 最多 2 条、relationship 最多 1 条
- 无置信度/矛盾/待验证标注

## 设计偏离：检索必须串行

设计文档中 `ParallelRetriever` 使用 `asyncio.TaskGroup` 并行，但实现必须串行 await。原因：`storage/database.py::cursor()` 持有进程级 `threading.Lock`（H-03），同事件循环内并发 acquire 会冻死事件循环（2026-07-20 生产死锁，见 `changes/2026-07-20-memory-agent-gather-deadlock.md`）。SQLite 查询毫秒级，串行无损失。`retrieve_bundle` 函数注释中显式禁止 `asyncio.gather`。

## 测试

- `tests/test_memory_agent.py`：34 用例全绿（原 33 用例，无断言改动）
- `tests/test_retrieval_pipeline.py`：新增 15 用例，覆盖 retrieve_bundle / cross_verify / ContextBuilder
- `tests/test_inner_drive.py`：新增 `TestAgent3LightContext`（2 用例）
- `tests/test_memory_agent_integration.py`：更新断言以反映 Agent 3 轻量上下文

全量回归：`python -m pytest tests --ignore=tests/real_api -q` → 691+15=706 passed, 2 skipped。

## 明确不做

- 不并行化检索
- 不改 MemoryAgent 置信度算法/阈值/prompt
- 不动 Agent 3 其他 prompt 组成
- 不接 fact_extractor（仅留 profile 桩）
- 不动 Agent 2
- 不改 `review`/`re_decide` 的 `cs` 用法（Agent 1 自用，保持全文）
