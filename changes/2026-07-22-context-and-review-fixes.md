# 2026-07-22 Context & 审查修复

## 修改文件

| 文件 | 修改 |
|------|------|
| `core/context_manager.py` | T1+T2+T3+T4 |
| `core/message_handler.py` | T1 调用方修改 |
| `core/agent.py` | T1 代理方法 + 移除未用导入 |
| `core/inner_drive.py` | T5 抽取 `_decision_loop` |
| `tests/test_message_handler.py` | T1 测试 mock 适配 |

## 修改详情

### T1: ContextManager.should_compress() (#295 审查意见 4)

- `core/context_manager.py`：新增 `should_compress(estimated_tokens) -> bool` 方法（阈值判断统一入口）
- `core/agent.py`：新增同名代理方法 `should_compress()` 委托给 `_context.should_compress()`（`compress_context` 的同等模式）
- `core/message_handler.py._build_messages()`：两处内联 `> COMPRESS_THRESHOLD` 改为 `agent.should_compress()`
- 移除 `message_handler.py` 和 `agent.py` 中不再使用的 `COMPRESS_THRESHOLD` 导入
- `tests/test_message_handler.py`：为 mock agent 添加 `should_compress = MagicMock(return_value=False)` 保持测试通过（MagicMock 默认返回 truthy，导致溢出判断总是成立）

### T2: estimate_tokens LRU 缓存 (#295/#103 余项)

- `core/context_manager.py`：
  - 提取 `_estimate_tokens_impl(text)` 纯逻辑函数
  - `_estimate_tokens_cached` 加 `@lru_cache(maxsize=2048)` 装饰
  - `estimate_tokens()` 改为空字符串短路 + 超长文本(>4000 chars)直走 `_impl` 避免缓存污染 + 常规文本走缓存
  - 降级分支逻辑不变，一并进缓存

### T3: 压缩输入不再均匀截断 (#295 审查意见 1/5)

- `core/context_manager.py._do_compress()`：
  - 旧逻辑：逐条 `content[:500]` 截断 + 整体 `text[-8000:]` 截尾
  - 新逻辑：最近 6 条完整保留（`RECENT_FULL_TURNS`），更早的每条短截断到 120 字符（`OLDER_SNIPPET`），总字符预算上调到 12000（`MAX_COMPRESS_INPUT`）
  - 常量提为模块级，跟随 `COMPRESS_THRESHOLD` 风格

### T4: 压缩摘要增量合并 (#295 审查意见 2 务实版)

- `core/context_manager.py._do_compress()`：有旧摘要时构造合并输入 `【已有历史摘要】+【新增对话】`，LLM 同时看到上下文；`CONTEXT_COMPRESS_PROMPT` 文案不动；压缩失败时旧摘要保留（现状保持）

### T5: InnerDrive 推理循环抽取 _decision_loop (#293 P1-2)

- `core/inner_drive.py`：
  - 新增 `_decision_loop(messages, *, on_parse_failed, source='inner_drive', max_tokens=None)` 私有方法
  - 公共逻辑：LLM 生成 → JSON 解析 → recall_query 子循环（`execute_tool_calls` + 结果喂回）→ max iterations 处理
  - `assess()` / `review()` / `re_decide()` 改为薄壳：各自的 prompt 构建 + fallback 工厂 + 日志 tag 保留，`_decision_loop` 为空壳处理循环本体
  - `assess_proactive` / `assess_agent3_intent` 不动（红线）
  - 新增 `import typing` 用于 `Callable` 类型标注（运行时无影响）

### T6: 循环导入现状确认（只记录，不改）

- `python -X dev -c "import core.agent, web.server, memory.consolidation, core.context_manager, core.message_handler, core.inner_drive, core.cli_controller, core.provider, memory.short_term, tools.traits, tools.memory_tools, core.dispatcher, core.cognitive_state, prompts.system"` → 全部成功，无循环导入错误
- 已知 lazy import 点：
  - `context_manager._do_compress → prompts.system`（保留）
  - `inner_drive._decision_loop → core.dispatcher`（新增，与旧 `assess` 同）
  - `message_handler._ensure_inner_drive → core.inner_drive`（保留）
  - `agent.decide_proactive_action → core.inner_drive`（保留）
- 结论：所有 lazy import 均必要，无需修改

## 回归测试

- `python -m pytest tests --ignore=tests/real_api -q` → **840 passed, 2 skipped**
  - 840 passed + 2 skipped (embedding server 未运行) = 842 collected，与基线等价
  - 3 个 message_handler 测试因 mock 适配已挽回
- `python -m py_compile core/*.py tools/*.py memory/*.py storage/*.py web/*.py models/*.py prompts/*.py` → 全通过
