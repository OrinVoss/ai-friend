# 2026-06-01 - #6 虚假记忆修正：矛盾检测 + 置信度衰减 + 用户纠正

## 修改文件

### 新建
- **memory/fact_checker.py** — FactChecker 类，embedding 语义相似度矛盾检测 + 置信度衰减/软删除
- **tests/test_fact_checker.py** — 16 个单元测试（初始化/矛盾检测/解决/余弦相似度/常量）
- **tests/test_memory_tools.py** — 6 个单元测试（RememberTool 存储/纠正/缺失参数）

### 修改
- **storage/repository.py** — 新增 `deactivate_fact()`, `update_fact_confidence()`, `get_similar_facts()`；search_facts 和 get_active_facts 加 `confidence >= 0.2` 过滤
- **memory/consolidation.py** — 初始化 FactChecker，`_extract_facts()` 后每条新事实与已有事实做矛盾检测
- **memory/long_term.py** — 新增 `correct_fact()`（confidence=1.0+importance=0.9）+ 同步包装器
- **tools/memory_tools.py** — RememberTool 新增 `correct` 参数，纠正模式走 correct_fact 路径
- **memory/retrieval.py** — `_keyword_score_single` 加入 confidence 权重（0.15）

## 核心机制

### 矛盾检测
1. 同 (category, key) 不同 value → 直接矛盾
2. embedding 余弦相似度 > 0.65 且 value 不同 → 语义矛盾
3. 嵌入引擎不可用时自动跳过语义检测

### 置信度衰减
- 被矛盾的事实：confidence × 0.4
- 衰减后 < 0.2 → 软删除（is_active=0）
- 检索时自动过滤 confidence < 0.2 的事实

### 用户纠正
- RememberTool 设置 `correct=true` → 旧事实软删除，新事实 confidence=1.0
- confidence=1.0 确保纠正不会被后续 upsert 覆盖

## 测试
222 passed (+22), 8 skipped
