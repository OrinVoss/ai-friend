# 修复：recall 工具整句 LIKE 恒 0 命中，Agent 1/3 无法使用记忆

日期：2026-07-21

## 现象

生产日志：Agent 1 三次 `recall`（含"全面扫描记忆库"）全部 `facts=0 exps=0`，而库中该 session 有 108 条 active facts、32 条 experiences。Agent 1/3 实际处于"无记忆"状态。

## 根因

- `tools/memory_tools.py::RecallTool.execute` 直接调 `ltm.search_facts(query)`——`repository.search_facts` 把**整句自然语言 query** 作为一个 LIKE 模式（`%用户的兴趣爱好、喜欢的话题、最近感兴趣的事物%`），几乎永远 0 命中。
- `search_experiences` 拿到的 `extract_keywords` 输出是长词组（如 `用户的兴趣爱好`），LIKE 命中率同样极低。
- `memory/retrieval.py::retrieve_by_recall_tag` 是同款的坏模式（`search_facts(query)` 整句 LIKE）。
- 与之对比，memory_agent 走向量相似度所以正常——recall 路径是仅存的 LIKE 时代遗留。

## 修复

两条路径都改走 `MemoryRetriever.retrieve_for_query()` 混合检索管线（语义 0.6 + 关键词 0.4，embedding 宕机自动降级关键词评分），Agent 1/3 的 recall 与 memory context 检索同源：

- `tools/memory_tools.py:58-64`：删 `search_facts`/`search_experiences` 直调，改用 `ctx.facts[:5] / ctx.experiences[:3] / ctx.reflections[:2]`；顺带补 F4 梦境标注。
- `memory/retrieval.py:91-95`（`retrieve_by_recall_tag`）：同样改走 `retrieve_for_query`。

## 验证

- 真库（data/ai_friend.db，session=小星）三条此前 0 命中的 query：`facts=10 exps=5 refl=3`。
- 全量：`pytest tests --ignore=tests/real_api -q` → **810 passed** 全绿。

## 备注

- `repository.search_facts` 的整句 LIKE 行为未改（无其他生产调用方受害）；若后续有新调用方，建议同步改为关键词/语义评分。
