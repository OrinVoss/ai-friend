# Layer 3 多阶段 Retrieval — 实施计划（供低成本模型执行，详版）

> 日期：2026-07-20。依据：`doc/refactor/layer3-retrieval/README.md`（设计）+ 代码现状核对。
> 本文档面向执行者：**所有需要知道的信息都在本文里**，不需要再去翻设计文档或猜代码结构。严格按项执行，不做清单之外的"顺手优化"。
> 项目：D:/桌面/编程作品/AI朋友，Python 3.13，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **691 passed + 2 skipped**，全部改完后必须全绿且不减少。

---

## 0. 现状核对（先看懂再动手）

Layer 3 设计（`README.md`）的五个组件约 70% 已建成，全部内嵌在 `memory/memory_agent.py`：

| 设计组件 | 现状位置 | 状态 |
|----------|----------|------|
| QueryClues | `memory/memory_agent.py:31` `MemoryClues` | ✅ 已有 |
| Parallel Retriever | `memory/memory_agent.py` `_retrieve_parallel()`（五源：facts_v2/observations/experiences/insights/relationship） | ✅ 已有，**串行** |
| Cross Verifier | `_cross_verify()` + `check_timeline`/`check_freshness`/`_check_consistency` + `SOURCE_QUALITY`/`WEIGHTS` + 相关性下限（MA-002） | ✅ 已有 |
| Reranker | 置信度六维加权 + top_sim 缩放 + 排序 | ✅ 雏形 |
| Context Builder | **缺失**——Agent 1 和 Agent 3 消费同一份全文（`_format_memory_answer`，`core/inner_drive.py:366`） | ❌ 本计划的核心 |

**设计偏离（有意，禁止改回）**：设计文档里 ParallelRetriever 用 TaskGroup 并行，**实现必须串行 await**——`storage/database.py::cursor()` 持有进程级 `threading.Lock`（H-03），同 loop 并发 acquire 会冻死事件循环（2026-07-20 生产死锁，`changes/2026-07-20-memory-agent-gather-deadlock.md`）。SQLite 查询毫秒级，串行无损失。

**当前数据流**（Agent 1/3 共享同一份全文）：

```
inner_drive.assess()
  ├─ _context_summary_for(user_input)          # core/inner_drive.py:341
  │    └─ memory_agent.answer() → _format_memory_answer(ma)   # 格式化成全文
  ├─ 全文 → build_inner_drive_prompt(memory_context_summary=全文)   # Agent 1 自己用
  └─ InnerDriveResult.context_summary = 全文   # 同一份传给 Agent 3
```

R1 memo 现状（`core/inner_drive.py:222` 构造、`:341` `_context_summary_for` 开头）：缓存的是**渲染后的字符串** `(user_input, cs)`。

---

## L3-1：抽取共享检索管线 `memory/retrieval_pipeline.py`（纯重构，行为零变化）

### 要平移的内容（从 `memory/memory_agent.py` 原样移动，不改逻辑）

1. **数据模型**（`:28-52`）：`MemoryClues`（改名 `QueryClues`）、`MemoryEvidence`。在 `memory_agent.py` 保留别名：
   ```python
   from memory.retrieval_pipeline import QueryClues, MemoryEvidence
   MemoryClues = QueryClues  # 向后兼容
   ```
   `MemoryAnswer` **留在** `memory_agent.py`（它是编排层输出，不是管线件）。
