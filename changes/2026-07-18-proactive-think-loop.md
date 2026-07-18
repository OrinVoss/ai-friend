# Agent 1 主动沉思循环 + 挂念清单（一期）

日期：2026-07-18

设计：`doc/refactor/layer4-agent/proactive-think-loop.md` + `inner-drive-state.md`（一期范围）。

## 背景

主动路径的 `assess_proactive()` 原来是单次 LLM 调用 + 关键词正则解析：想起具体事情无法查证、话题重复肤浅、每次触发都是一片空白地开始想——没有持续的内心世界，就没有主观能动性。响应路径的 `assess()` 已有 recall 循环，proactive 是 InnerDrive 唯一没有回忆能力的入口。

## 改动

### `core/inner_drive.py`

- 新增 `PROACTIVE_LOOP_SCHEMA`（thought / recall_query / action / topic_hint / reasoning / care_updates），替代正则解析；正则 `_parse_proactive_intent()` 保留为兜底。
- `assess_proactive()` 重写为**有界沉思循环**（默认 3 轮封顶）：`recall_query` 非空 → 执行只读 recall 并把结果喂回 messages 继续思考；为空 → 本轮即最终决定。最后一轮仍要 recall 的，采用该轮有效 action，无效则 `silent`。
- 循环唯一允许的写动作是 `care_updates`（更新自己的挂念清单）；不允许 remember/外部工具/改用户记忆。
- 旧单次路径保留为 `_assess_proactive_single()`，`proactive_think_loop=false` 时完整走老路。
- `ProactiveIntent` 接口不变，`MessageHandler` 零改动。
- 新增 `_parse_proactive_json()` / `_to_proactive_intent()` / `_apply_care_updates()` / `_positive_int()`。

### `core/inner_drive_state.py`（新建）

最小挂念清单（inner-drive-state.md 一期：扁平列表、容量上限、FIFO 淘汰）：

- 存储 `data/.inner_drive_state.{session_id}`（沿用 `.sleep_state` per-session 文件模式，已加 .gitignore）。
- `entries()` 读取、`apply_updates(add, remove)` 更新；损坏文件降级为空清单，读写失败不影响主流程。
- 完整设计（类型化条目、优先级、生命周期、浮现规则、回馈闭环）留待二期三期。

### `prompts/system.py`

`build_inner_drive_proactive_prompt()` 新增 `care_list` / `think_loop` 参数：loop 模式下输出格式块替换为沉思循环协议（思考起点引导：用户近况/挂念/好奇心/自我反思/创造——引导而非场景白名单），挂念清单注入 Round 1 上下文。非 loop 模式 prompt 不变。

### 配置与接线

- `config.py` / `config.example.json`：`proactive_think_loop`（true）、`proactive_think_max_rounds`（3）、`inner_drive_care_list_size`（20）。
- `core/message_handler.py`：开关开启时创建 per-session `InnerDriveState` 并注入 `InnerDriveAgent`。
- `doc/config-reference.md` 同步三个配置项。

### 测试（+14）

- `tests/test_inner_drive_state.py`（7）：增删、去重、FIFO 淘汰、跨实例持久化、损坏文件兜底、空更新。
- `tests/test_inner_drive.py::TestProactiveThinkLoop`（7）：无 recall 单轮结束、recall 后二轮决策（结果确实进入上下文）、3 轮强制终止、JSON 失败正则兜底、非法 action 降级 silent、挂念跨触发浮现且 remove 生效、开关关闭走单次路径。
- 存量 `TestAssessProactive`（中文自由文本 mock）经正则兜底保持全绿，无需改动。

## 验证

- `pytest tests/test_inner_drive.py tests/test_inner_drive_state.py -q`：44 passed
- 全量 `pytest tests --ignore=tests/real_api -q`：**613 passed + 2 skipped**（599 → 613）

## 备注

- 测试 mock 的 `config` 是裸 MagicMock，新数字配置参与比较会 TypeError——`InnerDriveAgent`/`InnerDriveState` 构造已做容错强转（坏类型回退默认值），两个 handler 测试文件按惯例显式置 `proactive_think_loop = False`。
- 二期：循环内 recall 换 Memory Agent（带置信度/证据链）；挂念清单类型化 + 生命周期 + 响应路径注入（surface_for_query）。
