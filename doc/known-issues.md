# 已知问题与技术债务

> 记录当前系统中存在、但暂不紧急处理的问题。
> 这些问题不会导致服务无法运行，但可能在特定场景下引发 bug 或增加维护成本。

---

## 1. dispatcher 全局参数别名映射的潜在冲突

### 状态

- 已修复：`title` 被错误映射为 `song`，导致 `notify` 工具标题丢失的问题
- 遗留风险：`_normalize_args` 仍是全局映射，未来可能再次冲突

### 详情

`core/dispatcher.py` 的 `_normalize_args()` 对所有工具参数做统一别名转换：

```python
aliases = [
    (("query", "search", "keyword", "question"), "query"),
    (("text", "msg", "content"), "content"),
    (("person", "who", "user", "target"), "name"),
    (("filepath", "filename", "file", "path"), "path"),
    (("song_name", "track"), "song"),
    (("directory", "dir", "folder"), "path"),
]
```

这种"一刀切"的设计导致 `title` 曾被当作 `song` 的别名吃掉，使 `notify` 工具连续失败。
虽然 `title → song` 已被移除，但以下别名组仍有潜在冲突：

| 别名组 | 风险参数 | 冲突场景 |
|---|---|---|
| `text/msg/content → content` | `text`, `msg` | 未来某个工具若原生使用 `text` 或 `msg` 作为参数名，会被强制改写为 `content` |
| `person/who/user/target → name` | `user`, `target` | 未来某个工具若原生使用 `user` 或 `target` 作为参数名，会被强制改写为 `name` |
| `filepath/filename/file/path → path` | `path` | 相对安全，但 `path` 是通用参数名，仍需谨慎 |
| `directory/dir/folder → path` | `dir`, `folder` | 同上 |

### 为什么不现在修

- 当前所有工具都能正常工作
- 完全移除全局别名需要修改多个工具，改动面较大
- 属于架构层面的清理，优先级低于功能开发和稳定性修复

### 建议修复方案

逐步取消 dispatcher 的全局别名映射，改为各工具内部处理自己的参数别名：

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

`dispatcher` 只负责解析和分发，不再修改参数名。

### 相关文档

- 完整事件报告：`doc/incident-dispatcher-alias-conflict.md`

---

## 2. 日志中文显示乱码

### 状态

- 观察中
- 不影响功能，仅影响可读性

### 详情

Windows 环境下，日志中的中文字符（如 session 名 "小星"）有时显示为乱码（如 `С��`）。
这是控制台编码问题，与业务逻辑无关。

### 建议修复方案

- 统一日志编码为 UTF-8
- 或在 Windows 下使用 `chcp 65001`

---

## 记录规范

新增已知问题时请按以下格式：

```markdown
## 序号. 问题标题

### 状态

- 已修复 / 观察中 / 待处理

### 详情

...问题描述...

### 为什么不现在修

...优先级说明...

### 建议修复方案

...长期方案...

### 相关文档

- ...
```
