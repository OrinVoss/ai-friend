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

## 3. 架构与 Prompt 改进建议（Claude Code 建议）

> 以下建议来自 Claude Code 的审查，只谈需要改进的地方，不谈优点。按模块分组，最后给出优先级排序。

---

## 架构建议

### 3.1 严格区分 Observation、Fact、Insight（最重要）

目前很多 Memory 存在"一步推理"的问题。

建议改成三级：

```
Observation（观察）
↓
Fact（多次验证后的事实）
↓
Insight（基于多个事实的假设）
```

例如：

错误：

```
用户播放月光奏鸣曲
↓
喜欢月光奏鸣曲
```

正确：

```
Observation
今天播放了月光奏鸣曲

↓

连续多次主动播放

↓

Preference
喜欢古典音乐（confidence 0.81）
```

Memory 永远不要跨层升级。

---

### 3.2 Reflection 不要生成"结论"，而要生成"假设"

目前 Reflection Prompt 太开放。

建议输出格式改成：

```
TYPE

OBSERVATION

EVIDENCE

HYPOTHESIS

CONFIDENCE

NEEDS_MORE_EVIDENCE
```

例如：

```
Observation:
用户连续三次主动开启互怼。

Evidence:
episode12
episode18
episode25

Hypothesis:
用户可能偏好互损式交流。

Confidence:
0.47

Need more evidence:
true
```

而不是：

```
用户真正需要的是……
```

这种最终结论。

---

### 3.3 React 不应该直接读取 Reflection

建议：

```
React

↓

Episode
Emotion
Fact
Relationship
```

只有

```
Planner
Inner Drive
```

需要的时候再 Retrieve Reflection。

否则 Reflection 会不断影响下一轮 Reflection，形成自我强化。

---

### 3.4 Fact 必须允许被降级

目前 Fact 更像 append-only。

建议增加：

```
confidence_decay()

merge()

contradict()

obsolete()
```

例如：

```
用户喜欢 Teeth
```

连续30天没有证据。

自动：

```
0.84

↓

0.61

↓

Observation
```

而不是永久存在。

---

## Prompt 建议

### 3.5 React Prompt 太长

建议：

React 只保留：

```
人格

当前情绪

最近3个 Episode

Top5 Fact

Relationship

当前任务
```

不要每轮塞：

- 梦境
- Reflection
- 长篇共同回忆
- 大量示例
- 很多 Rules

这些 Token 利用率非常低。

---

### 3.6 Personality 不应该放 Prompt

建议做成：

```
persona.json
```

例如

```
warmth

humor

curiosity

verbosity

style

boundaries
```

运行时自动渲染。

Prompt 只放：

```
Current Personality State
```

---

### 3.7 Tool Agent Prompt 可以砍掉一半

Tool Agent 不需要知道：

- 人格
- 关系
- 情绪
- 共同回忆
- 梦想

只需要：

```
Task

Available tools

Schema

Retry history
```

即可。

---

## Memory 建议

### 3.8 Memory 增加来源（Source）

每条 Fact 建议增加：

```
source

episode_ids

created_by

created_at

last_verified

verification_count
```

以后可以做：

- 可信度排序
- 证据追踪
- 删除污染 Memory

---

### 3.9 Memory 不要只有 confidence

建议：

```
confidence

freshness

stability

importance
```

四个维度。

例如：

```
喜欢吃火锅

confidence
0.96

freshness
0.15

stability
0.95

importance
0.32
```

而不是只有一个 confidence。

---

### 3.10 Reflection 应该低频运行

建议：

不要每轮都 Reflection。

改成：

```
满足任一条件：

累计20条 Episode

重要事件

关系变化

连续聊天30分钟

用户主动分享

长期计划变化
```

才生成 Reflection。

---

## Episode 建议

### 3.11 Episode 不要直接写自然语言摘要

建议同时保存：

```
raw conversation

structured event

emotion

entities

intent
```

以后 Retrieval 可以灵活很多。

---

### 3.12 增加 Episode Importance

例如：

```
普通闲聊
0.08

第一次见面
0.92

用户分享家庭
0.95

一起完成项目
0.88
```

Reflection 优先读取高 Importance Episode。

---

## Retrieval 建议

### 3.13 Retrieval 做多阶段

不要：

```
Embedding TopK
```

建议：

```
Query

↓

Intent

↓

Fact

↓

Episode

↓

Reflection

↓

Rank

↓

Context Builder
```

这样 Prompt 会短很多。

---

### 3.14 不同 Agent 使用不同 Retrieval

例如：

```
React

只读：
Fact
Episode

Planner

Fact
Episode
Reflection

Fact Extractor

Episode

Tool Agent

不读 Memory
```

不要所有 Agent 都共享 Context。

---

## 长期稳定性建议

### 3.15 增加 Memory GC（Garbage Collection）

建议每天运行：

```
Merge Duplicate

Decay Confidence

Delete Noise

Compress Episode

Rebuild Reflection
```

否则 Memory 一年以后一定污染。

---

### 3.16 Reflection 不应该成为永久 Memory

建议：

```
Reflection

↓

过期

↓

重新生成
```

不要永久保存。

Insight 应该随着新 Evidence 自动更新。

---

## 我认为最值得优先做的四件事（按优先级）

1. **重构 Reflection：从"结论"改成"带证据的假设"。**
2. **拆分 Observation → Fact → Insight 三层 Memory，禁止跨层推理。**
3. **React 默认不读取 Reflection，只在 Planner 需要时检索。**
4. **建立 Memory 生命周期（创建 → 验证 → 衰减 → 合并 → 删除），避免长期自我污染。**

如果把这四点做好，整个 Agent 的长期稳定性和可维护性都会提升一个档次。

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
