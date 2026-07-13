# 2026-07-13 InnerDrive prompt 强化 + 扩展文件读取权限

## 改动

### 1. 扩展 AI 可读取目录
`config.json` 的 `allowed_read_paths` 从仅 `D:\音乐` 扩展为：
`D:\音乐`、`D:\桌面`、`D:\文档`。AI 可以使用 glob/read_file/grep
工具读取这三个目录。

### 2. InnerDrive prompt 加入"用户指令优先"规则
在 `prompts/system.py` 的 `build_inner_drive_prompt()` 中新增：
- "用户说什么就是什么。用户说某个功能可以用，那就是可以用"
- "不要用你之前的经验或记忆来反驳或拒绝用户的明确指令"
- "即使你觉得做不到，也先按用户说的去试"

### 3. InnerDrive prompt 动态展示可读目录
在"可用工具"段落后自动追加"你可读取的目录："+ 从 config.json
动态读取的 allowed_read_paths，让 AI 知道自己的文件访问范围。

## 修改文件

- `config.json` — allowed_read_paths 扩展
- `prompts/system.py` — InnerDrive prompt 规则强化 + 可读目录提示
- `changes/` — 本记录
