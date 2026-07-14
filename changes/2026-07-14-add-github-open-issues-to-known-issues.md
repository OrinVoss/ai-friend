# 在 known-issues 中补充 GitHub 待处理 Issue 清单

## 背景

`doc/known-issues.md` 目前只记录了本地发现的问题。为了把 GitHub 上仍然 Open 的 Issue 也纳入统一视图，需要拉取并整理到文档中。

## 修改

- `doc/known-issues.md`：新增第 4 节「GitHub 待处理 Issue 清单」。
  - 从 [OrinVoss/ai-friend](https://github.com/OrinVoss/ai-friend/issues) 拉取当前 Open Issue（共 24 条）。
  - 按表格形式列出编号、标题、标签、链接。
  - 保留最新审查类 Issue（#295 / #294 / #293）在前，其余按原列表顺序排列。

## 效果

- 技术债务文档同时覆盖本地建议与 GitHub 远程 Issue。
- 后续排期时可以一次性看到所有待处理项，避免重复创建 Issue。

## 验证

- 文档格式检查通过
- 无代码变更，无需运行测试

## 提交

待提交