2. **常量与纯函数**：`STABLE_CATEGORIES`、`SOURCE_QUALITY`、`WEIGHTS`、`CONSISTENCY_SIM_THRESHOLD`、`RECALL_LIKE_INTENTS`、`parse_time_ranges`、`check_timeline`、`check_freshness`。
3. **检索主体**：`_retrieve_parallel` 的方法体抽成模块级函数（`memory_agent.py` 里的 `_retrieve_parallel` 五源串行查询 + 时间后过滤 + 相关性下限 + 排序截断的完整逻辑）：

   ```python
   # memory/retrieval_pipeline.py
   FACTS_POOL = 50
   OBS_POOL = 50
   EXP_POOL = 30
   INSIGHT_POOL = 20

   async def retrieve_bundle(
       repo, clues: QueryClues, max_evidence: int,
       relevance_floor: float, recall_like_intents: set = RECALL_LIKE_INTENTS,
   ) -> tuple[list[MemoryEvidence], Optional[float]]:
       """五源串行召回 + 时间后过滤 + 相关性下限 + 排序截断。
       返回 (evidences, top_sim)。禁止 asyncio.gather（cursor 锁死锁）。"""
   ```

   `MemoryAgent._retrieve_parallel` 改为薄封装：`return await retrieve_bundle(self.ltm.repo, clues, max_evidence, self._relevance_floor)`。类常量 `FACTS_POOL` 等移到模块级（memory_agent 里保留同名引用即可，测试若引用类常量注意兼容：`MemoryAgent.FACTS_POOL = FACTS_POOL`）。
4. **验证主体**：`_cross_verify`/`_detect_contradictions`/`_check_consistency` 抽成：

   ```python
   async def cross_verify(evidences, embed) -> tuple[list[MemoryEvidence], list[str], float]:
       """矛盾检测 + 一致性（批量编码余弦均值），返回 (evidences, contradictions, consistency)。"""
   ```

   `MemoryAgent._cross_verify` 改为薄封装。`_detect_contradictions` 是辅助函数一并移动。
5. **不移动**：`answer/verify_fact/correct_fact/batch_verify_facts` 编排、`_compute_confidence`、`_reconstruct*`、指代改写（`_needs_coreference`/`_rewrite_query`/`COREFERENCE_*`）、意图锚点（`INTENT_*`/`_classify_intent`）、`_sim`（如果 retrieve_bundle 需要则移过去并从这里 import）。

### 测试

- `tests/test_memory_agent.py` 33 个用例**必须原样全绿**（只能改 import 行，不能改断言；mock 的 `repo.get_active_insights` 等方法名不变）
- 新增 `tests/test_retrieval_pipeline.py`：
  ```python
  """Tests for memory/retrieval_pipeline.py"""
  import asyncio
  import unittest
  from unittest.mock import AsyncMock, MagicMock

  import numpy as np

  from memory.embeddings import EmbeddingEngine
  from memory.retrieval_pipeline import (QueryClues, retrieve_bundle,
                                         cross_verify, parse_time_ranges)
  from models.memory import EMBEDDING_VERSION, FactV2


  def _unit(vec):
      v = np.array(vec, dtype=np.float32)
      return v / np.linalg.norm(v)


  def _repo(facts=None, observations=None, experiences=None,
            relationship=None, insights=None):
      repo = MagicMock()
      repo.get_active_facts_v2 = AsyncMock(return_value=facts or [])
      repo.get_recent_observations = AsyncMock(return_value=observations or [])
      repo.get_recent_experiences = AsyncMock(return_value=experiences or [])
      repo.get_all_relationships = AsyncMock(return_value=relationship or {})
      repo.get_active_insights = AsyncMock(return_value=insights or [])
      return repo


  class TestRetrieveBundle(unittest.TestCase):
      def test_serial_order_and_pools(self):
          """五源串行查询，相关性下限过滤低相似证据。"""
          qvec = _unit([1, 0, 0, 0])
          blob = EmbeddingEngine.vec_to_bytes(qvec)
          good = FactV2(id=1, category="preference", fact_key="最爱食物",
                        fact_value="披萨", confidence=0.9, status="active",
                        embedding=blob, embedding_version=EMBEDDING_VERSION,
                        updated_at="2026-07-19 10:00:00")
          repo = _repo(facts=[good])
          clues = QueryClues(raw_query="披萨", query_embedding=blob)
          evidences, top_sim = asyncio.run(
              retrieve_bundle(repo, clues, max_evidence=10, relevance_floor=0.35))
          self.assertEqual(len(evidences), 1)
          self.assertAlmostEqual(top_sim, 1.0, places=3)

      def test_recall_intent_exempts_floor(self):
          """intent 为 recall 时跳过相关性下限。"""
          # 构造：facts 无向量（不可测量），intent='recall' → 全保留
          ...

  class TestCrossVerify(unittest.TestCase):
      def test_contradiction_detected(self):
          """同 category|key 不同值 → 双方标记 is_contradicted。"""
          ...
  ```

