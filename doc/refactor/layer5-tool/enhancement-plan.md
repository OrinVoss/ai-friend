# 工具系统增强方案

> 目标：把工具系统从「能用」升级到「好用」——结构化的结果、明智的重试、并行的执行、可观测的运行。
> 状态：设计文档，待实现。
> 归属：Layer 5。Prompt 精简已完成，本文档是工具系统的下一阶段。

---

## 1. 现状盘点

| 组件 | 现状 |
|------|------|
| 工具集 | 8 个外部工具（web_fetch / web_search / read_file / file_tree / glob / grep / music_play / notify）+ 2 个内部（recall / remember） |
| 基类 | `Tool` + `ToolRegistry` + `ToolSpec`（`tools/traits.py`），有权限元数据雏形 |
| 结果 | `ToolResult(success, output)`——一个布尔 + 一段文本 |
| 解析 | `core/dispatcher.py` 三段解析（结构化 JSON → XML 标签 → 裸 JSON），参数别名归一 |
| 执行 | `execute_tool_calls()` 同步、串行、无超时、无权限检查 |
| Agent | `ToolAgent` ReAct 循环，3 轮 × 3 次重试，失败时笼统地「调整方式后重新输出」 |

---

## 2. 问题清单（按严重度排序）

### P0-1 `ToolResult` 太薄，错误无法分类

`tools/traits.py:15` —— 结果只有 `success + output`。「参数写错了」「网页 404」「网络超时」「权限不足」全部混成一段文本。后果：

- LLM 无法判断该怎么补救（换参数？换工具？放弃？）
- 重试逻辑无法区分「值得重试」和「重试也是白费」

### P0-2 重试是盲目的

`core/tool_agent.py:170-215` —— 任何失败都重试，提示语是笼统的「调整方式后重新输出」。404 的页面重试 3 次还是 404；参数错误不改 schema 指导重试还是错。没有退避，没有按工具/按错误类型的策略。

### P0-3 Schema 指导不足，靠别名兜底

`tools/traits.py:139-144` —— `to_json_schema()` 里 `arguments` 是空泛的 `{"type": "object", "description": "工具参数，根据具体工具而定"}`，**模型拿不到每个工具的参数细节**，所以参数名乱写（`filepath`/`filename`/`file`/`path`），只能靠 `_normalize_args()`（`dispatcher.py:206`）的别名表兜底。这是治标，治本要把参数 schema 给全。

### P0-4 无参数校验、无超时

- 工具拿到 raw dict，缺参数到运行时才炸成异常文本
- `execute_tool_calls()`（`dispatcher.py:137`）直接 `tool.execute(args)`，没有超时——一个卡住的 web_fetch 挂起整个请求（known-issues 已记录）

### P1-1 同步串行执行

批量 `calls` 数组顺序执行（`dispatcher.py:122-155`），`run_with_requests()` 也是顺序（`tool_agent.py:238-243`）。web_search + web_fetch 这种 I/O 密集组合，延迟是简单相加。

### P1-2 输出截断混乱

四处硬编码、互不一致：`dispatcher.py:16`（2000）、`tool_agent.py:116/199`（3000）、`inner_drive.py:601`（1000）、`dispatcher.py:52`（10240）。网页内容没有正文抽取/智能摘要，长页面直接砍断，前半截可能是导航栏。

### P2-1 无可观测性

工具调用只有日志。没有 per-tool 成功率、延迟分布、重试率——哪个工具最拖后腿、哪个老失败，全靠翻日志猜。monitor 已记录 LLM 调用，工具指标缺位。

### P2-2 权限形同虚设

`check_permission()`（`traits.py:98`）定义了，但 `execute_tool_calls()` 从不调用它。内部/外部工具靠注册表隔离在撑，权限层没有真正生效。

---

## 3. 增强方案

### P0：质量地基

**1. `ToolResult` v2 —— 结构化错误**

```python
@dataclass
class ToolResult:
    success: bool
    output: str
    error_type: str = ""        # param_error / not_found / network_error /
                                # permission_denied / rate_limited / internal
    retryable: bool = False     # 这个错误值不值得重试
    elapsed_ms: float = 0.0
```

`ToolResult.ok/fail` 保留兼容，新增 `ToolResult.fail(error, error_type=..., retryable=...)`。

**2. 错误感知的重试**

