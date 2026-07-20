# Memory Agent：交叉验证算法

> 目标：对检索到的多条证据进行交叉验证，判断一致性、时效性、可靠性，输出带置信度的验证结果。

---

## 1. 验证维度

| 维度 | 说明 | 权重 |
|------|------|------|
| `consistency` | 多条证据是否相互一致 | 0.30 |
| `verification_count` | Fact 被验证次数 | 0.20 |
| `source_quality` | 证据来源质量（Fact > Observation > Experience） | 0.20 |
| `freshness` | 证据是否过时 | 0.15 |
| `timeline` | 时间线是否吻合 | 0.10 |
| `contradiction` | 是否存在矛盾 | 0.05 |

权重设计理由：

- `verification_count` 是所有维度中**最可靠的信号**——它代表这条 Fact 被独立证据反复确认的次数，权重给到 0.20
- `timeline` 只表示「没有明显时间矛盾」，上限不高，降为 0.10；且对偏好/身份/关系类事实，长时间跨度反而是稳定性的佐证（见 3.2）

---

## 2. 验证流程

```
evidences
  ↓
按主题聚类（embedding 余弦相似度）
  ↓
对每组证据做以下检查：
  ├── 一致性检查：同一主题的证据是否指向同一结论？
  ├── 时间线检查：时间范围是否重叠或矛盾？
  ├── 矛盾检测：是否有直接冲突的证据？
  ├── 新鲜度检查：最新证据是否支持旧结论？
  └── 来源质量加权：Fact 权重高于 Observation
  ↓
计算综合置信度
  ↓
标记 contradictions / stale / reliable
```

---

## 3. 具体算法

### 3.1 一致性检查

```python
def check_consistency(evidences: list[MemoryEvidence]) -> float:
    """同一主题的证据是否一致。返回 0.0 ~ 1.0。"""
    if len(evidences) <= 1:
        return 1.0
    
    # 按主题分组（基于证据 embedding 的余弦相似度）
    groups = group_by_topic(evidences)
    consistent_groups = 0
    
    for group in groups:
        values = [e.content for e in group]
        # 如果所有证据内容语义相似，则认为一致
        if semantic_similarity(values) > 0.7:
            consistent_groups += 1
    
    return consistent_groups / len(groups) if groups else 0.5
```

### 3.2 时间线检查（分事实类型）

时间跨度对置信度的影响**取决于事实类型**，不能一刀切：

- **事件类**（event）：跨度越大，证据链越散，置信度越低
- **偏好/身份/关系类**（preference / identity / relationship）：跨度几乎不影响置信度——「用户住在北京」横跨 365 天的证据反而佐证稳定性

```python
# 稳定型分类：长时间跨度是稳定性的佐证，不是减分项
STABLE_CATEGORIES = {"preference", "identity", "relationship"}

def check_timeline(evidences: list[MemoryEvidence],
                   category: str = "event") -> float:
    """时间线是否吻合。返回 0.0 ~ 1.0。"""
    dated = [e for e in evidences if e.timestamp]
    if len(dated) <= 1:
        return 1.0
    
    sorted_evidences = sorted(dated, key=lambda e: e.timestamp)
    first = datetime.fromisoformat(sorted_evidences[0].timestamp)
    last = datetime.fromisoformat(sorted_evidences[-1].timestamp)
    days = (last - first).days
    
    if category in STABLE_CATEGORIES:
        # 稳定型事实：跨度大 → 轻微加分（封顶 1.0）
        return min(0.8 + days / 365 * 0.2, 1.0)
    
    # 事件类事实：跨度越大，置信度越低
    if days <= 1:
        return 1.0
    elif days <= 7:
        return 0.8
    elif days <= 30:
        return 0.6
    else:
        return 0.4
```

### 3.3 矛盾检测

```python
def detect_contradictions(evidences: list[MemoryEvidence]) -> list[str]:
    """检测直接冲突的证据。"""
    contradictions = []
    # 使用现有 FactChecker 的语义相似度
    for i, e1 in enumerate(evidences):
        for e2 in evidences[i+1:]:
            if is_contradiction(e1.content, e2.content):
                contradictions.append(
                    f"{e1.content[:50]} vs {e2.content[:50]}"
                )
    return contradictions
```

### 3.4 新鲜度检查

```python
def check_freshness(evidences: list[MemoryEvidence]) -> float:
    """证据是否过时。返回 0.0 ~ 1.0。"""
    if not evidences:
        return 0.0
    
    latest = max(e.timestamp for e in evidences if e.timestamp)
    latest_date = datetime.fromisoformat(latest)
    days_old = (datetime.now() - latest_date).days
    
    if days_old <= 1:
        return 1.0
    elif days_old <= 7:
        return 0.8
    elif days_old <= 30:
        return 0.5
    elif days_old <= 90:
        return 0.3
    else:
        return 0.1
```