### 验收

- `git diff memory/memory_agent.py` 只有代码移动和 import 调整，无逻辑变化
- `tests/test_memory_agent.py` 33 用例全绿 + 全量不减少

---

## L3-2：RetrievalProfile + ContextBuilder（放 `memory/retrieval_pipeline.py`）

### 完整规格

```python
class ContextBuilder:
    """按 Agent Profile 把同一份验证过的记忆渲染成不同上下文。"""

    def build(self, profile: str, ma) -> str:
        """ma: MemoryAnswer（有 answer/confidence/evidences/contradictions/
        needs_more_evidence 字段）。ma 为 None 时返回 ""。"""
        if ma is None or not getattr(ma, "answer", ""):
            return ""
        if profile == "agent1":
            return self._build_full(ma)
        if profile == "agent3":
            return self._build_light(ma)
        if profile == "agent2":
            return ""
        raise ValueError(f"unknown retrieval profile: {profile}")
```

### agent1 全文（`_build_full`）——与现状**逐字一致**

现状逻辑在 `core/inner_drive.py:366 _format_memory_answer`，原样搬入（函数保留并改为调用 ContextBuilder，避免其他调用方回归）：

```
=== 记忆检索（置信度 {ma.confidence:.0%}）===
{ma.answer}
⚠️ 矛盾记忆：{ma.contradictions[:3] 用"； "连接}（如需引用请先向用户确认）   ← 仅 contradictions 非空时
（以上记忆证据不足，当作待确认信息，不要当作确定事实）   ← 仅 needs_more_evidence 或 confidence < 0.4 时
```

### agent3 轻量（`_build_light`）——新形态

规则：
- 从 `ma.evidences` 取：fact 类前 3 条、experience 类前 2 条、relationship 类前 1 条
- **剔除**：`is_contradicted=True`、`source_type == "insight"`、`source_type == "observation"` 的证据
- 不加置信度/矛盾/待验证标注（Agent 3 不做判断，给干净输入）
- 目标长度 ≤ agent1 全文的 40%

输出格式：

```
=== 相关记忆 ===
- {fact.content}                      # 原样，如 "preference|最爱食物: 披萨"
- {experience.content}                # 原样，如 "[开心] 一起聊歌单"
关系：trust=1.00，familiarity=0.80，intimacy=0.76，playfulness=0.72   ← 取 relationship 证据 content 去掉"关系指标："前缀；没有则省略该行
```

若过滤后 fact/experience 都为空且无 relationship → 返回 `""`（不输出空块）。

### 测试（追加进 `tests/test_retrieval_pipeline.py`）

```python
class TestContextBuilder(unittest.TestCase):
    def _ma(self, evidences, answer="答案文本", confidence=0.8,
            contradictions=None, needs_more_evidence=False):
        m = MagicMock()
        m.answer, m.confidence = answer, confidence
        m.evidences = evidences
        m.contradictions = contradictions or []
        m.needs_more_evidence = needs_more_evidence
        return m

    def _ev(self, source_type, content, is_contradicted=False):
        return MemoryEvidence(source_type=source_type, source_id=1,
                              content=content, confidence=0.8,
                              timestamp="2026-07-20 10:00:00",
                              is_contradicted=is_contradicted)

    def test_agent1_full_golden(self):
        ma = self._ma([], answer="事实文本", confidence=0.82,
                      contradictions=["A vs B"], needs_more_evidence=False)
        out = ContextBuilder().build("agent1", ma)
        self.assertEqual(out, "=== 记忆检索（置信度 82%）===\n事实文本\n"
                              "⚠️ 矛盾记忆：A vs B（如需引用请先向用户确认）")

    def test_agent3_light_filters(self):
        evs = [
            self._ev("fact", "preference|最爱食物: 披萨"),
            self._ev("fact", "event|坏事实: x", is_contradicted=True),
            self._ev("insight", "洞察[pattern]：假设"),
            self._ev("experience", "[开心] 聊歌单"),
            self._ev("relationship", "关系指标：trust=1.00，familiarity=0.80"),
        ]
        out = ContextBuilder().build("agent3", self._ma(evs))
        self.assertIn("最爱食物: 披萨", out)
        self.assertIn("[开心] 聊歌单", out)
        self.assertIn("trust=1.00", out)
        self.assertNotIn("坏事实", out)      # 矛盾剔除
        self.assertNotIn("洞察", out)        # insight 不进轻量
        self.assertNotIn("置信度", out)      # 无标注

    def test_agent3_caps_and_empty(self):
        # 4 条 fact 只取 3；空过滤结果返回 ""
        ...

    def test_agent2_empty(self):
        self.assertEqual(ContextBuilder().build("agent2", self._ma([])), "")

    def test_none_answer(self):
        self.assertEqual(ContextBuilder().build("agent1", None), "")
```

