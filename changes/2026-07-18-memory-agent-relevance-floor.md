# Memory Agent 相关性下限（MA-002）

日期：2026-07-18

## 背景

灰度观察发现 Memory Agent 置信度没有区分度：连「你好」这类与记忆无关的输入也会召回顶满 10 条证据、confidence≈0.71。根因有两个：

1. `_retrieve_parallel` 不按相似度过滤——similarity=0 的证据照样保留并进入答案；
2. 置信度六维加权（consistency/verification/source/freshness/timeline/contradiction）里**没有查询相关性维度**，相似度只用于排序，不参与置信度。

## 改动

### `memory/memory_agent.py`

- `MemoryEvidence` 新增 `has_similarity` 字段，区分「相似度可测量」和「无向量/旧版本向量/关系指标」两类证据。
- `_retrieve_parallel` 返回值改为 `(evidences, top_sim)`：
  - **相关性下限**：可测量证据中 cosine 相似度 < `relevance_floor`（默认 0.35）的直接丢弃；不可测量证据保留（相关性不可知，不误杀）。
  - **recall/summarize 意图豁免**：「上周我们聊了什么」这类无主题查询的 query 向量不携带话题，跳过下限，新增 `RECALL_LIKE_INTENTS` 常量。
  - `top_sim` 为可测量证据的最大相似度；不可测量/豁免场景返回 `None`。
- `_compute_confidence` 新增 `top_sim` 参数：非 None 时置信度乘以 `min(top_sim / relevance_full, 1.0)`（`relevance_full` 默认 0.75）。无关查询即使有残留证据，置信度也被压到低位并触发 `needs_more_evidence`。
- `answer()` 的 INFO 日志增加 `top_sim` 字段，方便生产调参。
- 构造函数新增 `relevance_floor` / `relevance_full` 参数。

### 配置接线

- `config.py` 新增 `memory_agent_relevance_floor`（0.35）、`memory_agent_relevance_full`（0.75）。
- `core/message_handler.py` `_ensure_memory_agent()` 从 config 读取注入。
- `config.example.json`、`doc/config-reference.md` 同步。

### 测试（`tests/test_memory_agent.py`，+6）

- 无关查询过滤全部噪声 → 「没有找到相关记忆。」、confidence 0.0
- 相关事实（sim 1.0）保留且置信度不打折
- 中等相似度（0.5）按比例压缩置信度
- recall 意图豁免下限
- 无向量证据不被误杀
- 下限可配置（自定义 0.1 时 sim 0.2 保留）

## 验证

- `pytest tests/test_memory_agent.py -q`：27 passed
- `pytest tests --ignore=tests/real_api -q`：**599 passed + 2 skipped**（593 → 599）

## 备注

- 默认阈值（0.35/0.75）是起点值，小维度模型存在各向异性，生产上按 `[memory_agent] answer:` 日志里的 `top_sim` 分布调参。
- 已知边界：关系指标证据无向量、永远保留；当它是唯一残留证据时，乘子会把置信度压到接近 0，属可接受行为。
