# Layer 3: 多阶段 Retrieval — 进度

## 状态

未开始。

## 已完成

- [x] 设计文档（README.md）

## 待完成

### P0：基础多源检索
- [ ] `QueryClues` 数据模型
- [ ] `ParallelRetriever` 并行检索
- [ ] `ContextBuilder` 按 Agent 类型组装
- [ ] `tests/test_parallel_retriever.py`

### P1：交叉验证
- [ ] `CrossVerifier`
- [ ] 与 `FactChecker` 集成
- [ ] `tests/test_cross_verifier.py`

### P2：Reranker
- [ ] 按 Agent Profile 加权排序
- [ ] 综合评分算法

### P3：不同 Agent 不同上下文
- [ ] Agent 3 轻量上下文
- [ ] Agent 2 无 Memory
- [ ] Agent 1 完整上下文

## 阻塞项

- 等待 Layer 1 二期完成，`facts_v2` / `observations` 数据稳定后实现更可靠
