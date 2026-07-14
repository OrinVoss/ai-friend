# Layer 1: Memory 生命周期重构 — 实施方案

## 数据模型

### Observation（原始观察）

```python
@dataclass
class Observation:
    id: Optional[int]
    content: str                    # 观察内容
    episode_turn_start: Optional[int]
    episode_turn_end: Optional[int]
    source_turn: Optional[int]
    created_by: str                 # consolidation / user_correction / tool_result
    created_at: str
    session_id: str
    embedding: Optional[bytes]
    embedding_version: int
    is_archived: bool
```

### FactV2（经验证的事实）

```python
@dataclass
class FactV2:
    id: Optional[int]
    category: str
    fact_key: str
    fact_value: str
    confidence: float
    stability: float
    freshness: float
    importance: float
    status: Literal["active", "decayed", "merged", "obsolete", "contradicted"]
    source_observation_ids: list[int]
    verification_count: int
    last_verified_at: Optional[str]
    created_by: str
    created_at: str
    updated_at: str
    session_id: str
    embedding: Optional[bytes]
    embedding_version: int
```

## 核心类

`memory/lifecycle.py::MemoryLifecycleManager`

```python
async def observe(...) -> Observation
async def find_similar_observations(...) -> list[Observation]
async def promote_fact(...) -> FactV2
async def verify_fact(fact_id: int)
async def contradict_fact(fact_id: int, reason: str)
async def decay(now: Optional[datetime])
async def merge_duplicates()
async def archive_old_observations(max_age_days: int)
async def garbage_collect()
```

## 流程

```
对话回合
    ↓
MemoryConsolidator.consolidate()
    ↓
创建 Observation（整段 turn_text）
    ↓
提取 facts（原有 FACT_EXTRACTION_PROMPT）
    ↓
同时写旧 user_facts 和新 facts_v2
    ↓
每 5 次 consolidation 触发 lifecycle GC
```

## 二期计划

1. 新增 `insights_v2` 表
2. 替换开放式 Reflection Prompt 为 JSON hypothesis Prompt
3. `MemoryConsolidator` 生成 Insight 时写入 `insights_v2`
4. Retrieval 切换到 `facts_v2` + `insights_v2`
5. 删除旧 `user_facts` / `reflections` 写入逻辑
6. 写一次性迁移脚本导入旧数据