### 3.5 来源质量加权

```python
SOURCE_QUALITY = {
    "fact": 1.0,           # 经验证的事实
    "observation": 0.6,    # 原始观察
    "experience": 0.5,     # 共同回忆（主观）
    "relationship": 0.3,   # 关系指标（间接）
}

def score_source_quality(evidence: MemoryEvidence) -> float:
    return SOURCE_QUALITY.get(evidence.source_type, 0.3)
```

### 3.6 综合置信度

```python
def compute_confidence(evidences: list[MemoryEvidence],
                       category: str = "event") -> float:
    if not evidences:
        return 0.0
    
    consistency = check_consistency(evidences)
    timeline = check_timeline(evidences, category=category)
    freshness = check_freshness(evidences)
    avg_source_quality = sum(score_source_quality(e) for e in evidences) / len(evidences)
    avg_verification = sum(
        getattr(e, 'verification_count', 1) for e in evidences
    ) / len(evidences)
    verification_score = min(avg_verification / 3.0, 1.0)
    
    contradictions = detect_contradictions(evidences)
    contradiction_penalty = 1.0 - min(len(contradictions) * 0.2, 0.5)
    
    confidence = (
        consistency * 0.30 +
        verification_score * 0.20 +
        avg_source_quality * 0.20 +
        freshness * 0.15 +
        timeline * 0.10 +
        contradiction_penalty * 0.05
    )
    
    return round(confidence, 2)
```

### 3.6.1 查询相关性缩放（MA-002）

✅ 已实现（2026-07-18，`changes/2026-07-18-memory-agent-relevance-floor.md`）

六维加权衡量的是「证据本身的质量」，但没有衡量「证据和问题的相关度」——无关输入（如「你好」）也能召回一池噪声证据拿到虚高置信度。因此在加权分之后追加相关性缩放：

```python
if top_sim is not None:
    confidence *= min(top_sim / relevance_full, 1.0)  # relevance_full 默认 0.75
```

同时在召回阶段加相关性下限：可测量证据（有当前版本向量的）cosine 相似度 < `relevance_floor`（默认 0.35）直接丢弃；无向量/旧版本向量的证据保留（相关性不可知，不误杀）。

**豁免规则**：recall/summarize 意图（「上周我们聊了什么」）的 query 向量不携带话题，跳过下限与缩放，否则无主题回忆会被误杀。

两个阈值均为 config 可调（`memory_agent_relevance_floor` / `memory_agent_relevance_full`），生产上按 `[memory_agent] answer:` 日志中的 `top_sim` 分布调参。

### 3.7 矛盾向上传播（二期）

✅ 已实现（2026-07-20，`changes/2026-07-20-memory-agent-p2.md`）：`lifecycle.contradict_fact` 标记 Fact contradicted 后扫描 active insights，`evidence_fact_ids` 含该 Fact 的一律 `mark_insight_suspect`（needs_more_evidence=1 + confidence ×0.5，保持 active 等待重评）。

当一条 Fact 被新证据推翻（`correct_fact` 或 `contradict_fact`）时，不能只标记这条 Fact：

```
Fact A 被标记为 contradicted
  ↓
查询 insights_v2 中 evidence_fact_ids 包含 A 的所有 Insight
  ↓
这些 Insight 标记为可疑（needs_more_evidence=true，confidence 降权）
  ↓
等待下次验证时重新评估
```

理由：Insight 是从 Fact 推理出来的，前提倒了，结论必须连带质疑。否则旧 Insight 会继续作为「有效记忆」被检索出来。

---

## 4. 输出标记

验证后的每个 `MemoryEvidence` 会被标记：

```python
@dataclass
class VerifiedEvidence(MemoryEvidence):
    consistency_score: float = 1.0
    timeline_score: float = 1.0
    freshness_score: float = 1.0
    is_contradicted: bool = False
    is_stale: bool = False
    is_reliable: bool = True
```

`MemoryAnswer` 中的 `contradictions` 字段收集所有检测到的矛盾。

---

## 5. 测试用例

| 场景 | 期望结果 |
|------|----------|
| 只有 1 条 Fact，verification_count=3 | confidence ≈ 0.8 |
| 2 条 Observation 内容一致 | consistency = 1.0 |
| 2 条 Observation 内容矛盾 | contradictions 非空，confidence 下降 |
| 最新证据是 1 年前 | freshness ≈ 0.1，整体 confidence 下降 |
| 只有 Experience 没有 Fact | source_quality 低，confidence 中等 |
| 最近 3 天有 2 条 Observation 支持某 Fact | freshness 高，verification_score 高 |
