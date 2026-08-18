# 工具开发指南

> 如何创建新工具并集成到三层 Agent 架构中。

---

## 工具系统架构

```
EXTERNAL_TOOL_NAMES         tools/traits.py
  └── 8 个外部工具的规范名单，Agent 2 按它从全量注册表过滤（#258）

Tool (base class)          tools/traits.py
  ├── name() → str
  ├── description() → str
  ├── parameters_schema() → dict    # JSON Schema
  ├── execute(args) → ToolResult    # 同步方法
  ├── spec() → ToolSpec
  ├── required_permissions: [str]   # 权限元数据，空列表 = 不限制（#183）
  ├── timeout_seconds: float = 30   # per-tool 超时（Layer5-T1）
  └── is_internal: bool = False     # True 的内部工具不暴露给 Agent 2

ToolRegistry                tools/traits.py
  ├── register(tool)
  ├── get(name) → Tool
  ├── list_specs() → [ToolSpec]
  ├── format_for_prompt()  → str    # 注入 prompt
  ├── to_json_schema() → dict       # JSON mode 工具列表
  └── check_permission(name, user_role)  # dispatcher._execute_single 强制执行（Layer5-D3）

ToolResult                  tools/traits.py
  ├── success: bool
  ├── output: str
  ├── static ok() / fail()
  └── to_dict() → dict
```

### 三层分工

| Agent | 可用工具 | 职责 |
|-------|----------|------|
| Agent 1 InnerDrive | `recall`, `remember` | 自主推理、检索记忆、决策是否需要外部工具 |
| Agent 2 ToolAgent | 全部 8 个外部工具 | 纯工具执行，无人格/情绪/记忆（未单独设温，沿用 config.temperature 默认 0.8） |
| Agent 3 Roleplay | `recall`, `remember`, `history_search` | 人格驱动回复，仅内部内存操作 |

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

    def execute(self, args: dict[str, Any]) -> ToolResult:
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

需要在**统一装配点** `core/session_factory.py` 的 `assemble_session()` 把新工具挂到 `ToolRegistry`（CLI 与 Web 共用此入口）：

```python
# core/session_factory.py assemble_session()
tool_registry = ToolRegistry()
tool_registry.register(RecallTool(retriever, ltm))
tool_registry.register(RememberTool(ltm))
...
tool_registry.register(WeatherTool())  # 和其他工具并列注册
...
agent = Agent(...)
agent._tool_registry = tool_registry  # 全量工具箱，由 AgentWiring 按内/外拆分
```

注意：入口注册的是**全量**工具箱，`core/agent_wiring.py` 的 `AgentWiring` 会自动拆分——Agent 1 / Agent 3 使用独立注册的内部工具（Agent 1：`recall` / `remember`；Agent 3 另加 `history_search`）；Agent 2 按 `tools/traits.py` 的 `EXTERNAL_TOOL_NAMES` 名单从全量注册表过滤出外部工具（并跳过 `is_internal=True` 的工具）。因此新工具如果是**外部工具**（调用 API、读文件等），还必须把 `name()` 加进 `EXTERNAL_TOOL_NAMES`，否则 Agent 2 看不到它。`FileTreeTool` 由 `include_file_tree` 参数控制：CLI（`main.py`）传 `True`，Web 端用默认 `False` 不注册，其余工具两端一致。

### 第 3 步（可选）：加参数别名

参数别名由各工具自己声明（KI-1，2026-07-21 起 dispatcher 的全局 `_normalize_args` 已删除）。在工具类上设置 `ALIASES` 类属性即可，dispatcher 会在执行前调用 `tool.normalize_args()` 归一：

```python
class WeatherTool(Tool):
    # {规范参数名: (别名1, 别名2, ...)}；规范名已存在时别名不生效
    ALIASES = {"city": ("location", "place", "town")}
```

不要依赖任何全局映射——每个工具只声明自己认得的名字，避免跨工具冲突（历史上全局别名曾把 notify 的 `title` 当成 music 的 `song` 吃掉）。

### per-tool 超时

每个工具可声明 `timeout_seconds` 类属性（默认 30s），dispatcher 在 `_execute_single` 中强制限制执行时间，超时返回 `error_type="network_error"`、`retryable=True`：

```python
class WeatherTool(Tool):
    timeout_seconds = 15  # 该工具最多执行 15 秒
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
- ToolResult v2 新增错误分类：`error_type`（"param_error"/"not_found"/"network_error"/"permission_denied"/"rate_limited"/"internal"）和 `retryable` 标记。`retryable=False` 的错误（如 param_error，参数问题重试无意义）提前放弃；`retryable=True` 的错误（如超时映射的 network_error）指数退避重试（1s/2s/4s）。
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
| `tools/file_tools.py` | `FileTreeTool` | 目录结构树（仅 CLI 注册，Web 端未注册） |
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
    Agent 2 ToolAgent
        │ 接收自然语言请求
        │ 三层解析：JSON 数组 → XML <tool_call> 正则 → 裸 JSON 兜底
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

### 工具调用记录归因（MH-002，2026-07-26）

Agent 2 每次执行生成 `ToolCallRecord`（`core/tool_agent.py`）：`name / arguments / success / output / elapsed_ms / error_type / retryable / request`。`request` 字段记录该调用所属的自然语言请求（截断 80 字符），由 ToolAgent 在记录时填入，新工具无需感知。`run_with_requests` 多请求并发合并后，`format_for_phase2()` 在存在两个及以上不同 `request` 时按请求分组渲染（每组小标题 `【请求：…】`，铁律段仅末尾一次，分组内经 `format_tool_results(..., append_iron_rule=False)` 关闭）；单请求时格式不变。

### 新工具注意事项

1. **Agent 3 不会看到你的工具** — 外部工具只对 Agent 2 可见
2. **参数尽量少** — `response_format="json_object"` 模式下参数越多越容易出错
3. **不要依赖 LLM 侧状态** — ToolAgent 每次调用 prompt 独立，无对话历史
4. **返回值控制在 2000 字符内** — 超出会截断（`#192`；默认值，可用配置键 `dispatcher_output_cap` 覆盖）
