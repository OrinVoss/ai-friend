# Layer 2: Prompt 分层与静态化

## 目标

把系统提示拆成"静态块 / 慢变块 / 动态块"，只重建真正变化的部分；减少单次请求中重复构建系统提示的开销。

## 当前状态

**已完成大部分**：

- [x] 分层 Prompt Cache（`core/prompt_cache.py`）
- [x] `prompts/system.py` 拆分为独立 block 并接入缓存
- [x] ~~Agent 1 短输入直接跳过 LLM~~（已于 2026-07-16 整体移除：API 成本低，关键词误判不值得）
- [x] Agent 1 把格式化后的记忆/关系摘要传给 Agent 3，避免重复检索
- [x] 静态对话示例仅前 N 轮注入（`conversation_examples_max_turns`）
- [x] 指令文本集中管理（`prompts/instructions.py`）
- [x] 工具触发规则从 ToolRegistry 动态生成（`prompts/tools_description.py`）
- [x] 情绪格式化下沉到 `EmotionalState.to_prompt_summary()`，Runtime 只传轻量摘要
- [x] Tool Agent Prompt 精简，不再包含人格/情绪/关系/回忆

## 关键提交

- `49a6fd4` — fix #160: hierarchical prompt cache + Agent 1 context summary + short input skip
- `255b259` — refactor(prompts): centralize instructions, derive tool rules from registry (#294)
- `ea4c617` — refactor(prompts/runtime): complete #294 P2-5 - pass emotion_summary from runtime

## 缓存分层

```
静态块（无 TTL，personality 文件变更时失效）：
  - identity
  - examples
  - inner_drive_instructions
  - inner_drive_tools

慢变块（TTL 60 秒，可配置）：
  - relationship
  - memory（facts / experiences / reflections）

动态块（不缓存）：
  - current time
  - tool records
  - recent conversation
  - current emotion
```

## 配置项

```json
{
  "prompt_cache_ttl_seconds": 60,
  "agent1_short_input_threshold": 20,
  "conversation_examples_max_turns": 3
}
```

## 剩余工作

- [ ] 监控 Prompt Cache 实际命中率与 token 节省效果
- [ ] 进一步压缩 Agent 3 Prompt（共同回忆、梦境等是否每轮都需要）
- [ ] 考虑把 `personality_file` 缓存版本逻辑移到配置层，避免 `load_config()` 反复调用
- [ ] 优化 Agent 1 短输入跳过逻辑（见下节）

## Agent 1 短输入过滤优化

### 当前问题

`core/inner_drive.py::_should_skip_llm()` 使用硬编码中文关键词列表判断短输入是否需要工具：

```python
TOOL_KEYWORDS = [
    "http", "https", "www.", ".com", ".cn", ".net", ".org",
    "搜索", "查", "找", "搜", "查一下", "查查", "google", "百度",
    "放歌", "听歌", "音乐", "歌曲", "播放",
    "通知", "提醒", "闹钟",
    "文件", "路径", "读取", "读", "打开", "看", "目录", "文件夹",
    "新闻", "天气", "时间", "日期",
]
```

问题：
- **误判**："我不查了"、"别放歌" 会命中关键词，本可跳过却调 LLM
- **漏判**：用户说 "Teeth"（歌名）时没有任何关键词命中，被误判为闲聊，导致没有播放
- **不可维护**：新增工具或新场景需要不断扩展关键词表

### 目标

用结构化规则 + 语义相似度替代粗糙关键词匹配，降低误判/漏判。

### 推荐方案

#### 第一层：结构化 JSON 规则

在 `config.json` 中用 JSON 描述"什么情况下不跳过 LLM"：

```json
{
  "inner_drive_skip_filter": {
    "short_input_threshold": 20,
    "url_patterns": ["http://", "https://", "www.", "\\.com", "\\.cn"],
    "file_path_patterns": ["[A-Za-z]:\\\\", "/home/", "/Users/", "\\.txt", "\\.md"],
    "explicit_tool_verbs": ["搜索", "查", "找", "播放", "通知", "提醒", "读取", "打开"],
    "skip_examples": ["你好", "嗯", "好的", "哈哈", "行", "可以", "拜拜", "晚安", "ok", "yes"],
    "tool_examples": ["Teeth", "放首歌", "查下天气", "提醒我", "读这个文件", "搜索一下"],
    "similarity_threshold": 0.72
  }
}
```

#### 第二层：Embedding 语义相似度

当 embedding engine 可用时：

1. 把用户输入 encode 成向量
2. 跟 `skip_examples` 和 `tool_examples` 分别计算余弦相似度
3. 取最近的一个：
   - 最近的是 `tool_examples` 且相似度 > threshold → **不跳过**
   - 最近的是 `skip_examples` 且相似度 > threshold → **跳过**
   - 都不高 → 回退到第一层规则

示例：用户说 "Teeth"，会跟 `tool_examples` 中的 "放首歌" / "播放 Teeth" 语义接近，被正确判定为需要工具。

#### 第三层：保留上下文规则

最近 2 轮有成功工具调用时，短输入仍然走 LLM。这个逻辑是对的，保留。

### 为什么不直接再用一次 LLM

`_should_skip_llm` 的设计目的就是省一次 LLM 调用。如果为了判断是否跳过而再调一次 LLM，就没有优化意义。Embedding 计算轻量，成本远低于 LLM。

### 涉及文件

- `config.py` / `config.example.json`：新增配置字段
- `core/inner_drive.py`：改造 `_should_skip_llm()`，新增语义相似度判断
- `tests/test_inner_drive.py`：新增测试用例

## 依赖

- Layer 1 Memory 生命周期：稳定的 Memory Context 摘要格式
- Layer 3 Retrieval：Context Builder 需要基于多阶段 Retrieval 的结果
