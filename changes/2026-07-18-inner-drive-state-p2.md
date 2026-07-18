# 挂念清单二期：类型化条目 + 生命周期 + 浮现规则 + 响应路径注入 + consolidation 合流

日期：2026-07-18

设计：`doc/refactor/layer4-agent/inner-drive-state.md`（二期范围：类型化条目 + 生命周期 + 浮现规则 + consolidation 写入与对照解决 + 响应路径注入）。

## 背景

一期的挂念清单是扁平字符串列表 + FIFO：没有类型、没有生命周期、只增不减会沉底、且只属于独处时——日常对话里用户聊到挂念的事，它浮不上来。二期按设计文档把内驱状态升级为「全系统的注意力列表」。

## 改动

### `core/inner_drive_state.py`（重写）

- **`DriveEntry` 类型化条目**：`care/curiosity/reflection/plan/idea` 五类，字段含 priority、source、created_at、last_surfaced_at、surface_count、expires_at、status、resolution、embedding（base64）。
- **生命周期**：`active → resolved/expired/decayed`；过期自动检查（`expires_at` 过点）；`priority < 0.2` 自动归档——「老想到但一直不做的，多半是空谈」。
- **浮现规则 `surface(emotion)`**：`浮现分 = priority × 情绪类型权重 × 新鲜度加成`；低落时 care/reflection ×1.3，兴奋/好奇时 idea/curiosity ×1.3；`plan` 临期 6 小时强制置顶；被浮现未行动的条目 `priority *= decay_rate`（0.9）。
- **淘汰规则（非 FIFO）**：先清 resolved/expired/decayed，再清低 priority，最后才动旧活跃条目。
- **`surface_for_query()`（二期 4.2）**：用户消息向量与活跃条目比对，超阈值 Top K 浮现；只读，不衰减不计数。
- **`resolve_matching()`（对照解决）**：对话文本与活跃条目语义比对，命中的标记 resolved 并记录「对话中提及（相似度 x.xx）」。
- **存储 v2**（`{"version": 2, "entries": [...]}`），v1 扁平文件加载时自动迁移为 care 类型条目。
- `apply_updates` 的 add 元素支持字符串或 `{"content","type","priority","expires_at"}` 字典，新增 `source` 参数。

### 响应路径注入（`core/inner_drive.py`）

- `assess()` 新增 `_surface_care_for()`：用户消息命中挂念时，把「=== 你在意的事（与当前对话相关，可自然提及，不要硬塞）===」块并入 `context_summary`——经 #160 链路同流到 Agent 3，调用侧零改动，零额外 LLM 调用。
- 沉思循环 Round 1 改用 `surface(emotion)`（带类型标签 `[计划]/[挂念]…`），不再全量倾倒；`PROACTIVE_LOOP_SCHEMA` 的 `care_updates.add` 支持类型化对象。

### consolidation 合流（`memory/consolidation.py`）

- 构造函数新增 `inner_drive_state`；`consolidate()` 末尾新增 Step 7：
  - **对照解决**：`resolve_matching(turn_text)`——用户自己提起挂念的事，该条目 resolved，不再浮现；
  - **线索写入**：新增 `CARE_CLUE_PROMPT`（`prompts/templates.py`），LLM 从对话中提取「未完成的线索」（约定/计划/未解决的问题）自动写入，`source="consolidation"`——睡觉整理记忆时发现线索，醒来惦记。

### 接线与配置

- `core/session_factory.py`：eager 创建共享 `InnerDriveState`（带 embedding engine），同时注入 consolidator 和 `agent._inner_drive_state`。
- `core/message_handler.py`：优先复用 agent 上的共享实例，fallback 自建（带 embed）。
- config 新增四项：`inner_drive_surface_top_k`(8)、`inner_drive_surface_response_k`(3)、`inner_drive_decay_rate`(0.9)、`inner_drive_care_similarity_threshold`(0.7)。

### 测试（+22）

- `test_inner_drive_state.py`（+15）：类型化写入/非法类型回退/v1 迁移、plan 置顶、情绪加权、浮现衰减、过期不浮现、低分归档、非 FIFO 淘汰顺序、语义浮现命中/未命中/无引擎、响应路径不衰减、对照解决命中/未命中。
- `test_inner_drive.py`（+2）：类型化 care_updates 写入与带标签浮现、`assess()` 挂念块注入 context_summary。
- `test_consolidation.py`（+5）：线索写入 source、空线索/坏 JSON 静默、无 content 过滤、无 state 跳过。

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**635 passed + 2 skipped**（613 → 635）

## 备注

- 一期 v1 状态文件自动迁移，无需手动处理。
- 响应路径成本：一次本地向量编码 + 比对，约 100~200 token 上下文，零额外 LLM 调用。
- 未做（三期）：回馈闭环（record_outcome）、`memory_agent` 来源、dreams 长期梦想。
- `type_weights`/`_positive_int` 等对 MagicMock/坏配置做了防御性强转。
