# 新增 file_tree 目录树工具

## 背景

文件工具（read_file / glob / grep）默认从项目根目录搜索，Agent 经常在不了解目录结构的情况下就发起宽泛递归搜索（如 `glob **/*.mp3 root=. `），导致扫描大量无关文件。其他 Agent 框架通常先给模型一个 `file_tree` 工具了解结构，再精确读取。

## 改动

### 1. `tools/file_tools.py`

新增 `FileTreeTool`：
- 参数 `path`：目录路径（默认项目根目录）
- 参数 `depth`：最大递归深度（1-4，默认 2）
- 返回树状文本，自动跳过 `.git`、 `__pycache__`、`.venv` 等目录
- 每个目录最多显示 10 个文件，总节点数限制 200
- 受 `_path_in_allowed` 安全约束

### 2. 工具注册

- `tools/traits.py`：`EXTERNAL_TOOL_NAMES` 加入 `file_tree`
- `main.py`：导入并注册 `FileTreeTool`
- `tests/mocks.py`：mock registry 加入 `file_tree`

### 3. Prompt 更新

- `core/inner_drive.py`：`INNER_DRIVE_SCHEMA` 的工具描述加入 `file_tree`
- `prompts/system.py`：
  - Agent 1 的内驱推理提示增加 "file_tree — 你想先了解某个目录的结构再读文件"
  - Agent 2 的工具调用提示增加 "用户想先了解目录结构 → 调用 file_tree"

### 4. 测试

新增 `tests/test_file_tools.py`：
- 基本树形输出
- depth 限制
- 路径不在允许范围
- 非目录输入
- ReadFileTool 读取目录列表

更新 `tests/test_tool_agent.py`：外部工具列表加入 `file_tree`。

## 验证

```bash
python -m pytest tests/test_file_tools.py tests/test_tool_agent.py tests/test_message_handler.py tests/test_inner_drive.py -v
# 64 passed
```