---

## L3-3：Agent 3 接入轻量上下文（一次检索，两种渲染）

### 改动点 1：memo 改存 MemoryAnswer 对象（`core/inner_drive.py`）

构造（`:222` 附近）：

```python
# 改前
self._cs_memo: tuple[str, str] | None = None
# 改后
self._cs_memo: tuple[str, object] | None = None  # (user_input, MemoryAnswer | None)
```

新增私有方法（替换 `_context_summary_for` 里 MemoryAgent 分支的调用方式）：

```python
def _memory_answer_for(self, user_input: str):
    """R1 memo：同一条消息内 memory_agent.answer() 只跑一次。
    返回 MemoryAnswer 或 None（未启用/失败/空 query）。"""
    if self._cs_memo and self._cs_memo[0] == user_input:
        return self._cs_memo[1]
    ma = None
    if self._memory_agent is not None and (user_input or "").strip():
        try:
            from core.async_utils import run_async
            ma = run_async(self._memory_agent.answer(user_input))
        except Exception as e:
            logger.warning(f"[inner_drive] memory agent failed, retriever fallback: {e}")
            ma = None
    self._cs_memo = (user_input, ma)
    return ma
```

### 改动点 2：`_context_summary_for` 用 agent1 profile 渲染

```python
def _context_summary_for(self, user_input: str) -> str:
    """Agent 1 prompt 的记忆上下文（全文）。memo 缓存 MemoryAnswer，
    Agent 3 的轻量渲染复用同一对象（L3-3）。"""
    if not (user_input or "").strip():
        # F3: 空 query 走 retriever 概览（现状逻辑保留）
        return self._build_context_summary(self._retriever.retrieve_for_query(user_input))
    ma = self._memory_answer_for(user_input)
    if ma is not None:
        from memory.retrieval_pipeline import ContextBuilder
        full = ContextBuilder().build("agent1", ma)
        if full:
            logger.debug(f"[inner_drive] context via memory agent (confidence={ma.confidence})")
            return full
        logger.debug("[inner_drive] memory agent empty, retriever fallback")
    return self._build_context_summary(self._retriever.retrieve_for_query(user_input))
```

注意：`_format_memory_answer` 改为薄封装 `return ContextBuilder().build("agent1", ma)`，保留它因为 `assess()` 里没用到但别处可能引用（grep 确认；若仅一处则直接替换调用点）。

### 改动点 3：`assess()` 里 Agent 3 的 context_summary 换轻量渲染

`assess()` 现状（`:245` 起）：`cs = self._context_summary_for(user_input) if use_ma else ""`，末尾 `result.context_summary = cs`。

改为：

