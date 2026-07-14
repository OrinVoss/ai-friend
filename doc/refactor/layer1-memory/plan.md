# Layer 1: Memory 生命周期重构 — 实施方案

## 1. 背景与问题

当前 `MemoryConsolidator.consolidate()` 直接做四件事：

1. `_extract_facts()` → 直接写 `user_facts` 表
2. `_summarize_experience()` → 直接写 `experiences` 表
3. `_generate_reflection_*()` → 直接写 `reflections` 表
4. `_update_relationship()` → 更新关系指标

存在的问题：

- 单次对话观察被直接当成永久事实，缺少验证过程
- Reflection 输出开放式结论，没有假设/证据/置信度
- 没有来源字段，无法追踪哪个 Agent、哪条 episode 产生的记忆
- Fact 只有 confidence，没有 freshness/stability/importance 多维度
- 没有衰减/合并/删除机制，长期运行会自我污染

## 2. 目标状态

```
对话回合 (Turn)
    ↓
Observation（原始观察，低置信度，随时写入）
    ↓ 多次验证 / 用户确认 / LLM 判断
Fact（经验证的事实，带 confidence/freshness/stability/importance）
    ↓ 跨事实推理，带证据链
Insight / Reflection（假设，带 evidence/confidence/needs_more_evidence/expires_at）
    ↓ 过期 / 证据失效 / 矛盾
Garbage Collection（merge / decay / contradict / obsolete / archive）
```

一期目标：完成 **Observation → Fact** 两层生命周期，新旧系统双写，默认关闭。
二期目标：完成 **Insight** 层，替换 Reflection，Retrieval 切换到新表。

## 3. 数据模型

### 3.1 新增表

```sql
-- 原始观察
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,              -- 观察内容（自然语言）
    episode_turn_start INTEGER,         -- 来源 episode 起始 turn
    episode_turn_end INTEGER,           -- 来源 episode 结束 turn
    source_turn INTEGER,                -- 具体触发 turn
    created_by TEXT NOT NULL DEFAULT 'consolidation',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL DEFAULT 'default',
    embedding BLOB,
    embedding_version INTEGER DEFAULT 0,
    is_archived INTEGER DEFAULT 0
);

-- 事实（从 observation 提升）
CREATE TABLE facts_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    stability REAL DEFAULT 0.5,
    freshness REAL DEFAULT 1.0,
    importance REAL DEFAULT 0.5,
    status TEXT DEFAULT 'active',       -- active / decayed / merged / obsolete / contradicted
    source_observation_ids TEXT DEFAULT '[]',
    verification_count INTEGER DEFAULT 0,
    last_verified_at TIMESTAMP,
    created_by TEXT NOT NULL DEFAULT 'consolidation',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL DEFAULT 'default',
    embedding BLOB,
    embedding_version INTEGER DEFAULT 0,
    UNIQUE(session_id, category, fact_key)
);
```

索引：

```sql
CREATE INDEX idx_observations_session ON observations(session_id, is_archived, created_at);
CREATE INDEX idx_facts_v2_session ON facts_v2(session_id, status, confidence);
```

### 3.2 Python 模型

```python
@dataclass
class Observation:
    id: Optional[int] = None
    content: str = ""
    episode_turn_start: Optional[int] = None
    episode_turn_end: Optional[int] = None
    source_turn: Optional[int] = None
    created_by: str = "consolidation"
    created_at: str = ""
    session_id: str = ""
    embedding: Optional[bytes] = None
    embedding_version: int = 0
    is_archived: bool = False

@dataclass
class FactV2:
    id: Optional[int] = None
    category: str = ""
    fact_key: str = ""
    fact_value: str = ""
    confidence: float = 0.5
    stability: float = 0.5
    freshness: float = 1.0
    importance: float = 0.5
    status: Literal["active", "decayed", "merged", "obsolete", "contradicted"] = "active"
    source_observation_ids: list[int] = field(default_factory=list)
    verification_count: int = 0
    last_verified_at: Optional[str] = None
    created_by: str = "consolidation"
    created_at: str = ""
    updated_at: str = ""
    session_id: str = ""
    embedding: Optional[bytes] = None
    embedding_version: int = 0
```

保留旧 `UserFact / Experience / Reflection` 模型不动，保证旧代码能跑。

## 4. `MemoryLifecycleManager`

文件：`memory/lifecycle.py`

核心方法：

```python
class MemoryLifecycleManager:
    def __init__(self, ltm: LongTermMemory, config=None, embedding_engine=None)

    # ── Observation ──
    async def observe(content, source_turn, episode_turn_start, episode_turn_end, created_by) -> Observation
    async def find_similar_observations(content, limit=5) -> list[Observation]

    # ── Fact promotion ──
    async def promote_fact(observation_ids, category, key, value,
                           confidence, stability, freshness, importance) -> FactV2
    async def verify_fact(fact_id)
    async def contradict_fact(fact_id, reason)

    # ── Lifecycle ──
    async def decay(now)
    async def merge_duplicates()
    async def archive_old_observations(max_age_days=30)
    async def garbage_collect()
```

设计要点：

- `observe()` 把整段 turn_text 作为原始观察写入
- `find_similar_observations()` 一期用关键词搜索，二期可切换为 embedding 相似度
- `promote_fact()` 把观察提升为事实；同 `(session_id, category, fact_key)` 会合并并增加 `verification_count`
- `decay()` 根据 `last_verified_at` 衰减 `freshness` 和 `confidence`，低于阈值标记为 `decayed`
- `garbage_collect()` 组合 decay、merge、archive

