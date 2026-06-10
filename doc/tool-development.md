# 工具开发指南

> 如何创建新工具并集成到三层 Agent 架构中。

---

## 工具系统架构

```
Tool (base class)          tools/traits.py
  ├── name() → str
  ├── description() → str
  ├── parameters_schema() → dict    # JSON Schema
  ├── execute(args) → ToolResult
  └── spec() → ToolSpec

ToolRegistry                tools/traits.py
  ├── register(tool)
  ├── get(name) → Tool
  ├── list_specs() → [ToolSpec]
  ├── format_for_prompt()  → str    # 注入 prompt
  └── to_json_schema() → dict       # JSON mode 工具列表

ToolResult                  tools/traits.py
  ├── success: bool
  ├── output: str
  └── static ok() / fail()
```

### 三层分工

| Agent | 可用工具 | 职责 |
|-------|----------|------|
| Agent 1 InnerDrive | `recall`, `remember` | 自主推理、检索记忆、决策是否需要外部工具 |
| Agent 2 ToolAgent | 全部 7 个外部工具 | 纯工具执行，temperature=0.3，无人格/情绪/记忆 |
| Agent 3 Roleplay | `recall`, `remember` | 人格驱动回复，仅内部内存操作 |

**核心原则**：Agent 3 的 system prompt 中不出现外部工具指令，从根源上消除模型虚构外部工具调用。

---

## 快速开始：创建一个新工具

### 第 1 步：创建工具类

在 `tools/` 下新建文件，继承 `Tool` 基类：

```python
# tools/weather_tool.py
from tools.traits import Tool, ToolResult
from typing import Any


class WeatherTool(Tool):
    def name(self) -> str:
        return "weather"

    def description(self) -> str:
        return "查询指定城市的当前天气"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，如 北京、上海",
                }
            },
            "required": ["city"],
        }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        city = args.get("city", "")
        if not city:
            return ToolResult.fail("请指定城市名称")
        try:
            # 调用天气 API...
            return ToolResult.ok(f"{city} 当前温度 22°C，晴")
        except Exception as e:
            return ToolResult.fail(f"查询失败：{e}")
```

### 第 2 步：注册到 ToolRegistry

需要同时在**两个位置**注册，分别给 Agent 2 和 Agent 1/3：

```python
# 位置 1 — web/session.py WebAgent.__init__
registry.register(WeatherTool())  # 和其他工具并列注册

# 位置 2 — core/agent.py Agent.__init__（如果是 Agent 2 可以用的外部工具）
```

注意：Agent 1 和 Agent 3 只能使用 `recall` / `remember` 两个内部工具。新工具如果是**外部工具**（调用 API、读文件等），只需要在 WebAgent 注册到完整的 `_tool_registry`。

### 第 3 步（可选）：加参数别名

`dispatcher.py` 的 `_normalize_args()` 支持参数别名映射。如果你的工具有常见别名，加到那里：

```python
def _normalize_args(name: str, args: dict) -> dict:
    ALIASES = {
        "query": ["search", "keyword", "question"],
        "content": ["text", "msg"],
        "name": ["person", "who", "user", "target"],
    }
    # 自动归一化...
```

---

## ToolResult 规范

```python
# 成功
return ToolResult.ok("查询结果：...")

# 失败（会被 ToolAttemptTracker 重试）
return ToolResult.fail("API 返回错误：...")

# 异常（会被捕获并转为 fail）
raise ValueError("unexpected")  # 自动包装为 ToolResult.fail
```

### 错误处理

- 返回 `ToolResult.fail` → ToolAttemptTracker 触发重试（最多 3 次/轮 × 3 轮）
- 抛出异常 → dispatcher 捕获，转为 `ToolResult.fail`
- 全部重试失败 → 回报 Agent 1 重新决策

---

## 参数规范

### JSON Schema 最佳实践

```python
def parameters_schema(self) -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
            "max_results": {
                "type": "integer",
                "description": "返回结果数",
                "default": 5,
            },
        },
        "required": ["query"],
    }
```

### 命名约定

- 参数名用 **snake_case**
- description 用中文或英文，保持一致
- 必需参数放 `required` 数组
- 可选参数给 `default`

---

## 工具箱现有工具参考

| 文件 | 类 | 说明 |
|------|-----|------|
| `tools/memory_tools.py` | `RecallTool` | 检索记忆（内部） |
| `tools/memory_tools.py` | `RememberTool` | 存储事实（内部，支持 correct=true） |
| `tools/web_tools.py` | `WebSearchTool` | 网络搜索（AnySearch） |
| `tools/web_tools.py` | `WebFetchTool` | 网页内容提取 |
| `tools/file_tools.py` | `ReadFileTool` | 读取本地文件 |
| `tools/search_tools.py` | `GlobTool` | 文件名模式匹配 |
| `tools/search_tools.py` | `GrepTool` | 正则内容搜索 |
| `tools/notify_tool.py` | `NotifyTool` | Windows toast 通知 |
| `tools/music_tool.py` | `MusicPlayTool` | 播放音乐 |

---

## 工具调用链路

```
用户输入
    │
    ▼
Agent 1 InnerDrive
    │ 推理：是否需要外部工具？
    │ 内部可用：recall / remember
    │
    ├── 不需要 → 跳过 Agent 2，直接进入 Agent 3（闲聊优化）
    │
    └── 需要 → 输出自然语言请求
        │
        ▼
    Agent 2 ToolAgent (temp=0.3)
        │ 接收自然语言请求
        │ ToolAttemptTracker: 3 次重试/轮 × 3 轮
        │ 精简 prompt（无情绪/人格/记忆）
        │
        ├── 成功 → 结果注入 Agent 3 上下文
        │
        └── 全部失败 → 回报 Agent 1 重新决策
            │
            ▼
        Agent 1 重新评估 → 调整策略或放弃工具
```

### 新工具注意事项

1. **Agent 3 不会看到你的工具** — 外部工具只对 Agent 2 可见
2. **参数尽量少** — `response_format="json_object"` 模式下参数越多越容易出错
3. **不要依赖 LLM 侧状态** — ToolAgent 每次调用 prompt 独立，无对话历史
4. **返回值控制在 2000 字符内** — 超出会截断（`#192`）
