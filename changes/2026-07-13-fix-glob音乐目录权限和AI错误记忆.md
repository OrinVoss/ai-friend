# 2026-07-13 修复 glob 工具无法访问 D:\音乐 + AI 记忆错误

## 现象

用户要求 AI 调用音乐工具列出歌曲时，Agent 1（InnerDrive）反复拒绝执行，
理由为"音乐目录(D:\音乐)不可访问、glob 工具被禁用"。即使通过穿透域名
登入后用户直接下令，AI 仍坚持无法操作。

## 根因

两个问题叠加：

1. **glob / grep 工具未配访问 D:\音乐**（工具层）
   - `_get_allowed_roots()` 默认只返回项目根目录，配置项
     `config.allowed_read_paths` 为空时 `D:\音乐` 永远被拦。
   - `glob` 和 `grep` 的 `description()` 写死了"可搜索 D:\音乐"，
     但实际没有该权限，误导了 LLM 的调用决策。

2. **AI 积累了错误的长期记忆**（记忆层）
   - 首次失败后 AI 记住了"音乐目录不可访问"作为高置信度事实
     （`confidence=1.00`），后续对话中每次 Recall 都强化该结论，
     导致 Agent 1 直接 `needs_tools=False`，不再尝试调用音乐工具。

## 修复

1. `config.json` — 新增 `allowed_read_paths: ["D:\\音乐"]`，使 glob/grep
   工具可以搜索音乐目录。
2. `tools/file_tools.py` — `ReadFileTool.description()` 更新为动态描述，
   不再硬编码 D:\音乐等路径。
3. `tools/search_tools.py` — `GlobTool.description()` 和
   `GrepTool.description()` 同步更新。
4. `data/ai_friend.db` — 删除错误的记忆事实（id=57 音乐目录不可访问、
   id=60 音乐工具权限被拒绝）、对应的 experiences（id≥16）和
   reflections（id≥20），防止旧记忆干扰新尝试。

## 修改文件

- `config.json` — 新增 `allowed_read_paths`
- `tools/file_tools.py` — 描述更新
- `tools/search_tools.py` — 描述更新
- `changes/` — 本记录