- `retryable=False`（param_error / not_found / permission_denied）→ 不重试，直接回报 Agent 1
- `retryable=True`（network_error / rate_limited）→ 重试，带简单退避（1s / 2s / 4s）
- 重试提示语带上错误类型：「上次失败原因是 404（页面不存在），换一个来源或放弃」——比「调整方式」具体得多

**3. 执行前参数校验**

`execute_tool_calls()` 里按 `parameters_schema()` 校验必填参数和类型，缺参直接返回 `param_error`，**不进入执行**——错误从运行时异常变成结构化反馈，LLM 下一轮就能修。

**4. 统一超时**

`Tool` 基类加 `timeout_seconds: float = 30.0` 元数据（web 类工具可覆盖），dispatcher 统一 enforce，超时返回 `network_error(retryable=True)`。

### P1：性能

**5. 并行执行**

- `execute_tool_calls()` 对 `calls` 数组用 asyncio 并行（工具间无依赖）
- `run_with_requests()` 并行化，合并结果保持顺序
- 文件类工具快、网络类工具慢，并行后延迟从「求和」变「取最大值」

**6. 统一且智能的输出处理**

- 截断集中到一处（`ToolResult` 生成侧），删掉四处硬编码
- web_fetch/web_search 输出先做正文抽取，再按与 query 的相关性优先保留段落，最后才截断——砍掉的是边角料，不是正文

### P2：能力与观测

**7. Schema 给全参数细节**

`to_json_schema()` 升级：每个工具的 `parameters_schema()` 注入结构化输出格式（仿 function calling 的 per-tool parameters）。模型看得到参数名和类型，别名表降级为兼容兜底而非主力。

**8. 工具指标**

per-tool 统计：调用次数、成功率、平均延迟、重试率，挂到现有 monitor（`core/monitor.py`），Web 面板可查。

### P3：生态（配合「多信息源」愿景，按需）

**9. 新工具接入指南**

模板 + 注册约定（命名、schema 写法、error_type 使用、timeout 设置），让加工具是填空题。

**10. 候选新工具**

订阅/定时类（RSS、定期检查某个页面变化）——配合独处循环的 explore，「它关注的话题有更新」可以成为新的内驱来源。写操作类工具（写文件、改配置）暂不做，等权限层真正生效后再评估。

**11. 权限强制执行**

`execute_tool_calls()` 调用 `check_permission()`，拒绝返回 `permission_denied`。

---

## 4. 与现有设计的关系

- **Layer 5 Prompt 精简（已完成）**：本方案不动 Prompt 结构，只改执行层和结果结构
- **Agent 1 review**：`ToolResult` v2 的错误类型让 review 判断「够不够、要不要换方式」更准
- **独处循环 explore**：智能截断 + 并行执行直接降低探索成本，内化（`solo-activity.md`）拿到的是正文不是导航栏
- **睡眠循环**：工具指标给「哪个工具老失败」提供数据，核查阶段可联动降权

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `tools/traits.py` | `ToolResult` v2、`timeout_seconds`、schema 增强 | P0/P2 |
| `core/dispatcher.py` | 参数校验、超时、权限检查、并行执行、统一截断 | P0/P1 |
| `core/tool_agent.py` | 错误感知重试 + 退避、run_with_requests 并行 | P0/P1 |
| 各工具实现 | 标注 error_type / retryable / timeout | P0 |
| `core/monitor.py` | 工具指标收集 | P2 |
| `tests/test_dispatcher.py` / `test_tool_agent.py` | 新增覆盖 | 各期 |

---

## 6. 测试与验收

测试：

1. 缺参调用 → `param_error`，工具未被执行
2. `retryable=False` 错误 → 不重试直接返回
3. 超时工具 → 按时返回 `network_error`，不挂起请求
4. 并行执行：两个 500ms 工具总耗时 < 800ms
5. schema 含每个工具的参数细节
6. 权限拒绝 → `permission_denied`，未执行

验收：

- 工具失败时 Agent 1 的 review 日志能看到具体错误类型
- 批量工具调用的端到端延迟可观察地下降
- monitor 面板能查到 per-tool 成功率
- 全量测试不降级

---

## 7. 相关文档

- `../layer4-agent/solo-activity.md` — explore 是 web 工具的重度用户
- `../layer1-memory/sleep-cycle.md` — 工具指标可用于睡眠核查
- `doc/known-issues.md` — 超时缺失等原始问题记录
