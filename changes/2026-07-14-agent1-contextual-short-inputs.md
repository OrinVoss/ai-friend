# 让 Agent 1 理解上下文中的简短指令（如歌名）

## 问题

用户之前让 AI "随便放一首歌"，AI 播放后用户只发了 "Teeth"（想播放这首歌）。Agent 1 把它理解为"对刚才播放的歌做反馈"，判断 `needs_tools=False`，没有调用 `music_play`。

## 修复

### 1. `prompts/system.py` 的 `build_inner_drive_prompt`

- 新增 `tool_call_history` 参数
- 在 Agent 1 的 prompt 中显示最近 5 条工具调用记录
- 内驱检查清单增加：
  - "用户是否只说了一个简短名词（如歌名、文件名）？"
  - "结合最近工具历史判断：如果刚放过音乐，用户说了一个歌名 → 要播放这首歌"

### 2. `core/inner_drive.py`

- `InnerDriveAgent.__init__` 新增 `tool_call_history` 参数
- 所有调用 `build_inner_drive_prompt` 的地方传入 `tool_call_history`

### 3. `core/message_handler.py`

- 初始化 `InnerDriveAgent` 时传入 `a._tool_call_history`

## 验证

```bash
python -m pytest tests/test_message_handler.py tests/test_inner_drive.py -v
# 45 passed
```
