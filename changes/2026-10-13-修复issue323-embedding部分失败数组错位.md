# 修复 issue #323：embedding 部分失败导致返回数组与输入不对齐

## 修改的文件
- `memory/embeddings.py`

## 修改原因
`EmbeddingEngine.encode` 在 API 失败但有部分缓存命中时只返回缓存命中的向量，数组行数少于输入文本数。下游 `fact_checker.py:86` 用 `existing_facts[best_idx]` 索引相似度结果时，缺行会导致 best_idx 指向错误的事实，可能把无关事实误判矛盾并执行 decay/deactivate。

## 修改内容
- API 失败分支：为未编码成功的文本补零向量，保证输出与输入等长、索引对齐。
- 完全无缓存命中时仍抛错（启动自检 `verify_embedding_health` 依赖此行为）。
- 验证：`pytest -k embed` 50 passed, 2 skipped。
