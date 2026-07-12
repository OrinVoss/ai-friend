# 修改记录：第3轮安全性审查（工具权限边界）

**日期**：2026-05-31
**审查人**：Claude Code
**审查范围**：`tools/`、`core/dispatcher.py`、`core/tool_agent.py`、`core/inner_drive.py`、`core/agent.py`、`prompts/system.py`、`main.py`、`web_main.py`、`web/session.py`、`config.py`

## 修改的文件

- 新建 `doc/round03-tool-permissions.md`：完整的工具权限边界安全性审查报告

## 修改原因

对 AI Friend 项目进行第3轮安全性审查，聚焦工具权限边界。发现 22 项安全风险，其中严重 5 项、高危 7 项、中危 6 项、低危 4 项。

## 修改内容摘要

生成约 6000 字的安全性审查报告，包含：

1. **架构隔离失效**（严重）：Agent 1 和 Agent 3 在代码层面可直接调用全部外部工具，仅靠提示词约束
2. **路径遍历风险**（严重）：`read_file`、`glob`、`grep` 使用不安全的 `startswith` 路径校验，未解析符号链接
3. **命令注入风险**（严重）：`notify` 工具存在 PowerShell 字符串拼接注入；`music_play` 使用 `os.startfile()` 且未校验文件头
4. **SSRF 风险**（高危）：`web_fetch` 未对目标 URL 进行内网地址过滤
5. **JSON Schema 不完整**（高危）：`to_json_schema()` 仅返回 `{"type": "json_object"}`，无结构约束
6. **工具权限元数据缺失**（高危）：`ToolRegistry` 缺乏权限等级、Agent 授权等元数据
7. **提示词注入防御薄弱**（高危）：Agent 1 的决策解析基于简单关键词匹配
8. **默认配置过松**（中危）：`allowed_read_paths` 默认包含桌面、文档、下载目录

报告包含每项发现的文件路径、行号、风险评级、攻击场景和修复建议。
