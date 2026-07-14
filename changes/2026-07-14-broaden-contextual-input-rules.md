# 放宽 Agent 1 的上下文简短输入规则

## 变更

`prompts/system.py` 的 `build_inner_drive_prompt` 中，内驱检查清单的上下文规则从具体的：

> 如果刚放过音乐，用户说歌名 → 播放这首歌  
> 如果刚读过文件，用户说文件名 → 读取这个文件

扩展为更通用的规则：

> 用户是否只说了一个简短名词、数字或短语？这很可能是对上一个操作的继续、修正或具体化。

覆盖 music_play、read_file/glob/grep、web_search/web_fetch、notify 等工具的上下文，并包含"换一个"/"再来一个"/"这个"/"那个"/"好"/"行"等继续词。

## 验证

```bash
python -m pytest tests/test_message_handler.py tests/test_inner_drive.py -v
# 45 passed
```
