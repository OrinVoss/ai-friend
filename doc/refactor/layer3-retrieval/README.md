# Layer 3: 多阶段 Retrieval

## 目标

从单一的「Embedding TopK」检索，升级为多阶段、分 Agent、可交叉验证的检索体系。

## 当前状态

**P0-P2 已实现**（2026-07-21，见 `changes/2026-07-21-layer3-retrieval-pipeline.md`）。

- `memory/retrieval_pipeline.py` 已抽取为共享检索管线（QueryClues / retrieve_bundle / cross_verify / ContextBuilder）。
- `ContextBuilder` 按 Agent Profile 渲染：Agent 1 全文、Agent 3 轻量、Agent 2 空。
- Agent 3 的 `context_summary` 已切换为轻量上下文；Agent 1 prompt 仍使用全文。
- P3 的 `fact_extractor` 仅留 profile 桩，未接线（现状提取输入为整批 turn 文本，够用）。

## 核心问题

| 问题 | 表现 |
|------|------|
| 所有 Agent 共享同一份 Context | Tool Agent 也读取人格/情绪/回忆 |
| 检索只有相似度 | 「相似」不等于「相关」 |
| 没有时间感知 | 向量做不了时间算术，「上周聊了什么」无法按时间过滤 |
| 没有交叉验证 | 返回什么就用什么，不判断对错 |
| React 默认读 Reflection | Reflection 是结论，不是证据，容易自我强化 |

## 整体架构

```
Query
  ↓
Query Analyzer（查询编码 + 时间解析）
  ├── 整句查询 → embedding 向量（召回主力，不做关键词匹配）
  └── 时间线索（规则解析 → 绝对日期）
  ↓
Parallel Retriever（多源并行检索）
  ├── facts_v2
  ├── observations
  ├── experiences
  ├── relationship
  └── insights（二期）
  ↓
Cross Verifier（交叉验证）
  ├── 一致性检查
  ├── 时间线检查
  ├── 矛盾检测
  └── 新鲜度检查
  ↓
Reranker（重排序）
  ├── 按 Agent 类型加权
  ├── 按置信度加权
  └── 按新鲜度加权
  ↓
Context Builder（按 Agent Profile 组装）
  ├── Agent 1: facts + episodes + insights
  ├── Agent 2: 不读 Memory
  └── Agent 3: hot_facts + recent_episodes + relationship
  ↓
Agent-specific Context
```

## 各 Agent 的 Retrieval Profile

| Agent | 可读取的记忆 | 读取方式 | 目的 |
|-------|-------------|----------|------|
| **Agent 1 (InnerDrive)** | facts_v2, experiences, insights, relationship | 完整交叉验证 | 决策依据 |
| **Agent 2 (ToolAgent)** | 不读 Memory | - | 纯工具执行 |
| **Agent 3 (Roleplay)** | hot_facts, recent_episodes, relationship | 简化检索，不做深度交叉验证 | 回复参考 |
| **Fact Extractor** | observations, conversation_turns | 原始文本检索 | 提取候选事实 |
| **Memory Agent** | 全部 | 完整交叉验证 | 回答记忆问题 |

## 核心组件

### Query Analyzer

负责把自然语言查询拆解为结构化线索：

```python
@dataclass
class QueryClues:
    raw_query: str
    query_embedding: bytes | None = None      # 召回主力，不做关键词匹配
    time_ranges: list[tuple[str, str]] = field(default_factory=list)
    intent: Literal["recall", "verify", "compare", "summarize"] | None = None
```

### Parallel Retriever

并行调用多个 Repository 方法：

```python
class ParallelRetriever:
    async def retrieve(self, clues: QueryClues, limit: int = 20) -> RetrievalBundle:
        async with asyncio.TaskGroup() as tg:
            facts_task = tg.create_task(self._search_facts(clues))
            obs_task = tg.create_task(self._search_observations(clues))
            exp_task = tg.create_task(self._search_experiences(clues))
            rel_task = tg.create_task(self._get_relationship())
        return RetrievalBundle(
            facts=facts_task.result(),
            observations=obs_task.result(),
            experiences=exp_task.result(),
            relationship=rel_task.result(),
        )
```

### Cross Verifier

对检索结果做一致性验证：

```python
class CrossVerifier:
    async def verify(self, bundle: RetrievalBundle) -> VerifiedBundle:
        # 1. 同一主题的证据是否一致？
        # 2. 时间线是否吻合？
        # 3. Fact 是否被 contradicted / decayed？
        # 4. 最近 Observation 是否支持旧 Fact？
```

### Context Builder

根据 Agent 类型组装最终上下文：

```python
class ContextBuilder:
    def build(self, agent_type: str, bundle: VerifiedBundle) -> str:
        if agent_type == "agent1":
            return self._build_full_context(bundle)
        elif agent_type == "agent3":
            return self._build_light_context(bundle)
        elif agent_type == "agent2":
            return ""
```

## 与 Memory Agent 的关系

Memory Agent 是 Layer 3 的**用户**，它调用 Parallel Retriever 和 Cross Verifier 来完成自己的交叉验证逻辑。Layer 3 提供的是通用检索基础设施。

## 实现优先级

### P0：基础多源检索

- [x] `QueryClues` 数据模型（`memory/retrieval_pipeline.py`）
- [x] 五源串行检索（`retrieve_bundle`；强制串行，见设计偏离）
- [x] `ContextBuilder` 按 Agent 类型组装
- [x] `tests/test_retrieval_pipeline.py`

### P1：交叉验证

- [x] `cross_verify` 一致性/时间线/矛盾/新鲜度检查
- [x] 与 `FactChecker` 集成（仍由 `MemoryAgent` 在 `verify_fact` 中调用）
- [x] 相关测试并入 `tests/test_retrieval_pipeline.py`

### P2：Reranker

- [x] 按 Agent Profile 加权排序（ContextBuilder 过滤 + 截断）
- [x] 置信度 + 新鲜度 + 相关性综合评分（保留在 MemoryAgent 置信度算法中）

### P3：不同 Agent 不同上下文

- [x] Agent 3 只读 hot_facts + recent_episodes + relationship（轻量上下文）
- [x] Agent 2 不读 Memory（`ContextBuilder.build("agent2")` 返回空）
- [x] Agent 1 可读 insights（全文上下文）
- [ ] `fact_extractor` 未接线：仅 profile 桩，现状提取输入为整批 turn 文本，够用

## 依赖

- Layer 1 Memory 生命周期：稳定的数据模型和 `facts_v2` / `observations`
- Layer 2 Prompt Budget：Context Builder 的输出需要符合预算分配

## 相关文档

- `doc/refactor/layer1-memory/memory-agent.md`
- `doc/refactor/layer2-prompt/README.md`
