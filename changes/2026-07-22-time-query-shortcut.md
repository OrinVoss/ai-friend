# 修复：Agent 1 时间查询短路——"上下文已有答案"不再触发工具链

日期：2026-07-22

## 背景

监控 Review 发现：用户问"现在几点"时，系统走了「Agent 1 决策 → Agent 2 工具（返回空）→ Agent 3 回复」的远路。实际上 `build_inner_drive_prompt` 首行就动态注入了 `当前时间：...`，Agent 1 手里有牌却不知道。

## 根因

`prompts/instructions.py::INNER_DRIVE_CHECKLIST` 首条把"时间"列为潜在工具触发项（"用户是否提到了你不知道的事实、数据、新闻、天气、**时间**？"），引导 Agent 1 为时间问题寻找工具——而工具层根本没有"获取时间"工具，只能返回空，再绕回 Agent 3 用上下文兜底。Agent 3 侧本就有"有人问时间直接告诉ta"的规则，缺口只在 Agent 1。

## 修复

`INNER_DRIVE_CHECKLIST` 首条拆为两条：

- 外部事实类保留：事实、数据、新闻、天气；
- 新增明示：问时间/日期/星期——当前时间就写在上文，直接回答，**永远不需要为此调用工具**。

即 Review 中"方案一"的最小实现（决策层可见"上下文已有答案"）；方案三（Agent 3 硬规则）原本已存在，无需重复建设。

## 测试

- `tests/test_prompt_instructions.py::TestTimeQueryNoToolRule`（2 用例）：清单含"永远不需要为此调用工具"；Agent 1 完整 prompt 同时含动态时间与该规则。
- 全量：`pytest tests --ignore=tests/real_api -q` → **842 passed** 全绿。
