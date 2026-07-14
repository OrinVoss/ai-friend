# 更新 known-issues：补充架构与 Prompt 改进建议

## 背景

需要把 Claude Code 的审查建议集中写入 `doc/known-issues.md`，作为后续重构的参考清单。这些建议只谈需要改进的地方，不谈优点。

## 修改

- `doc/known-issues.md`：新增第 3 节"架构与 Prompt 改进建议（Claude Code 建议）"，包含：
  - 架构建议：Observation / Fact / Insight 分层、Reflection 改为假设、React 不直接读取 Reflection、Fact 允许降级
  - Prompt 建议：缩短 React Prompt、Personality 与 Prompt 解耦、精简 Tool Agent Prompt
  - Memory 建议：增加 Source、四维评分、低频 Reflection
  - Episode 建议：结构化保存、增加 Importance
  - Retrieval 建议：多阶段检索、不同 Agent 使用不同 Context
  - 长期稳定性建议：Memory GC、Reflection 过期重生成
  - 优先级排序：列出最值得优先做的四件事

## 效果

- 技术债务文档完整记录了当前架构层面的改进方向
- 为后续 Memory、Reflection、Retrieval 重构提供了明确的优先级

## 验证

- 文档格式检查通过
- 无代码变更，无需运行测试

## 提交

待提交