## 5. `MemoryConsolidator` 改造

改造后 `consolidate()` 执行流程：

```python
def consolidate(self, short_term, personality, ...):
    if not self._pending_buffer:
        self._gc_only()
        return

    turn_text = self._format_turns(self._pending_buffer)

    # Step 0: 创建 Observation
    if self._lifecycle:
        obs = self._lifecycle.observe(turn_text, ...)
        lifecycle_obs_ids = [obs.id]

    # Step 1: 提取 facts（旧系统 + 新系统双写）
    self._extract_facts(turn_text, observation_ids=lifecycle_obs_ids)

    # Step 2: 创建结构化 Episode（旧系统不变）
    self._summarize_experience(turn_text, short_term)

    # Step 3: 生成 Reflection（旧系统不变，二期替换为 Insight）
    self._generate_reflection_l1/l2/l3(...)

    # Step 4: 更新关系
    self._update_relationship(personality)

    # Step 5: Prune（旧系统）
    self._prune(...)

    # Step 6: Layer 1 GC（新系统）
    if self._lifecycle and self._consolidation_count % 5 == 0:
        self._lifecycle.garbage_collect()

    # Step 7: Embed
    self._embed_new_items()
```

关键改动：

- `__init__` 增加 `config` 参数；当 `config.use_observation_fact == True` 时初始化 `_lifecycle`
- `_extract_facts()` 接收 `observation_ids`，每提取一个 fact 后同时调用 `_lifecycle.promote_fact()`
- 原有 `user_facts` 写入逻辑完全保留

## 6. Prompt 模板（二期使用）

### 6.1 Observation 提取

```
从这段对话中提取原始观察。
每个观察输出一行：
OBS|内容|置信度|重要性

- 内容：客观描述用户说了什么或发生了什么
- 置信度：0.0~1.0
- 重要性：0.0~1.0（多久后还有意义）

只提取用户明确说过或高度可推断的信息。不确定的给低置信度。
不要下结论，只描述观察。
```

### 6.2 Fact 提升（从 Observations）

```
基于以下观察，判断能否提炼成事实。
如果同一主题有多条观察，可以合并提升为事实。

输出格式（每行一个）：
FACT|分类|关键词|值|置信度|重要性

分类: preference, identity, event, relationship, routine
```

### 6.3 Insight 生成（二期替换 Reflection）

```
基于以下事实和体验，生成一个假设性洞察。

输出必须是 JSON：
{
  "hypothesis": "用户可能偏好...",
  "insight_type": "pattern",
  "evidence": ["fact_id_1", "fact_id_2"],
  "confidence": 0.47,
  "needs_more_evidence": true
}
```

## 7. 数据库迁移策略

### 推荐方案：并行运行（已采用）

1. 新增 `observations`、`facts_v2` 表（schema version 2）
2. 保留旧 `user_facts`、`experiences`、`reflections` 表继续工作
3. 改造后的 `MemoryConsolidator` 同时写新表和旧表（双写）
4. Retrieval 仍读旧表，新表只写不读
5. 验证新系统稳定后，写一次性迁移脚本把旧表数据导入新表
6. 删除旧表写入逻辑

优点：不影响当前对话功能；可对比新旧系统；出问题可快速回滚。

## 8. 实施步骤

### 一期（已完成）

1. **数据库 Schema**：新增 `observations`、`facts_v2` 表，schema version 2
2. **数据模型**：新增 `Observation`、`FactV2`
3. **Repository**：新增 CRUD
4. **Lifecycle Manager**：实现核心生命周期方法
5. **Consolidator 改造**：双写，加 `use_observation_fact` 开关
6. **配置**：`config.py` / `config.example.json` 新增开关
7. **测试**：`test_memory_lifecycle.py` + 扩展 `test_consolidation.py`
8. **文档**：changes 记录 + `doc/refactor/layer1-memory/`

### 二期（待规划）

1. 新增 `insights_v2` 表
2. 替换 `REFLECTION_PROMPT` 为 JSON hypothesis prompt
3. `MemoryConsolidator` 生成 Insight 时写入 `insights_v2`
4. `memory.retrieval` 切换到 `facts_v2` + `insights_v2`
5. 删除旧 `user_facts` / `reflections` 写入逻辑
6. 写旧数据迁移脚本

## 9. 验证标准

1. `pytest tests/test_memory_lifecycle.py tests/test_consolidation.py -v` 全部通过
2. 连续对话 20 轮后，新表中有 Observation/FactV2 数据
3. 同一条用户喜好的表述重复 3 次后，对应 FactV2 的 `verification_count >= 3` 且 `confidence` 上升
4. 用户更正信息后，旧 FactV2 被标记为 `contradicted`，新 FactV2 生成
5. Insight 输出必须包含非空 `evidence` 和 `confidence`（二期）
6. 全量测试 `pytest tests --ignore=tests/real_api -q` 不降级

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 新表数据质量不如旧表 | 双写期间对比，默认关闭，验证后再开 |
| Prompt 改后 LLM 输出格式不稳定 | 严格 JSON schema + 失败 fallback |
| 旧数据无法迁移 | 保留旧表只读，新数据走新表 |
| 性能下降（多了一层） | 批量操作 + 索引 + GC 异步 |

## 11. 相关文件

- `memory/lifecycle.py`
- `memory/consolidation.py`
- `storage/database.py`
- `storage/repository.py`
- `models/memory.py`
- `config.py`
- `tests/test_memory_lifecycle.py`
- `tests/test_consolidation.py`
- `changes/2026-07-14-memory-layer1-observation-fact.md`
