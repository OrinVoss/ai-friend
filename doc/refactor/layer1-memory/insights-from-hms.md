# 从 H.M. / 舍雷舍夫斯基 / Holographic Memory System 得到的启发

> 来源：织影（Shadoweave）团队关于 HMS 与 Memory Bank 的文章
> 写入日期：2026-07-14
> 状态：启发记录，供 Layer 1 二期和 Layer 3 Retrieval 参考

---

## 1. 核心启发

### 1.1 存储 ≠ 回忆

H.M. 案例说明：信息可以被保留，却不一定能被调取。我们的系统里：

- **Observation** 是存储层（archive）
- **Fact / Insight** 是回忆推理层（interpretation）
- 但当前 Retrieval 仍然是「向量相似度 TopK」，本质是查表，不是回忆

**改进方向**：回忆阶段应该基于多条线索（时间、人物关系、事件链）交叉重构，而不是单轮相似度匹配。

### 1.2 遗忘是记忆的能力，不是漏洞

舍雷舍夫斯基案例说明：无限存储会窒息理解。当前我们：

- 保留了所有 `user_facts` / `experiences` / `reflections`
- 只有简单的 `prune_facts` / `prune_experiences` 做数量控制
- 没有真正的「衰减 → 归档 → 删除」生命周期

**改进方向**：加强 GC 的语义判断，低价值、低新鲜度的记忆应该主动被弱化或归档。

### 1.3 vough 与 mimi 的分离

《双面真相》中的两种记忆逻辑：

| 类型 | 特性 | 我们系统中的对应物 |
|------|------|------------------|
| **vough**（事实存档） | 客观记录，绝不改动 | `observations` 表 |
| **mimi**（现实解读） | 结合当下重新理解 | `facts_v2` / `insights_v2` |

当前问题：
- Observation 创建后可能会被修改（虽然目前代码没有 update 逻辑，但没有明确的不可变性保证）
- Fact 的 value 可能会被 upsert 覆盖，但旧 Observation 不会联动
- 缺乏「新证据推翻旧判断」的显式机制

**改进方向**：
1. `observations` 明确为只增不改的 archive
2. `facts_v2` / `insights_v2` 是可被新证据更新的 interpretation
3. 用户更正时：Observation 保留原样，旧 Fact 标记 `contradicted`，新 Fact 生成并关联新的 Observation

### 1.4 全息式碎片重构

HMS 的核心：像全息底片一样，用碎片化线索还原完整经历。

当前我们的 Retrieval 是单点相似度。应该改成多线索交叉：

```
Query
  ↓
提取线索（时间、实体、关系、情绪）
  ↓
并行检索：facts_v2 + observations + experiences + relationship
  ↓
交叉验证：同一主题的多条证据是否一致？
  ↓
如果有矛盾 → 标记或降权
  ↓
组装成 Context Summary
```

### 1.5 记忆巩固（Consolidation）应该像睡眠

HMS 的「自进化机制」复刻了人脑睡眠期间的记忆巩固：回放往日经历，萃取深层规律。

当前我们的 `MemoryConsolidator` 每 N 轮触发一次，但主要是提取 fact / experience / reflection。缺少：

- 对 Observation 的「回放」式复盘
- 从多条 Observation 中提炼模式（而不是直接生成 fact）
- 对已有 Fact 的主动验证（最近有没有新 Observation 支持/反驳它？）

**改进方向**：Layer 1 二期可以在 consolidation 中加入「回放验证」步骤。

### 1.6 敢于承认记错

文章结尾强调：数字记忆的优势不在于永远正确，而在于敢于承认出错。

当前我们：
- 有 `contradict_fact` 可以标记矛盾
- 但 `facts_v2` 的 `confidence` 下降机制还不够主动
- 没有「用户明确纠正」的高优先级处理通道

**改进方向**：
- 用户输入明确更正时，直接触发 `contradict_fact` + 创建新 Fact
- 定期 GC 时，基于最近的 Observation 对旧 Fact 做「健康检查」

---

## 2. 对当前 Layer 1 的评估

### 做得好的

- `Observation → Fact` 分层思路与 vough/mimi 分离一致
- `facts_v2` 有 `confidence / stability / freshness / importance` 多维度
- `contradict_fact` 提供了承认错误的入口
- 双写阶段风险低，可回滚

### 不足

| 不足 | 表现 | 影响 |
|------|------|------|
| Observation 不可变性未显式声明 | 代码里没有禁止 update 的机制 | 未来可能被意外修改 |
| Retrieval 仍是相似度查询 | 没有多线索交叉验证 | 「相似」不等于「相关」 |
| GC 太保守 | 只按时间衰减 freshness | 低价值记忆长期占用 |
| 缺少睡眠式巩固 | consolidation 是即时提取，不是回放 | 模式发现能力弱 |
| 用户纠正没有专用通道 | 依赖 FactChecker 检测矛盾 | 明确纠正可能被低置信度过滤 |

---

## 3. 可落地的改进建议（按优先级）

### P0：Observation 不可变 + 用户纠正专用通道

1. 在 `Repository` 中给 `observations` 表加约束：只允许 INSERT，不提供 UPDATE 接口
2. 在 `MemoryLifecycleManager` 新增 `correct_fact()`：
   - 标记旧 Fact 为 `contradicted`
   - 创建新 Fact，source_observation_ids 包含用户纠正对应的 Observation
   - 新 Fact confidence 直接给 1.0

### P1：多线索交叉验证的 Retrieval

新增 `memory/retrieval.py` 的重构思路（Layer 3 核心）：

```python
class MemoryRetriever:
    def retrieve_reconstructive(self, query: str) -> ReconstructedMemory:
        # 1. 提取线索
        clues = self._extract_clues(query)
        # 2. 并行检索
        facts = self._search_facts(clues)
        observations = self._search_observations(clues)
        episodes = self._search_episodes(clues)
        # 3. 交叉验证
        verified = self._cross_verify(facts, observations, episodes)
        # 4. 组装
        return ReconstructedMemory(verified)
```

### P2：强化 GC 的语义判断

当前 `decay()` 只按时间衰减。改进为：

- 结合 `importance` 和 `verification_count` 计算实际衰减速度
- `importance < 0.3` 且 `freshness < 0.2` 的 Fact 直接标记 `obsolete`
- Observation 超过 30 天且未被任何 Fact 引用 → archive

### P3：睡眠式巩固（Layer 1 二期）

在 `MemoryConsolidator` 中新增 `_replay_and_consolidate()`：

1. 取最近 50 条 Observation
2. 按主题聚类（可用 embedding）
3. 对同一主题的多条 Observation：
   - 如果已有对应 Fact → 增加 `verification_count`
   - 如果没有 → 生成候选 Fact
4. 对已有 Fact 检查：最近的 Observation 是否支持它？不支持则降 confidence

---

## 4. 结论

这篇文章验证了我们 Layer 1 的方向是对的（Observation → Fact → Insight + 生命周期），但也提醒我们：

1. **回忆不是查表**：Retrieval 需要多线索交叉重构
2. **遗忘必须主动**：GC 要更激进、更有语义判断
3. **承认错误是一等公民**：用户纠正、矛盾检测、证据链追踪都要显式化
4. **巩固是回放**：consolidation 应该像睡眠一样，对过往经历做模式提炼

这些将直接影响 Layer 1 二期和 Layer 3 Retrieval 的设计。
