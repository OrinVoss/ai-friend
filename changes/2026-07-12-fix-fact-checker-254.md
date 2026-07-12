# 修复 FactChecker 质量问题 (#254)

## 修改文件

- `memory/fact_checker.py`
- `tests/test_fact_checker.py`

## 修改原因

Issue `#254` 指出 `memory/fact_checker.py` 存在三个质量问题：

- **FC-003**: `resolve()` 总是无条件衰减旧事实置信度，不验证新事实本身的质量。
- **FC-004**: `_cosine_sim` 使用纯 Python 实现，比 numpy 慢约 10 倍。
- **FC-005**: 当 embedding 不可用时，仅依赖同 `category+key` 的显式矛盾检查，缺少语义层面的兜底检测。

## 修改内容摘要

### FC-003 新事实质量感知

- 新增常量 `MIN_NEW_FACT_CONFIDENCE = 0.3` 与 `CONFIDENCE_RATIO_MILD = 0.5`。
- `resolve()` 在衰减旧事实前先检查新事实置信度：
  - 若新事实置信度低于 `MIN_NEW_FACT_CONFIDENCE`，直接跳过，不对旧事实做任何修改。
  - 若新 / 旧置信度比值低于 `CONFIDENCE_RATIO_MILD`，使用更温和的衰减系数 `CONTRADICTION_DECAY_MILD = 0.7`。
  - 否则使用原来的 `CONTRADICTION_DECAY = 0.4`。

### FC-004 numpy 向量化

- 引入 `numpy`（已在 `requirements.txt` 中）。
- `_cosine_sim()` 改为使用 `np.dot` / `np.linalg.norm` 实现。
- 新增 `_cosine_sim_batch()`，对 `new_vec` 与 `old_vecs` 一次性计算余弦相似度，避免 Python 循环。
- `detect_contradiction()` 的 embedding 分支改为批量计算并取最大相似度。

### FC-005 关键词重叠兜底

- 新增 `_tokenize()` 与 `_jaccard_overlap()` 方法，使用字符/词级 Jaccard 相似度作为 embedding 不可用时的兜底。
- 新增常量 `KEYWORD_OVERLAP_THRESHOLD = 0.5`。
- `detect_contradiction()` 在 embedding 引擎缺失或不可用时，执行关键词重叠检查。

### 测试

- 保留并继续通过全部原有 `TestDetectContradiction`、`TestResolve`、`TestCosineSim`、`TestConstants` 测试。
- 新增测试类：
  - `TestResolveQualityAwareness`：低置信度新事实跳过、温和衰减、完全衰减三种场景。
  - `TestKeywordFallback`：关键词兜底检测矛盾、同值不矛盾、低重叠不矛盾、显式矛盾优先。
  - `TestCosineSimBatch`：批量余弦相似度与 pairwise 结果一致、多向量、零向量场景。
- `tests/test_fact_checker.py` 通过 26 个用例，`tests/test_consolidation.py` 通过 7 个用例。
