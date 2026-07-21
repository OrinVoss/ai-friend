# Layer 2 收尾 — 实施计划（供低成本模型执行，详版）

> 日期：2026-07-20。依据：`doc/refactor/layer2-prompt/progress.md` 待完成项（3 项）。
> 本文档面向执行者：每项给出根因位置、做法、测试、验收。**严格按项执行，不做清单之外的"顺手优化"。**
> 项目：D:/桌面/编程作品/AI朋友，Python 3.13，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **693 用例（691 passed + 2 skipped）**，改完必须全绿且不减少。

---

## L2-1：`load_config()` 去重（消除工具层的重复加载）

**根因**：`tools/file_tools.py:46` 在**每次工具执行**时调 `load_config()` 读磁盘 + 打日志——生产日志里一条用户消息出现 2-4 次 `[config] loaded from: config.json`。L-10/L-12 只收敛了 web 入口，工具层漏了。

**做法**：
1. `config.py` 的 `load_config` 加进程内缓存：`functools.lru_cache(maxsize=1)` 或直接模块级 `_CACHED: Config | None`（选后者，可读性更好；提供 `reload_config()` 清缓存供测试和将来热更新用）。
2. `web/server.py:26` 模块级 `config = load_config()` 不变（自动受益）。
3. 注意：`load_config(path)` 带自定义 path 的调用（测试）必须绕过缓存——只对默认 `CONFIG_PATH` 缓存。

**测试**（`tests/test_config.py`）：连续两次 `load_config()` 只读一次盘（patch `open` 计数）；`reload_config()` 后重新读；自定义 path 不进缓存。

**验收**：生产日志一条消息内 `[config] loaded` 至多出现一次（首次）。

---

## L2-2：Prompt Cache 命中率与 token 节省监控

**根因**：`core/prompt_cache.py` 有 hit 日志（:79）但没有统计——命中率、节省的字符量不可见，无法验证 #160 的收益。

**做法**：
1. `core/prompt_cache.py` 增加计数器（实例属性，线程安全用 `threading.Lock`）：`hits` / `misses` / `saved_chars`（hit 时块的长度）。
2. 新增 `stats() -> dict` 方法；`MessageHandler` 或 Agent 在每次 `build_*_prompt` 调用后 debug 日志输出累计：`[prompt_cache] stats: hit_rate=xx% saved=N chars`（debug 级，避免刷屏；或每 50 次调用输出一次 info）。
3. 监控端点：`core/monitor.py`（如已有 LLM 监控环形缓冲）顺手暴露该 dict；没有就算了，不做 Web UI。

**测试**（`tests/test_prompt_cache.py` 追加）：hit/miss 计数正确、saved_chars 累计正确、stats() 结构。

---

## L2-3：Agent 3 prompt 块必要性评估（仅评估 + 文档，不改代码）

**背景**：`progress.md` 遗留「评估梦境、共同回忆等块的必要性」。R4（2026-07-20）已处理梦境块（idle≤600 不注入 + sleep 轮过滤）。剩余问题：共同回忆（experiences）块在 Agent 3 是否值得保留。

**做法**（纯分析，输出评估记录，不改代码）：
1. 抓一份生产 react prompt（日志 `chars_in` + `prompts/system.py::_build_memory_block` 结构），量化各块占比：人格/情绪/关系/事实/回忆/对话历史/工具规则。
2. 评估结论写入 `doc/refactor/layer2-prompt/progress.md`（每个块：保留/压缩/删除 + 一句理由）。**任何压缩改动不在本计划内**——结论需人工确认后再立项。

**验收**：progress.md 里有成文的块级评估结论。

---

## 明确不做

- 不压缩/删除任何 prompt 块（L2-3 只评估）
- 不做 Prompt Cache 的 Web 可视化
- 不动 `build_system_prompt` 的结构

## 执行顺序与验收总表

| 顺序 | 项 | 风险 | 关键验收 |
|------|----|------|----------|
| 1 | L2-1 load_config 缓存 | 低 | 日志一条消息一次 loaded |
| 2 | L2-2 命中率监控 | 低 | stats() 计数正确 |
| 3 | L2-3 块评估 | 无 | progress.md 评估结论成文 |

全部完成后：`python -m pytest tests --ignore=tests/real_api -q` 全绿（≥693 用例）；`doc/refactor/layer2-prompt/progress.md` 三项打勾（L2-3 标「评估完成」）；新建 `changes/2026-07-2X-layer2-tail.md`。
