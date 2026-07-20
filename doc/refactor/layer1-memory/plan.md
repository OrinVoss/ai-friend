# Layer 1: Memory 生命周期重构

> 目标：把当前"直接存 fact/reflection"的模型，改造为 **Observation → Fact → Insight** 三层生命周期模型，让记忆可验证、可衰减、可遗忘、可追溯来源。

> **实施状态**：一期 Observation → Fact 已于 2026-07-18 完整上线（schema v4，直接切换，未走双写）；二期 Insight 替换 Reflection 已于 2026-07-20 上线（schema v5，同样直接切换：reflections 数据迁入 insights_v2 并归档为 reflections_archive，读路径经 repository 适配器切新表）。见 `changes/2026-07-18-memory-layer1-full-launch.md`、`changes/2026-07-20-insight-replaces-reflection.md`。

---

## 1. 当前问题

当前 `MemoryConsolidator.consolidate()` 直接做四件事：

1. `_extract_facts()` → 直接写 `user_facts` 表
2. `_summarize_experience()` → 直接写 `experiences` 表
3. `_generate_reflection_*()` → 直接写 `reflections` 表
4. `_update_relationship()` → 更新关系指标

问题：
- 单次对话观察被直接当成永久事实，缺少验证过程
- Reflection 输出开放式结论，没有假设/证据/置信度
- 没有来源字段，无法追踪哪个 Agent、哪条 episode 产生的记忆
- Fact 只有 confidence，没有 freshness/stability/importance 多维度
- 没有衰减/合并/删除机制，长期运行会自我污染

---

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

---

## 3. 数据模型改造

### 3.1 新增表

```sql
-- 原始观察
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,              -- 观察内容（自然语言）
    episode_turn_start INTEGER,         -- 来源 episode 起始 turn
    episode_turn_end INTEGER,           -- 来源 episode 结束 turn
    source_turn INTEGER,                -- 具体触发 turn
    created_by TEXT NOT NULL,           -- 哪个阶段生成：consolidation / user_correction / tool_result
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
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
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
    embedding BLOB,
    embedding_version INTEGER DEFAULT 0,
    UNIQUE(session_id, category, fact_key)
);

-- 洞察/假设（从 fact 推理）
CREATE TABLE insights_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis TEXT NOT NULL,           -- 假设内容
    evidence_fact_ids TEXT DEFAULT '[]',
    insight_type TEXT,                  -- pattern / contradiction / connection / emotion / prediction
    confidence REAL DEFAULT 0.5,
    needs_more_evidence INTEGER DEFAULT 1,
    expires_at TIMESTAMP,               -- 过期时间
    status TEXT DEFAULT 'active',       -- active / expired / verified / rejected
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
    embedding BLOB,
    embedding_version INTEGER DEFAULT 0
);
```

### 3.2 新增 Python 模型

在 `models/memory.py` 新增：

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
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    session_id: str = ""
    embedding: Optional[bytes] = None
    embedding_version: int = 0

@dataclass
class InsightV2:
    id: Optional[int] = None
    hypothesis: str = ""
    evidence_fact_ids: list[int] = field(default_factory=list)
    insight_type: Optional[str] = None
    confidence: float = 0.5
    needs_more_evidence: bool = True
    expires_at: Optional[str] = None
    status: Literal["active", "expired", "verified", "rejected"] = "active"
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    session_id: str = ""
    embedding: Optional[bytes] = None
    embedding_version: int = 0
