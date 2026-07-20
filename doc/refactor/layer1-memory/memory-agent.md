# Memory Agent —— 记忆智能体设计

> 目标：把「记忆检索 + 交叉验证 + 重构回答」封装成一个独立的 Memory Agent，替代当前散在 `memory/retrieval.py` 中的被动查询函数。
> 状态：P0/P1 已实现（2026-07-16，`memory/memory_agent.py`，`tests/test_memory_agent.py` 21 用例）；P2/P3 待实施。

---

## 1. 背景与问题

当前 `MemoryRetriever` 的问题：

- 只返回相似度 TopK 列表，不判断对错
- 没有交叉验证：同一主题的多条证据是否一致？
- 没有证据链：Agent 3 拿到记忆后不知道来源和置信度
- 没有主动纠错：用户更正后旧 Fact 可能仍被检索出来
- 没有睡眠式巩固：consolidation 是即时提取，不是回放验证

---

## 2. 核心概念

Memory Agent 是一个独立的智能体，负责：

1. **查找**：基于多线索从 `observations` / `facts_v2` / `experiences` / `relationship` 中检索
2. **交叉验证**：检查多条证据是否一致，标记矛盾或过时信息
3. **重构回答**：组装最终结论，附带置信度和证据来源

Memory Agent 本体是**确定性推理组件**，不调用 LLM。职责边界显式拆成两层：

```
MemoryAgent（确定性，可单测）
  ├── _extract_clues()   → 结构化线索
  ├── _retrieve()        → 证据列表
  ├── _cross_verify()    → 验证后的证据（含置信度）
  └── _reconstruct()     → 结构化 MemoryAnswer

语义重构层（可选，独立 LLM 调用，不属于 Memory Agent 本体）
  MemoryAnswer → LLM → 自然语言回复
```

- 确定性部分输入输出可预测，可单元测试
- LLM 只在最后一步介入，且**可选**：Agent 3 可以直接消费 `MemoryAnswer` 的结构化字段（answer / confidence / evidences），不必经过 LLM 重构
- 避免「确定性组件悄悄变成 LLM Agent」，语义重构策略也可独立替换

---

## 3. 工作流程

```
用户问题 / Agent 1 请求
    ↓
Memory Agent
    ├── 1. 查询编码（Query Encoding）
    │      ├── 整句查询 → embedding 向量（召回主力，本地向量模型）
    │      ├── 时间解析：仅时间词用规则，转绝对日期范围
    │      └── 不做关键词/实体提取（由向量隐式处理）
    ├── 2. 并行检索（Parallel Retrieval）
    │      ├── observations：原始存档，找直接证据
    │      ├── facts_v2：经验证事实，找结论
    │      ├── experiences：共同回忆，找事件
    │      └── relationship：关系指标，找上下文
    ├── 3. 交叉验证（Cross Verification）
    │      ├── 同一主题的多条证据是否一致？
    │      ├── 时间线是否吻合？
    │      ├── Fact 的 verification_count 是否足够？
    │      ├── 有没有被标记为 contradicted / decayed？
    │      └── 最近 Observation 是否支持旧 Fact？
    ├── 4. 重构回答（Reconstruction）
    │      ├── 组装最终结论（自然语言或结构化）
    │      ├── 标注置信度（0.0 ~ 1.0）
    │      ├── 列出证据来源（observation_ids, fact_ids, episode_ids）
    │      └── 标记不确定或需要进一步验证的部分
    ↓
输出 MemoryAnswer
```

---

## 4. 数据模型

```python
@dataclass
class MemoryClues:
    """从查询中提取的线索。召回以向量为主，不做关键词匹配。"""
    raw_query: str                            # 原始查询
    query_embedding: bytes | None = None      # 整句查询向量（召回主力）
    time_ranges: list[tuple[str, str]] = field(default_factory=list)  # 绝对日期范围
    intent: str | None = None                 # 可选，向量锚点分类


@dataclass
class MemoryEvidence:
    """一条证据。"""
    source_type: Literal["observation", "fact", "experience", "relationship"]
    source_id: int
    content: str
    confidence: float
    timestamp: str
    is_contradicted: bool = False
    is_stale: bool = False


@dataclass
class MemoryAnswer:
    """Memory Agent 的最终输出。"""
    answer: str                               # 重构后的自然语言答案
    confidence: float                         # 整体置信度 0.0 ~ 1.0
    evidences: list[MemoryEvidence]           # 证据链
    needs_more_evidence: bool = False         # 是否证据不足
    contradictions: list[str] = field(default_factory=list)  # 发现的矛盾点
    suggestions: list[str] = field(default_factory=list)     # 建议的后续动作
```

---

## 5. 核心类