```python
use_ma = self._memory_agent is not None
mem_ctx = None
ma = self._memory_answer_for(user_input) if use_ma else None
cs = self._context_summary_for(user_input) if use_ma else ""
if not use_ma:
    mem_ctx = self._retriever.retrieve_for_query(user_input)
    cs = self._build_context_summary(mem_ctx)
# Agent 3 的轻量上下文（L3-3）：与 Agent 1 的同一份记忆，按 profile 渲染
if ma is not None:
    from memory.retrieval_pipeline import ContextBuilder
    light = ContextBuilder().build("agent3", ma)
    cs_agent3 = light if light else cs   # 轻量为空（无相关记忆）时退回 cs
else:
    cs_agent3 = cs
# 二期 4.2：挂念浮现块照旧拼接在 cs_agent3 上
care_block = self._surface_care_for(user_input)
if care_block:
    cs_agent3 = f"{cs_agent3}\n\n{care_block}" if cs_agent3 else care_block
```

末尾所有 `result.context_summary = cs` 改为 `result.context_summary = cs_agent3`（含解析失败兜底、recall 循环返回、max iterations 兜底三处）。`review`/`re_decide`/`assess_agent3_intent` 的 `cs` 是给 Agent 1 自己看的，**保持全文**（`review` 结果的 `context_summary` 本来就留空，不动）。

### 测试（追加进 `tests/test_inner_drive.py`）

```python
class TestAgent3LightContext(unittest.TestCase):
    """L3-3：一次 answer，Agent 1 全文 / Agent 3 轻量，memo 语义不变。"""

    def setUp(self):
        # 参照 TestContextSummaryMemo 的构造：memory_agent.answer 返回
        # MagicMock(answer="...", confidence=0.9, contradictions=[],
        #           needs_more_evidence=False, evidences=[...])
        ...

    def test_context_summary_is_light_for_agent3(self):
        result = self.agent.assess("本地有这个歌吗")
        # Agent 3 收到轻量形态
        self.assertNotIn("置信度", result.context_summary)
        # Agent 1 的 prompt 仍是全文（sys_prompt 里有置信度标注）
        sys_prompt = self.provider.generate.call_args[0][0][0]["content"]
        self.assertIn("置信度", sys_prompt)

    def test_memo_single_answer_per_message(self):
        self.agent.assess("同一问题")
        self.memory_agent.answer.assert_called_once()
```

---

## L3-4：文档收尾

1. `doc/refactor/layer3-retrieval/README.md`：状态改「P0-P2 已实现（2026-07-2X，`changes/2026-07-2X-layer3-retrieval-pipeline.md`）」，勾选 P0/P1/P2 清单；P3 的 fact_extractor 注明「仅留 profile 桩，未接线（现状提取输入为整批 turn 文本，够用）」。
2. `doc/refactor/progress.md`：Layer 3 行状态改「主体完成」，明细打勾。
3. `doc/architecture.md`：检索段落加一句「多阶段检索管线共享（retrieval_pipeline.py），ContextBuilder 按 Agent Profile 渲染」。
4. 新建 `changes/2026-07-2X-layer3-retrieval-pipeline.md`（中文）：设计映射表（本文第 0 节）、抽取清单、agent3 轻量格式示例、串行检索的设计偏离、验收结果。

---

## 明确不做

- **不并行化检索**（第 0 节设计偏离）
- **不改 MemoryAgent 置信度算法/阈值/prompt**（纯移动 + 渲染分流）
- **不动 Agent 3 其他 prompt 组成**（人格/情绪/对话历史块原样）
- **不接 fact_extractor**（L3-2 只留 profile 桩）
- **不动 Agent 2**（现状即不读记忆，符合设计）
- **不改 `review`/`re_decide` 的 cs 用法**（Agent 1 自用，保持全文）

## 执行顺序与验收总表

| 顺序 | 项 | 风险 | 关键验收 |
|------|----|------|----------|
| 1 | L3-1 抽取管线 | 中（大移动） | `tests/test_memory_agent.py` 33 用例原样全绿 |
| 2 | L3-2 Profile + Builder | 低 | `test_agent1_full_golden` 逐字一致 |
| 3 | L3-3 Agent 3 轻量接入 | 低 | react tok_in 下降；memo 单发 |
| 4 | L3-4 文档 | 无 | changes + 打勾 |

全部完成后：`python -m pytest tests --ignore=tests/real_api -q` 全绿（≥691 passed + 2 skipped），新测试文件 +10 用例左右。