```

保留旧 `UserFact / Experience / Reflection` 模型不动，保证旧代码能跑。

---

## 4. 新增 `memory/lifecycle.py`

核心类：

```python
class MemoryLifecycleManager:
    def __init__(self, ltm: LongTermMemory, config=None):
        self.ltm = ltm
        self.config = config

    # ── Observation ──
    async def observe(self, content: str, source_turn: int,
                      episode_turn_start: Optional[int] = None,
                      episode_turn_end: Optional[int] = None,
                      created_by: str = "consolidation") -> Observation

    async def find_similar_observations(self, content: str, limit: int = 5) -> list[Observation]

    # ── Fact promotion ──
    async def promote_fact(self, observation_ids: list[int],
                           category: str, key: str, value: str,
                           confidence: float = 0.5) -> FactV2

    async def verify_fact(self, fact_id: int, evidence_turn_id: int)
    async def contradict_fact(self, fact_id: int, reason: str)

    # ── Insight ──
    async def create_insight(self, hypothesis: str,
                             evidence_fact_ids: list[int],
                             insight_type: str,
                             confidence: float = 0.5,
                             needs_more_evidence: bool = True) -> InsightV2

    async def expire_insight(self, insight_id: int)
    async def verify_insight(self, insight_id: int)

    # ── Lifecycle ──
    async def decay(self, now: Optional[datetime] = None)
    async def merge_duplicates(self)
    async def archive_old_observations(self, max_age_days: int = 30)
    async def garbage_collect(self)
```

---

## 5. `MemoryConsolidator` 改造

当前 `consolidate()` 执行 6 步。改造后变为 8 步：

```python
def consolidate(self, short_term, personality):
    if not self._pending_buffer:
        self._gc_only()
        return

    turn_text = self._format_turns(self._pending_buffer)

    # Step 1: 创建 Observation（替代原来的直接 extract facts）
    observations = self._create_observations(turn_text)

    # Step 2: 从 Observation 中提取候选 Fact
    candidate_facts = self._extract_candidate_facts(observations)

    # Step 3: 提升/验证 Fact（LifecycleManager.promote/verify）
    self._promote_or_verify_facts(candidate_facts, observations)

    # Step 4: 创建结构化 Episode（替代原来的 summarize_experience）
    self._create_episode(turn_text)

    # Step 5: 生成 Insight（替代原来的 reflection，输出 JSON hypothesis）
    if self._should_generate_insight():
        self._generate_insight(personality)

    # Step 6: 更新关系
    self._update_relationship(personality)

    # Step 7: GC
    self._gc()

    # Step 8: Embed
    self._embed_new_items()
