# Memory Agent：交叉验证算法

> 目标：对检索到的多条证据进行交叉验证，判断一致性、时效性、可靠性，输出带置信度的验证结果。

---

## 1. 验证维度

| 维度 | 说明 | 权重 |
|------|------|------|
| `consistency` | 多条证据是否相互一致 | 0.30 |
| `timeline` | 时间线是否吻合 | 0.20 |
| `source_quality` | 证据来源质量（Fact > Observation > Experience） | 0.20 |
| `freshness` | 证据是否过时 | 0.15 |
| `verification_count` | Fact 被验证次数 | 0.10 |
| `contradiction` | 是否存在矛盾 | 0.05 |

---

## 2. 验证流程

```
evidences
  ↓
按主题/实体分组
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
    
    # 按主题分组（基于 keywords / entities 的相似度）
    groups = group_by_topic(evidences)
    consistent_groups = 0
    
    for group in groups:
        values = [e.content for e in group]
        # 如果所有证据内容语义相似，则认为一致
        if semantic_similarity(values) > 0.7:
            consistent_groups += 1
    
    return consistent_groups / len(groups) if groups else 0.5
```

### 3.2 时间线检查

```python
def check_timeline(evidences: list[MemoryEvidence]) -> float:
    """时间线是否吻合。返回 0.0 ~ 1.0。"""
    dated = [e for e in evidences if e.timestamp]
    if len(dated) <= 1:
        return 1.0
    
    sorted_evidences = sorted(dated, key=lambda e: e.timestamp)
    # 检查时间顺序是否合理（比如不应该先看到结果后看到原因）
    # 一期简单实现：时间跨度越大，置信度越低
    first = datetime.fromisoformat(sorted_evidences[0].timestamp)
    last = datetime.fromisoformat(sorted_evidences[-1].timestamp)
    days = (last - first).days
    
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
def compute_confidence(evidences: list[MemoryEvidence]) -> float:
    if not evidences:
        return 0.0
    
    consistency = check_consistency(evidences)
    timeline = check_timeline(evidences)
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
        timeline * 0.20 +
        avg_source_quality * 0.20 +
        freshness * 0.15 +
        verification_score * 0.10 +
        contradiction_penalty * 0.05
    )
    
    return round(confidence, 2)
```

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
