# 移除 Agent 1 短输入跳过机制

用户决策：LLM API 成本低，为省一次调用承担关键词误判不值得。`_should_skip_llm` 整体移除，所有输入一律走完整 Agent 1 推理。

## 问题

短输入跳过（#160 引入）用 40+ 个硬编码关键词子串判断「这句闲聊不用调 LLM」，误判双向存在：

- **漏判（功能丢失）**：「我想听周杰伦」（关键词是「听歌」）、「放一首晴天」（关键词是「放歌」）被误判为闲聊，工具意图直接丢
- **误伤（浪费调用）**：「今天去医院检查了」命中「查」、「你看呢」命中「看」，无端不跳过

`doc/systematic-solution.md` 曾立案并给出语义相似度方案；最终选择更简单的答案——删掉。优化方案本身（向量锚点）在 Memory Agent 线索里已有同款实践，但为「省一次调用」这个目的服务，投入产出不成正比。

## 改动

- `core/inner_drive.py`：删除 `_should_skip_llm()`、`TOOL_KEYWORDS`、构造函数 `short_input_threshold` 参数、assess() 的预筛选分支
- `core/message_handler.py`：移除 `short_input_threshold` 传参
- `config.py`：删除 `agent1_short_input_threshold` 字段 + 校验 + env_map 项；`config.example.json` / `config.json` 同步删除
- 测试：
  - `tests/test_inner_drive.py`：跳过测试改为「短输入同样走完整 LLM 推理」；删除 2 个基于跳过前提的测试
  - `tests/test_memory_agent_integration.py`：短输入用例改为「provider.generate 被调用 + 仍走 MemoryAgent」
  - `tests/test_message_handler.py`：setUp 补 `to_prompt_summary` 真实返回值与 `use_memory_agent=False`（此前这些测试靠短输入跳过避开了 prompt 构建和 MA 装配，删除后暴露出来）
- 文档：`config-reference.md`（字段/环境变量/示例 JSON）、`architecture.md`、`prompt-reference.md`、`message-flow.md`（3 处图）、`technical.md`、`deployment.md`、`known-issues.md`（#160 修复记录补后续）、`systematic-solution.md`（立案标记已解决并说明决策）、`refactor/progress.md`、`refactor/enhancement-overview.md`、`refactor/layer2-prompt/README.md` / `progress.md`

## 影响

- 每条用户消息都会触发一次 Agent 1 LLM 调用（包括「你好」）——成本可接受，行为更一致
- Agent 1 不再有任何「不看内容就下结论」的路径；闲聊仍由 LLM 判定不需要工具后直达 Agent 3

## 测试

- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **466 passed**（净 -2 用例：删除跳过前提测试）