```

### 5.1 新 Prompt：Observation 提取

新建 `prompts/templates.py` 常量：

```python
OBSERVATION_EXTRACTION_PROMPT = """从这段对话中提取原始观察。
每个观察输出一行：
OBS|内容|置信度|重要性

- 内容：客观描述用户说了什么或发生了什么
- 置信度：0.0~1.0
- 重要性：0.0~1.0（多久后还有意义）

只提取用户明确说过或高度可推断的信息。不确定的给低置信度。
不要下结论，只描述观察。

对话：
{text}

观察：
"""
```

### 5.2 新 Prompt：Fact 提取（从 Observations）

```python
FACT_PROMOTION_PROMPT = """基于以下观察，判断能否提炼成事实。
如果同一主题有多条观察，可以合并提升为事实。

输出格式（每行一个）：
FACT|分类|关键词|值|置信度|重要性

分类: preference, identity, event, relationship, routine

观察：
{observations}

已有事实：
{existing_facts}

可提升的事实：
"""
```

### 5.3 新 Prompt：Insight 生成（替代 Reflection）

把现有 `REFLECTION_PROMPT` 替换为 `INSIGHT_GENERATION_PROMPT`：

```python
INSIGHT_GENERATION_PROMPT = """基于以下事实和体验，生成一个假设性洞察。

输出必须是 JSON：
{
  "hypothesis": "用户可能偏好...",
  "insight_type": "pattern",
  "evidence": ["fact_id_1", "fact_id_2"],
  "confidence": 0.47,
  "needs_more_evidence": true
}

要求：
- hypothesis 必须是可验证的假设，不是最终结论
- evidence 必须列出支持的事实 ID
- confidence 0.0~1.0
- needs_more_evidence 如果证据不足则为 true

事实：
{facts}

体验：
{experiences}
"""
```

---

## 6. 数据库迁移策略

### 推荐方案 B：并行运行（低风险）

1. 新增 `observations`, `facts_v2`, `insights_v2` 三张表。
2. 保留旧 `user_facts`, `experiences`, `reflections` 表继续工作。
3. 改造后的 `MemoryConsolidator` 同时写新表和旧表（双写）。
4. 读操作优先使用旧表，逐步切换到新表。
5. 验证新系统稳定后，写一次性迁移脚本把旧表数据导入新表。
6. 删除旧表。

### 备选方案 A：直接替换（高风险）

1. 把 `user_facts` 改名为 `_old_user_facts`。
2. 创建新的 `facts_v2` 表。
3. 写迁移脚本导入旧数据（旧 fact 默认 confidence=0.8，verification_count=1）。
4. 所有代码直接改用新表。

**推荐方案 B**，因为：
- 不影响当前对话功能
- 可以对比新旧系统的输出质量
- 出问题可快速回滚到旧表

---

## 7. 实施步骤

### Step 1: 数据库 Schema（1 天）

- `storage/database.py` 新增 `observations`, `facts_v2`, `insights_v2` 表定义
- `models/memory.py` 新增 `Observation`, `FactV2`, `InsightV2`
- `storage/repository.py` 新增对应 CRUD
- 写 schema 迁移，schema_version 升级到 2

### Step 2: `memory/lifecycle.py`（2~3 天）

- 实现 `MemoryLifecycleManager`
- 实现 observe / promote / verify / contradict / decay / merge / gc
- 与现有 `FactChecker` 集成

### Step 3: `MemoryConsolidator` 改造（2~3 天）

- 新增 `_create_observations`, `_extract_candidate_facts`, `_promote_or_verify_facts`, `_create_episode`, `_generate_insight`
- 保留旧方法但标记 deprecated
- 配置开关 `use_memory_lifecycle: bool`，默认 False
- 双写新旧表

### Step 4: Prompt 模板（1 天）

- `prompts/templates.py` 新增 Observation/Fact/Insight prompt
- 移除/修改旧 Reflection prompt

### Step 5: GC 调度（1 天）

- 新增 `memory/gc.py`
- 在 `MemoryConsolidator` 中每 N 轮调用一次 GC
- Web 端增加手动触发 GC 的接口（可选）

### Step 6: 测试（2~3 天）

- `tests/test_memory_lifecycle.py`（新建）
  - Observation 创建
  - Fact 提升
  - Fact 验证/矛盾
  - Insight 生成/过期
  - GC 衰减/合并
- `tests/test_consolidation.py` 更新
  - 新 consolidate 流程
  - 双写验证
  - 配置开关

### Step 7: 切换与清理（1 天）

- 默认开启 `use_memory_lifecycle: true`
- 运行一段时间后删除旧表写入逻辑
- 写旧数据迁移脚本

---

## 8. 验证标准

1. `pytest tests/test_memory_lifecycle.py tests/test_consolidation.py -v` 全部通过
2. 连续对话 20 轮后，新表中有 Observation/Fact/Insight 数据
3. 同一条用户喜好的表述重复 3 次后，对应 Fact 的 `verification_count >= 3` 且 `confidence` 上升
4. 用户更正信息后，旧 Fact 被标记为 `contradicted`，新 Fact 生成
5. Insight 输出必须包含非空 `evidence` 和 `confidence`
6. 全量测试 `pytest tests --ignore=tests/real_api -q` 不降级

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 新表数据质量不如旧表 | 双写期间对比，默认关闭，验证后再开 |
| Prompt 改后 LLM 输出格式不稳定 | 严格 JSON schema + 失败 fallback |
| 旧数据无法迁移 | 保留旧表只读，新数据走新表 |
| 性能下降（多了一层） | 批量操作 + 索引 + GC 异步 |

---

## 10. 推荐下一步

执行 **Step 1 + Step 2**：先把表和 `MemoryLifecycleManager` 架子搭起来，不改动 `MemoryConsolidator` 主流程。等 manager 能独立跑通 observe/promote/verify 后，再进入 Step 3 改造 consolidate。
