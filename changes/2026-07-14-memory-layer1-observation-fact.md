# Layer 1 Memory 生命周期：Observation → Fact（一期）

## 改动摘要

ML-001：为记忆系统引入显式的 **Observation → Fact** 两层生命周期，避免单次对话观察被直接当成永久事实。本期为双写阶段：旧 `user_facts` 表继续工作，新 `observations` / `facts_v2` 表并行写入，默认关闭，验证稳定后可开启。

## 涉及文件

- `storage/database.py`
  - 新增 `observations`、`facts_v2` 表
  - schema version 升级到 2
  - 新增对应索引
- `storage/repository.py`
  - 新增 Observation / FactV2 的 CRUD
- `models/memory.py`
  - 新增 `Observation`、`FactV2` 数据模型
- `memory/lifecycle.py`（新建）
  - `MemoryLifecycleManager`：observe / promote / verify / contradict / decay / gc
- `memory/consolidation.py`
  - `MemoryConsolidator` 支持 `config.use_observation_fact` 开关
  - 开启时额外创建 Observation 并双写 FactV2
  - 每 5 次 consolidation 触发一次 lifecycle GC
- `config.py`
  - 新增 `use_observation_fact: bool = false`
- `config.example.json`
  - 新增 `"use_observation_fact": false`
- `main.py`、`web/session.py`
  - 将 `config` 传入 `MemoryConsolidator`
- `tests/test_memory_lifecycle.py`（新建）
  - 覆盖 Observation / FactV2 生命周期
- `tests/test_consolidation.py`
  - 覆盖开关行为与双写逻辑

## 方案说明

### 为什么分两期

- 风险最低：旧记忆系统继续工作，新系统只并行写入
- 可早期验证：跑几天后观察 `facts_v2` 数据质量，再决定是否切换 Retrieval
- 改动面小：一期不碰 Prompt、Retrieval、Agent Runtime
- 可回滚：关闭开关即回到原流程

### 一期范围

1. 新增 `observations` 表：保存每次 consolidation 的原始观察
2. 新增 `facts_v2` 表：保存带 `confidence / stability / freshness / importance` 的事实
3. `MemoryLifecycleManager` 提供核心生命周期方法
4. `MemoryConsolidator` 在原有流程基础上，额外双写 Observation + FactV2
5. 新增 GC：事实衰减（freshness/confidence 随时间下降）、旧 Observation 归档

### 二期工作

- 用 Insight 替换 Reflection
- Retrieval 切换到 `facts_v2` + `insights_v2`
- 完整 GC：merge / decay / obsolete
- 删除旧 `user_facts` / `reflections` 表

## 配置方式

```json
{
  "use_observation_fact": false
}
```

默认 `false`。想开启新生命周期时改为 `true` 即可。

## 验证结果

```bash
python -m pytest tests/test_memory_lifecycle.py tests/test_consolidation.py -v
# 19 passed

python -m pytest tests --ignore=tests/real_api -q
# 401 passed, 2 skipped
```

## 后续工作

- 运行一段时间后对比 `user_facts` 与 `facts_v2` 的数据质量
- 验证同一喜好重复 3 次后 `verification_count >= 3` 且 `confidence` 上升
- 用户更正信息后，旧 FactV2 被标记为 `contradicted`，新 FactV2 生成
- 稳定后进入二期：Insight 替换 Reflection