```python
class MemoryAgent:
    """记忆智能体：负责检索、交叉验证、重构回答。"""

    def __init__(self, ltm: LongTermMemory, lifecycle: MemoryLifecycleManager,
                 retriever: MemoryRetriever, embedding_engine=None):
        self.ltm = ltm
        self.lifecycle = lifecycle
        self.retriever = retriever
        self._embed = embedding_engine

    async def answer(self, query: str, max_evidence: int = 10) -> MemoryAnswer:
        """回答用户关于过去的问题。"""
        clues = await self._extract_clues(query)
        evidences = await self._retrieve_parallel(clues, max_evidence)
        verified = await self._cross_verify(evidences)
        return self._reconstruct(query, verified)

    async def verify_fact(self, fact_id: int) -> MemoryAnswer:
        """主动验证某个 Fact 是否仍然成立。"""
        fact = await self.ltm.repo.get_fact_v2_by_id(fact_id)
        if not fact:
            return MemoryAnswer(answer="Fact not found", confidence=0.0)
        clues = MemoryClues(raw_query=f"{fact.fact_key} {fact.fact_value}")
        clues.query_embedding = await self._encode(clues.raw_query)
        evidences = await self._retrieve_parallel(clues, max_evidence=10)
        verified = await self._cross_verify(evidences, target_fact=fact)
        return self._reconstruct_fact_verification(fact, verified)

    async def correct_fact(self, old_fact_id: int, new_value: str,
                           source_turn: int) -> FactV2:
        """用户纠正某个 Fact。"""
        # 1. 先取旧 Fact，并创建 Observation（不可变 archive）
        # Observation 内容保留「旧值 → 新值」完整上下文：
        # 一期只做简单值替换，但未来支持复杂纠正（实体归属变化、
        # 「我当时说的是气话」这类置信度修正）时，需要原始纠正语境。
        old_fact = await self.ltm.repo.get_fact_v2_by_id(old_fact_id)
        old_value = old_fact.fact_value if old_fact else "unknown"
        obs = await self.lifecycle.observe(
            content=f"用户纠正：{old_value} → {new_value}",
            source_turn=source_turn,
            created_by="user_correction",
        )
        # 2. 标记旧 Fact 为 contradicted
        await self.lifecycle.contradict_fact(old_fact_id, reason="user correction")
        # 3. 创建新 Fact
        new_fact = await self.lifecycle.promote_fact(
            observation_ids=[obs.id],
            category=old_fact.category if old_fact else "preference",
            key=old_fact.fact_key if old_fact else "unknown",
            value=new_value,
            confidence=1.0,
            stability=0.8,
            freshness=1.0,
            importance=0.9,
            created_by="user_correction",
        )
        return new_fact

    # ── 内部方法 ──

    async def _extract_clues(self, query: str) -> MemoryClues:
        """编码查询向量并解析时间范围。不做关键词匹配，召回全靠向量。"""
        pass

    async def _retrieve_parallel(self, clues: MemoryClues,
                                 max_evidence: int) -> list[MemoryEvidence]:
        """并行从多个来源检索证据。"""
        pass

    async def _cross_verify(self, evidences: list[MemoryEvidence],
                            target_fact: FactV2 | None = None) -> list[MemoryEvidence]:
        """交叉验证证据的一致性。"""
        pass

    def _reconstruct(self, query: str, evidences: list[MemoryEvidence]) -> MemoryAnswer:
        """基于验证后的证据重构最终答案。"""
        pass
```

---

## 6. 使用场景

### 6.1 Agent 1 回忆用户信息

```python
# 在 InnerDriveAgent.assess() 中
memory_answer = await memory_agent.answer(user_input)
context_summary = memory_answer.answer  # 直接传给 Agent 3
```

### 6.2 用户问「我们上次聊了什么」

```python
# 在 Agent 3 中
memory_answer = await memory_agent.answer("我们上次聊了什么")
reply = f"我们上次聊了{memory_answer.answer}（置信度 {memory_answer.confidence:.0%}）"
```

### 6.3 系统定期验证旧 Fact

```python
# 在 MemoryConsolidator GC 阶段
for fact in old_facts:
    result = await memory_agent.verify_fact(fact.id)
    if result.confidence < 0.3:
        await lifecycle.decay_fact(fact.id)
```

### 6.4 用户纠正

```python
# 在 MessageHandler 中
if user_says_correction:
    await memory_agent.correct_fact(old_fact_id, new_value, turn_id)
```

---

## 7. 与现有组件的关系

| 现有组件 | 与 Memory Agent 的关系 |
|----------|----------------------|
| `MemoryRetriever` | 被 Memory Agent 调用，提供基础检索能力 |
| `MemoryLifecycleManager` | 被 Memory Agent 调用，负责 Fact 生命周期操作 |
| `MemoryConsolidator` | 负责生成 Observation；Memory Agent 负责使用 |
| `FactChecker` | 提供矛盾检测能力，被 `_cross_verify` 复用 |
| `InnerDriveAgent` | 调用 Memory Agent 获取 context_summary |
| `Agent 3` | 调用 Memory Agent 回答用户关于过去的问题 |

### 7.1 集成注意事项

