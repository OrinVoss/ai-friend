# 2026-07-13 修复 dispatcher 把 notify 的 title 当成 song 的别名冲突

## 修改原因

`core/dispatcher.py` 的 `_normalize_args` 全局把 `title` 映射为 `song`，
导致 notify 工具收到的参数变成：

```python
{'message': '发个通知', 'duration': 5, 'song': '通知'}
```

原本应该有的 `title` 字段被吃掉了，所以 notify 一直报"标题不能为空"。

## 修改文件

- `core/dispatcher.py`
  - `_normalize_args` 的 song 别名组不再包含 `title`，只保留
    `song_name` / `track`。
- `tools/music_tool.py`
  - `MusicPlayTool.execute` 本地兼容 `title` / `song_name` / `track` 别名，
    不影响 notify。
- `tests/test_dispatcher.py`
  - 新增 `test_title_not_mapped_to_song`：确保 notify 的 title 不会被转换。
  - 新增 `test_song_name_and_track_aliases`：确保 music 工具别名仍然可用。

## 验证

```bash
python -m pytest tests/test_dispatcher.py tests/test_notify_tool.py -v
# 46 passed
```
