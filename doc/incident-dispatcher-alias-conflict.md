# Incident：dispatcher 全局别名映射导致 notify 工具 title 参数丢失

## 现象

用户要求 AI 发送 Windows 桌面通知时，`notify` 工具连续失败，错误信息为：

```text
标题不能为空，收到的参数：{'message': '发个通知', 'duration': 5, 'song': '通知'}
```

LLM 明明在工具调用中传了 `title`，但 `notify_tool.execute()` 收到的参数里却找不到 `title`，只有 `song`。

## 根因

`core/dispatcher.py` 的 `_normalize_args()` 对所有工具参数做全局别名映射：

```python
aliases = [
    (("query", "search", "keyword", "question"), "query"),
    (("text", "msg", "content"), "content"),
    (("person", "who", "user", "target"), "name"),
    (("filepath", "filename", "file", "path"), "path"),
    (("song_name", "title", "track"), "song"),   # ← 问题在这里
    (("directory", "dir", "folder"), "path"),
]
```

为了让 `music_play` 支持"播放 title: xxx"，代码把 `title` 作为 `song` 的全局别名。
但 `notify` 工具同样使用 `title` 作为"通知标题"参数，于是 dispatcher 在分发前就把 `title` 改写成了 `song`，notify 工具自然找不到标题。

## 影响范围

- **notify 工具**：任何需要 `title` 的调用都会因为标题丢失而失败。
- **music_play 工具**：不受影响，反而因此多获得了一种用户表达方式。
- **未来新增工具**：如果某个工具也使用 `title`、`text`、`msg`、`user`、`target` 等通用参数名，同样会被意外改写。

## 修复方案（已实施）

### 1. 移除 `title → song` 的全局映射

`core/dispatcher.py`：

```python
# 修复前
(("song_name", "title", "track"), "song"),

# 修复后
(("song_name", "track"), "song"),
```

### 2. music_play 本地兼容 title 别名

`tools/music_tool.py`：

```python
song = (
    args.get("song", "").strip()
    or args.get("title", "").strip()
    or args.get("song_name", "").strip()
    or args.get("track", "").strip()
)
```

### 3. notify 工具增强参数兼容与错误提示

`tools/notify_tool.py`：

```python
message = (
    args.get("message", "").strip()
    or args.get("content", "").strip()
    or args.get("text", "").strip()
    or args.get("msg", "").strip()
    or args.get("body", "").strip()
)
```

同时把"标题和内容不能为空"的模糊提示改为返回实际收到的参数，方便 LLM 根据错误调整。

### 4. 增加 dispatcher 工具失败日志

`core/dispatcher.py` 在 `execute_tool_calls()` 中对每个失败工具打印：

```python
logger.warning(f"[tool] {r['name']} failed: {r['output'][:200]}")
```

这让线上排查可以直接看到失败原因和参数。

### 5. 测试覆盖

- `tests/test_dispatcher.py`：新增 `test_title_not_mapped_to_song`、`test_song_name_and_track_aliases`。
- `tests/test_notify_tool.py`：新增 content/text/msg/body 别名测试、错误提示测试。

## 相关提交

- `83565e1` fix(notify): accept content alias for message and sync inner_drive tests
- `b33e211` chore(logging): add tool failure and notify arg logging for easier debugging
- `2b5327f` fix(notify): accept text/msg/body aliases and return clearer errors
- `506df9e` fix(dispatcher): stop stealing title for song alias; fix notify failures

## 遗留风险

`_normalize_args` 仍是**全局**别名映射，以下别名组仍有潜在的参数名冲突：

| 别名组 | 冲突场景 |
|---|---|
| `text/msg/content → content` | 未来某个工具若使用 `text` 或 `msg` 作为原生参数名，会被抢走 |
| `person/who/user/target → name` | 未来某个工具若使用 `user` 或 `target` 作为原生参数名，会被抢走 |
| `filepath/filename/file/path → path` | 相对安全，但 `path` 本身是通用参数名 |

## 长期建议

逐步取消 dispatcher 的全局别名映射，改为**各工具内部处理自己的参数别名**。这样每个工具对自己的参数命名负责，互不干扰。

示例：

```python
# web_search_tool.py
query = (
    args.get("query", "").strip()
    or args.get("search", "").strip()
    or args.get("keyword", "").strip()
)

# read_file_tool.py
path = (
    args.get("path", "").strip()
    or args.get("file", "").strip()
    or args.get("filepath", "").strip()
)
```

dispatcher 只保留解析和分发职责，不再修改参数名。

## 经验教训

1. 全局参数别名映射会隐藏跨工具的命名冲突，应谨慎使用。
2. 工具失败日志必须包含实际收到的参数，否则很难定位"参数被改写"类问题。
3. 单元测试应覆盖 dispatcher 的别名行为，而不仅是单个工具的 execute。
