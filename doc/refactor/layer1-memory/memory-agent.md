# Memory Agent —— 记忆智能体设计

> 目标：把「记忆检索 + 交叉验证 + 重构回答」封装成一个独立的 Memory Agent，替代当前散在 `memory/retrieval.py` 中的被动查询函数。
> 状态：设计文档，待实现。

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

它不是 LLM Agent，而是一个**确定性推理组件**（可以可选地调用 LLM 做最终语义重构）。

---

## 3. 工作流程

```
用户问题 / Agent 1 请求
    ↓
Memory Agent
    ├── 1. 线索提取（Clue Extraction）
    │      ├── 时间线索：今天/昨天/上周/2026年7月
    │      ├── 实体线索：人名、地点、物品、事件
    │      ├── 关系线索：我和用户、用户和他人
    │      ├── 情绪线索：开心/难过/生气/焦虑
    │      └── 关键词：直接搜索词
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
    """从查询中提取的线索。"""
    time_ranges: list[tuple[str, str]]        # (start, end) ISO format
    entities: list[str]                       # 人名、地点、物品
    relationships: list[str]                  # 关系描述
    emotions: list[str]                       # 情绪标签
    keywords: list[str]                       # 直接搜索词
    raw_query: str                            # 原始查询


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
        clues = MemoryClues(
            time_ranges=[], entities=[fact.fact_key], relationships=[],
            emotions=[], keywords=[fact.fact_value], raw_query=fact.fact_value,
        )
        evidences = await self._retrieve_parallel(clues, max_evidence=10)
        verified = await self._cross_verify(evidences, target_fact=fact)
        return self._reconstruct_fact_verification(fact, verified)

    async def correct_fact(self, old_fact_id: int, new_value: str,
                           source_turn: int) -> FactV2:
        """用户纠正某个 Fact。"""
        # 1. 创建 Observation（不可变 archive）
        obs = await self.lifecycle.observe(
            content=f"用户纠正：{new_value}",
            source_turn=source_turn,
            created_by="user_correction",
        )
        # 2. 标记旧 Fact 为 contradicted
        await self.lifecycle.contradict_fact(old_fact_id, reason="user correction")
        # 3. 创建新 Fact
        old_fact = await self.ltm.repo.get_fact_v2_by_id(old_fact_id)
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
        """从查询中提取线索。一期可用正则/关键词，二期可用 LLM。"""
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

---

## 8. 实现优先级

### P0：基础版本（1~2 天）

- [ ] `MemoryClues` / `MemoryEvidence` / `MemoryAnswer` 数据模型
- [ ] `MemoryAgent.answer()`：关键词检索 + 简单交叉验证
- [ ] `MemoryAgent.correct_fact()`：用户纠正通道
- [ ] `tests/test_memory_agent.py`

### P1：交叉验证增强（2~3 天）

- [ ] `_extract_clues()`：时间、实体、关系提取
- [ ] `_cross_verify()`：时间线检查、矛盾检测、stale 检测
- [ ] `verify_fact()`：主动验证旧 Fact

### P2：语义重构（2~3 天）

- [ ] 集成 embedding 做语义相似度验证
- [ ] 可选 LLM 调用：把验证后的证据交给 LLM 生成自然语言答案
- [ ] 证据链可视化（Web 端展示）

### P3：睡眠式巩固（Layer 1 二期）

- [ ] 在 `MemoryConsolidator` 中调用 `MemoryAgent.verify_fact()` 做批量验证
- [ ] 基于验证结果自动 decay / obsolete 旧 Fact

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
