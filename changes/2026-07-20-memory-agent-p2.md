# Memory Agent P2：矛盾向上传播 + Insight 证据池 + 向量锚点指代解析

日期：2026-07-20

## 背景

Layer 1 二期收尾（`memory-agent.md` P2 清单）。三块：

1. **矛盾向上传播**（`memory-agent-verification.md` 3.7）：Fact 被推翻时，从它推理出的 Insight 不能继续作为有效记忆被检索——「前提倒了，结论必须连带质疑」。
2. **Insight 进证据池**：insights_v2 上线后（`changes/2026-07-20-insight-replaces-reflection.md`），Memory Agent 的证据池还只有 fact/observation/experience/relationship，结构化假设没参与记忆回答。
3. **指代解析**：《国际歌》案例的根治——用户问「本地有这个歌吗」，「这个歌」指 AI 自己上一条回复里的《国际歌》。prompt 引导（`changes/2026-07-20-coreference-prompt-and-history-filter.md`）只能缓解，根治是在检索前把指代解析成具体实体。

## 改动（全部本人实现，未用子代理）

### 1. 矛盾向上传播

- `storage/repository.py` 新增 `mark_insight_suspect(insight_id, factor=0.5)`：`needs_more_evidence=1` + confidence ×0.5，**保持 active 等待重新评估**，不直接废弃。
- `memory/lifecycle.py::contradict_fact`：标记 Fact contradicted 后，扫描 active insights，`evidence_fact_ids` 含该 Fact 的全部 `mark_insight_suspect`；传播失败不影响主流程（try/except + warning）。

### 2. Insight 证据池（`memory/memory_agent.py`）

- `MemoryEvidence.source_type` 增加 `"insight"`；`SOURCE_QUALITY["insight"]=0.6`（假设级，与 observation 同级、低于 fact）。
- `_retrieve_parallel` 新增 `INSIGHT_POOL=20`：active insights 作为证据参与向量召回、相关性下限、交叉验证全套流程；`needs_more_evidence` 的内容里显式标注「（待验证）」、verification_count=0。

### 3. 指代解析（向量锚点 + LLM 改写）

- **检测不用关键字**（与同文件 INTENT_ANCHORS 同一哲学）：`COREFERENCE_ANCHORS`（「这个是什么意思」「那首歌叫什么」「它在哪里」「后来怎么样了」等指代性问句锚点），query 向量与锚点最大余弦 ≥ 0.65 才触发。无向量环境安全回退不触发。
- **改写**：触发后用 LLM 结合最近对话（`history_fn`）把 query 改写为自足形式（`COREFERENCE_REWRITE_PROMPT`，`prompts/templates.py`），改写结果重新编码后再检索；LLM 失败/输出异常一律回退原 query。
- 构造新增 `llm_fn`/`history_fn`；`core/message_handler.py` 接线（provider + short_term 800 token 历史）。

### 4. GC 完整性核对（无代码变更）

`garbage_collect` 现有：decay + merge_duplicates + archive_old_observations + expire_due_insights。`merge_duplicates` 保持占位——`UNIQUE(session_id, category, fact_key)` 已防精确重复，语义级近重复合并（需要向量聚类 + 合并策略）是独立特性，推迟到后续迭代。

## 测试（+9）

- `tests/test_memory_lifecycle.py::TestContradictionPropagation`（3）：引用者被标记、无引用空转、传播失败不破坏主流程
- `tests/test_memory_agent.py::TestInsightEvidence`（2）：insight 进证据池、待验证标注
- `tests/test_memory_agent.py::TestCoreferenceRewrite`（4）：指代命中改写、非指代不调 LLM、LLM 失败回退、无 llm_fn 不改写

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**672 passed + 2 skipped**（664 → 672）

## 备注

- 指代锚点阈值 0.65 是起点值，生产上按 `[memory_agent] coreference anchor sim=` debug 日志调。
- 指代解析每次触发多一次小 LLM 调用（max_tokens=128），非指代 query 零额外成本。
