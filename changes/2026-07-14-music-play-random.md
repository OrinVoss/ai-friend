# 修复 music_play 不支持随机播放

## 问题

用户说"随便放一首歌"时：
- Agent 2 调用 `music_play(song="random")` 直接失败，因为工具不支持 "random"
- 然后 Agent 2 改用 `glob` 在项目根目录 `.` 下递归搜索 `**/*.mp3` / `**/*.flac`，触发 10000 文件上限，效率极低

## 修复

`tools/music_tool.py`：
- `MusicPlayTool.execute` 新增对 `song="random"` / `"随机"` / `"随便"` 的支持
- 随机时扫描 `MUSIC_DIR` 下所有音频文件，随机选择一首播放
- 抽取 `_collect_songs` 和 `_find_matches` 方法，复用扫描逻辑
- 更新工具描述，说明支持随机播放

## 测试

新增 `tests/test_music_tool.py`：
- 测试 `music_list` 列出音乐目录
- 测试 `music_play(song="random")` 成功播放
- 测试空目录下随机播放失败
- 测试按精确文件名播放

```bash
python -m pytest tests/test_music_tool.py -v
# 4 passed
```