- **Agent 3 Prompt 需要理解置信度**：`MemoryAnswer` 带 `confidence` 和 `contradictions`，Agent 3 的 Prompt 模板要显式处理——低置信度记忆标为「待确认」，矛盾信息显式展示，而不是当作确定事实
- **`InnerDriveAgent.assess()` 改造**（✅ 已实现 2026-07-16，`use_memory_agent` 开关默认 false）：用 `memory_agent.answer()` 替代 `retriever.retrieve_for_query()`，把 `answer` 字段写入 `context_summary` 传给 Agent 3。具体替换点：

  ```python
  # 现状（core/inner_drive.py）
  memory_context = await retriever.retrieve_for_query(user_input)  # 相似度 TopK，不判断对错

  # 替换后
  memory_answer = await memory_agent.answer(user_input)
  memory_context = memory_answer.answer  # 带置信度和证据链
  ```

  注意这一个替换点**同时升级两个消费方**：Agent 1 自己的决策依据（prompt 的记忆块经 `build_inner_drive_prompt(memory_context_summary=...)` 注入），和经 `context_summary` 传给 Agent 3 的记忆摘要（#160 的复用链路），不需要改 Agent 3 的调用侧。MemoryAgent 失败时自动回退到 retriever 旧路径。

  灰度策略：配置开关 `use_memory_agent`（默认 false），与 `use_observation_fact` 同款模式——新旧路径并存，实测对比召回质量后再切默认。
- **复用 `FactChecker` 时的性能**：`_cross_verify()` 调用 `is_contradiction()` 时应复用已有 embedding，不产生新的 embedding 计算；批量矛盾检测做缓存，避免 O(n²) 次调用
- **Observation 不可变性**：`Repository` 只提供 `observations` 的 INSERT/SELECT，不提供 UPDATE 接口（vough 封存）

---

## 8. 实现优先级

### P0：基础版本

- [x] `MemoryClues` / `MemoryEvidence` / `MemoryAnswer` 数据模型
- [x] `MemoryAgent.answer()`：向量检索 + 简单交叉验证
- [x] `MemoryAgent.correct_fact()`：用户纠正通道
- [x] `tests/test_memory_agent.py`

### P1：交叉验证增强 + 最小版睡眠巩固

- [x] `_extract_clues()`：时间解析（统一为绝对日期范围）+ 意图向量锚点（可选）
- [x] `_cross_verify()`：分类型时间线检查、矛盾检测、stale 检测
- [x] `verify_fact()`：主动验证旧 Fact
- [x] **批量验证（最小版睡眠式巩固）**：低负载时取最近未验证的 Fact，批量跑 `verify_fact()`，低置信度的触发 decay——只复用已有能力，先解决「旧 Fact 无人验证」的核心问题
- [x] **相关性下限（MA-002）**：可测量证据低于 `memory_agent_relevance_floor`（默认 0.35）直接丢弃，置信度按 `top_sim / memory_agent_relevance_full`（默认 0.75）缩放；recall/summarize 意图豁免——解决「无关输入也召回 10 条噪声、置信度虚高」的问题 ✅ 已完成（2026-07-18，`changes/2026-07-18-memory-agent-relevance-floor.md`）

### P2：完整交叉验证与 GC

- [x] 集成 embedding 做语义相似度验证（verify_fact 内 FactChecker 语义矛盾检测）
- [x] 矛盾向上传播：Fact 被推翻时，依赖它的 Insight 标记为可疑（needs_more_evidence + confidence 降权）✅ 2026-07-20
- [x] 完整 GC：decay / obsolete / archive / expire_due_insights（merge 保持占位，语义近重复合并推迟）✅ 2026-07-20
- [x] `_extract_clues()` LLM 版本（向量锚点检测指代 + LLM 改写自足查询）✅ 2026-07-20

（以上三项见 `changes/2026-07-20-memory-agent-p2.md`）

### P3：完整睡眠巩固与可视化（优先级最低，按需）

- [ ] 模式提炼：从 Observation 聚类中发现新模式（周期触发）
- [ ] 跨会话模式发现
- [ ] 语义重构 LLM 层（Agent 3 可直接用 `MemoryAnswer.answer`，这层是锦上添花）
- [ ] 证据链可视化（Web 端展示）

> 说明：原「语义重构」从 P2 降为 P3。Agent 3 直接消费结构化 `MemoryAnswer` 即可，LLM 重构不是核心路径。

---

## 9. 与 HMS 的对应关系

| HMS 概念 | Memory Agent 对应实现 |
|----------|----------------------|
| 原始事实封存（vough） | `observations` 表只增不改 |
| 现实解读（mimi） | `_reconstruct()` 结合当下生成答案 |
| 碎片化线索重构 | `_extract_clues()` + `_retrieve_parallel()` |
| 交叉核对事实 | `_cross_verify()` |
| 自进化机制 | `verify_fact()` + 睡眠式巩固 |
| 承认出错 | `correct_fact()` + `contradict_fact()` |

---

## 10. 验收标准

1. 用户问「我最喜欢吃什么」→ Memory Agent 返回答案 + 证据来源 + 置信度
2. 同一主题有多条矛盾 Observation → 检测到矛盾并在 answer 中标注
3. 用户纠正「我不喜欢吃披萨了」→ 旧 Fact 被 contradicted，新 Fact confidence=1.0
4. 30 天前的旧 Fact，最近无 Observation 支持 → verify_fact() 返回低置信度并建议 decay
5. 全量测试不降级
