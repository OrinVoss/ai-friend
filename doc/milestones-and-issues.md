# 里程碑与 Issue

> 最后更新：2026-06-01 | 总计 91 issues（60 已完成，31 开放）| 三层 Agent 已上线 | 语义搜索已上线 | #6 虚假记忆修正 | #125 主动行为集成 | #127-#142 数据质量根本修复

---

## 总览

| 版本 | 聚焦 | Issues | 已完成 | 开放 | 进度 |
|------|------|--------|--------|------|------|
| v0.1 | 基础架构稳定 | 30 | 30 | 0 | 100% |
| v0.2 | 记忆系统升级 | 9 | 4 | 5 | 44% |
| v0.3 | 情感与人格 | 12 | 9 | 3 | 75% |
| v0.4 | Web 工程化 | 9 | 2 | 7 | 22% |
| v0.5 | 前瞻与质量 | 26 | 17 | 9 | 65% |
| v1.0 | 正式版发布 | 9 | 1 | 8 | 11% |
| v2.0 | 远景合并 | 1 | 0 | 1 | 0% |

---

## v0.1 — 基础架构稳定（30/30 完成 ✅）

**目标**：消除代码审查报告中的关键 bug 和安全问题，让项目达到可维护的基线。

### 已完成

#### 安全加固
| # | 标题 | 修改内容 |
|---|------|---------|
| #13 | API Key 环境变量读取 | `config.py` 支持 `DEEPSEEK_API_KEY` 等环境变量覆盖 |
| #16 | ReadFileTool 路径穿越 | 限制读取范围在项目目录内 |

#### 线程安全与错误处理
| # | 标题 | 修改内容 |
|---|------|---------|
| #17 | ConversationBuffer 加锁 | 所有读写操作包裹 `threading.Lock` |
| #18 | bare except 清理 | 替换为具体异常类型，加日志 |

#### 配置与 Schema
| # | 标题 | 修改内容 |
|---|------|---------|
| #34 | config.json 默认值不一致 | 补全 `api_timeout`、`max_facts` 等缺失字段 |
| #35 | Schema 迁移重复 ALTER | 改为 `PRAGMA table_info` 检查列存在性 |
| #36 | Reflections 软删除 | 新增 `is_active` 列，DELETE → UPDATE |
| #38 | timeout 配置化 | 新增 `api_timeout` 配置项，不再硬编码 180s |
| #39 | 缺 requirements.txt | 锁定 5 个依赖及版本 |

#### 内存与数据流
| # | 标题 | 修改内容 |
|---|------|---------|
| #33 | 上下文压缩不触发 | process_message 路径超阈值时注入压缩摘要 |
| #37 | format_for_prompt 截断方向 | 从保留最早改为保留最新对话 |

#### 性能
| # | 标题 | 修改内容 |
|---|------|---------|
| #15 | 情感分析重复调用 | CLI/Web 路径统一为单次分析 |

#### 存储与工具调用升级
| # | 标题 | 修改内容 |
|---|------|---------|
| #1 | Async SQLite (aiosqlite) | `threading.Lock + sqlite3` → `asyncio.Lock + aiosqlite`；storage/ 全异步（async context manager cursor）；memory/long_term.py 异步+同步兼容包装；main.py 用 asyncio.run()；web/server.py lifespan 中 await db.open()；requirements.txt 加 aiosqlite |
| #2 | 结构化 JSON Tool Calling | `core/provider.py` 加 `response_format` 参数支持 JSON mode；`tools/traits.py` 加 `to_json_schema()` 方法；`core/dispatcher.py` 改为三层解析（JSON calls 数组 + XML 正则 + 裸 JSON）；`prompts/system.py` JSON 格式工具指令；`core/tool_agent.py` 传 `response_format` 给 provider |

#### 重构（被后续 issue 覆盖）
| # | 标题 | 覆盖者 |
|---|------|--------|
| #3 | 环境变量覆盖 | #13 |
| #11 | Session 泄漏 | #59 |
| #12 | proactive_loop 竞争 | #59 |
| #14 | 工厂函数 | #58 |
| #31 | 统一 CLI/API 路径 | #58 |

### 开放（0 个）✅ v0.1 全部完成

#### Schema 变更
| # | 标题 | 风险 | 说明 |
|---|------|------|------|
| #10 | conversation_turns 加 session_id | 中 | Schema 变更，需迁移现有数据 |

#### 优化
| # | 标题 | 说明 |
|---|------|------|
| #32 | 替换 cl100k_base 为 DeepSeek tokenizer | 当前仍用 cl100k_base 近似（tiktoken），未替换为 DeepSeek 官方 tokenizer |

### 已验证修复（v0.1 Bug 清零）

以下 v0.1 bug 经过 10 Agent 并行代码扫描确认已解决：

| # | 标题 | 严重度 | 修复确认 |
|---|------|--------|---------|
| #68 | process_message 绕过状态机，current_input 未设置 | 🔴→✅ | `message_handler.py` 已设置 `current_input`，Web 路径正常工作 |
| #69 | 破防 Web 路径情感分析滞后一轮 | 🔴→✅ | 已验证非 bug：`get_all_reversed()` 正确找到当前用户轮次 |
| #75 | CLI 路径 sentiment + consecutive_negative 重复 | 🔴→✅ | `cli_controller.py` 已移除 `_on_reflect` 中的重复情感分析 |
| #70 | 工具调用后续轮 token 限制过低 (128) | 🟡→✅ | 后续轮 `max(384, max_tok*2//3)`，最低 384 tokens |
| #71 | _compress_context 缺少递归保护 | 🟡→✅ | `_compressing` 标志防止重入 |
| #73 | personality.save 重复保存 | 🟡→✅ | CLI 每 10 轮保存一次，Web 每消息一次，无重复 |
| #74 | _tool_registry 初始 None | 🟡→✅ | 默认 `ToolRegistry()` 空实例非 None |
| #72 | reversed(get_all) 频繁创建迭代器 | ✅ | 新增 `get_all_reversed()` 方法 |

---

## v0.2 — 记忆系统升级（3/9 完成）

**目标**：从"关键词搜索引擎"升级为"语义理解 + 分层记忆 + 自我修正"。

### 核心架构升级
| # | 标题 | 说明 |
|---|------|------|
| #4 | 向量语义检索 | ✅ Qwen3.5-0.8B-Q6_K.gguf 本地嵌入，512 维，SQLite BLOB 存储（已实现，模型与原始方案不同） |
| #5 | 分层反思 | L1 事实 → L2 模式归纳 → L3 深度洞察，防止浅层重复 |
| #6 | 虚假记忆修正 | ✅ 矛盾检测（直接+语义）+ 置信度衰减 + 用户纠正（correct_fact），FactChecker 集成到 consolidation |

### Bug 修复
| # | 标题 | 说明 |
|---|------|------|
| #19 | 情感值饱和 | ✅ 按情绪半衰期系统已实现（EMOTION_HALF_LIVES：surprise 3t ~ trust 25t），核心问题已解决 |
| #20 | humor/sass 无实际效果 | 特质定义后在代码中未使用（`core/personality.py` 仅检查 empathy/playfulness/warmth/thoughtfulness） |
| #21 | _score_facts 原地覆写 | 评分结果未写回 DB（仍在 `retrieval.py` 中原地修改 `composite_score`，功能性无害但不规范） |
| #22 | consolidation pending 重复 | pending 队列可能包含同一 turn 多次（`_pending_buffer` 纯 list，无去重） |
| #40 | 无 session_id 过滤 | 多用户时记忆互相串扰（所有表均无 `session_id` 列） |
| #41 | 情感分析三处调用 | ✅ 已减少到 2 处（`agent.py:187` 每轮 + `consolidation.py:234` 合并路径），仍有一处冗余合并调用待消除 |

---

## v0.3 — 情感与人格（8/12 完成）

**目标**：让 AI 拥有真正的情感深度——会记仇、情绪有惯性、行为被深层人格驱动。

### 已完成

| # | 标题 | 修改内容 |
|---|------|---------|
| #55 | 作息+梦境 | 午睡/夜睡，LLM 生成梦境，醒来分享 |
| #59 | 主动回复刷屏 | reset last_activity_time + cooldown + add_to_history=False |
| #76 | 怨恨机制 | resentment 累积/衰减，压制 joy 上限，减慢 trust 恢复 |
| #77 | 分速衰减 | 8 个情绪各独立半衰期（surprise 3t ~ trust 25t） |
| #78 | 情绪事件记忆 | 强情绪自动记录，注入后续 prompt |
| #98 | 短期记忆恢复 | 重启/刷新从 DB 恢复最近 30 轮对话 |
| #99 | 自主上网探索 | AI 空闲时搜索+浏览，发现有趣的主动分享 |
| #100 | 自主工具+作息 | 探索/聊天频率限制 + 午睡夜睡梦境 |

### 开放

| # | 标题 | 说明 |
|---|------|------|
| #7 | 对话节奏多维影响 | 反驳链、回复速度趋势、态度一致性参与情绪更新 |
| #8 | 人格特质全链路 | OCEAN × 记忆编码/检索/回应三层 |
| #23 | BaseProvider ABC | 抽象 Provider 接口，方便切换模型 |
| #42 | 情感值归一化 | 达 ±1.0 极限后的重置与反弹机制 |

---

## v0.4 — Web 工程化（2/9 完成）

**目标**：Web 端达到生产可用水平——安全、高效、可维护。

| # | 标题 | 状态 | 说明 |
|---|------|------|------|
| #9 | 主动驱动升级 | ✅ | 基于未完成话题/长期目标（被更详细的 #64 覆盖） |
| #116 | per-session proactive 任务管理 | ✅ | SessionManager 追踪 per-session proactive 任务，新标签页连接取消旧任务，消除多标签页并发竞争 |
| #57 | Web 持久化排查 | 🔴 | DB 路径/写放大/session 析构/shutdown 清理/WAL checkpoint |
| #58 | 统一启动入口 | 🔴 | start.py + create_agent 工厂，消除重复初始化 |
| #24 | Web 安全 | 🔴 | CORS 配置、速率限制、CSP 头 |
| #43 | Pydantic 验证 | 🔴 | REST API 输入模型校验 |
| #44 | 写放大优化 | 🔴 | personality 每消息写 → 每 10 轮写（和 CLI 一致） |
| #45 | Web 封装 | 🔴 | 停止直接访问 agent 私有方法 |
| #46 | 线程池风险 | 🔴 | 同步阻塞调用导致默认线程池耗尽 |

---

## v0.5 — 前瞻与质量（5/21 完成）

**目标**：面向未来的架构演进 + 工程质量底座。

### 情感与记忆前瞻

| # | 标题 | 说明 |
|---|------|------|
| #60 | 情绪多维动态 | 交互模式特征（反驳链/速度/一致性）参与情绪计算 |
| #63 | OCEAN 人格渗透 | 五大人格特质影响记忆编码权重、检索偏向、回应生成 |
| #64 | 内在驱动力 | 未完成对话 + 长期目标 + 思念状态驱动主动对话 |
| #65 | 向量语义搜索 | ✅ 本地 Embedding 替换纯关键词检索（Qwen3.5-0.8B-Q6_K.gguf, 512维, llama.cpp, 混合评分 0.6/0.4） |
| #125 | InnerDrive + 主动行为集成 | ✅ 两级门控：ProactivityManager 轻量预筛选 → InnerDrive LLM 决策（chat/explore/silent），替换随机话题和 40/60 分流 |
| #127 | user_facts 主体识别缺失 | ✅ LLM prompt 只提取 user_fact + 检索 SQL 过滤 fact_type='user_fact' |
| #128 | 置信度系统失效 | ✅ #6 FactChecker: decay + <0.2 过滤 + 评分权重 |
| #129 | user_facts 大量重复 | ✅ #6 FactChecker: 同 (category,key) 矛盾检测 → 衰减 |
| #130 | conversation_turns 幻觉存档 | ✅ _build_messages 跳过舞台指示（括号开头对话） |
| #132 | relationship_metrics 无时间序列 | ✅ relationship_snapshots 表 + get_relationship_history() |
| #134 | _run_sync 线程问题 | ✅ 统一 core/async_utils.run_async 替换 3 处重复 |
| #135 | MemoryRetriever 架构缺陷 | ✅ prune 降级 composite_score*0.1 替代 deactivate |
| #136 | MemoryConsolidator 合并原子性 | ✅ 分步错误隔离，部分失败不清空 pending |
| #137 | 数据模型字段不一致 | ✅ 模型补全 + 同步包装统一 |
| #138 | 向量搜索未完全连接 | ✅ UserFact 模型补全 embedding/embedding_version + Repository 映射 |
| #139 | health_check() 硬编码 | ✅ 回退到 /v1/embeddings 端点 |
| #140 | deque 初始化问题 | ✅ __post_init__ 保留已有数据 |
| #141 | FACT 格式解析严格 | ✅ re.match(r'FACT\s*\|') 容错空白 |
| #142 | schema/cursor 问题 | ✅ schema_version 表 + commit() + relationship_snapshots 表 |
| #66 | 分层反思 | L1 事实 → L2 模式 → L3 深度洞察 |
| #67 | 虚假记忆修正 | 矛盾检测 + 置信度衰减 + 纠正高权重 |

### 工程质量

| # | 标题 | 说明 |
|---|------|------|
| #25 | 单元测试 | pytest + mock，覆盖 agent/provider/memory |
| #28 | Prompt 可配置 | 对话示例外置为 JSON/YAML，减少 token 浪费 |
| #50 | 文档补全 | architecture.md 更新 + Web 端专门文档 |

### 前端打磨

| # | 标题 | 说明 |
|---|------|------|
| #26 | 角色名/心跳/异常 | 硬编码"星"→ 读取 personality.name，心跳重连 |
| #47 | 气泡合并 | segment 独立气泡改回追加到同一气泡 |
| #48 | CJK 换行 | 中文终端换行宽度计算 |
| #49 | 打字速度 | CLI typing_speed 配置不生效 |
| #52 | ARIA/键盘 | 无障碍访问 |
| #53 | CSP 头 | 前端安全头 |
| #54 | CSS 变量 | 颜色集中管理 |

### 稳定性

| # | 标题 | 说明 |
|---|------|------|
| #27 | Shutdown 清理 | 关闭 DB、取消 task、保存 session |
| #29 | React 状态清理 | 异常退出不残留 _react_messages |
| #51 | WS 异常处理 | ✅ WebSocket 异常显式处理（WebSocketDisconnect info 日志 + Exception error 日志回显客户端） |

---

## 路线图

```
现在 ──▶ v0.1 收尾（2 issue：#10 schema + #32 tokenizer）
            │
            ▼
         v0.3 情感深化（4 issue）
            │  对话节奏、人格全链路、BaseProvider、归一化
            ▼
         v0.4 Web 工程化（8 issue）
            │  持久化、统一入口、安全、性能、WS ✅
            ▼
         v0.2 记忆升级（6 issue）
            │  分层反思、虚假记忆修正、humor/sass、去重、隔离
            ▼
         v0.5 前瞻 + 质量（17 issue）
                情绪多维、OCEAN、内在驱动、前端打磨、文档
            ▼
         v1.0 正式版（8 issue）
                情感完整 + Web 可用 + 记忆可靠 + 测试文档✅
```

---

## v1.0 — 正式版发布（1/8 完成）

**目标**：情感完整、Web 生产可用、记忆系统语义化、关键 bug 清零、有测试、有文档。

这是所有版本工作的**收敛点**——v1.0 本身不引入大的新架构，而是把 v0.1~v0.5 的关键遗留问题一次性收尾。

### 发布 checklist

| # | 标题 | 关联旧 issue | 说明 |
|---|------|-------------|------|
| #79 | 情感系统四层全部完成 | #7 #42 #69 #75 #20 | 多维输入、归一化、重复调用修复、特质生效 |
| #80 | 记忆系统语义化 | #4 #6 #21 #22 #40 | 向量检索、虚假记忆修正、去重、隔离 |
| #81 | Web 端生产可用 | #58 #57 #44 #24 #43 #46 | 统一入口、持久化完整、安全、性能 |
| #82 | 关键 Bug 清零 | #68 #70 #73 #74 #48 #49 #51 | 状态机、token、保存、WS 异常等 — ✅ 除 #49 外全部已验证解决 |
| #83 | 测试覆盖 ✅ | #25 | pytest 171 用例（11 文件，EmotionalState/分段/Provider/Agent 等） |
| #84 | 文档完整 | #50 | README、API 文档、配置参考、人格指南 |
| #85 | 前端体验打磨 | #26 #54 | 动态角色名、CSS 变量、动画、移动端 |
| #86 | Shutdown 与稳定性 | #27 #29 | 优雅关闭、状态清理、自动休眠 |

### v1.0 完成标准

- [x] 三层 Agent 架构上线（Agent 1 InnerDrive + Agent 2 ToolAgent + Agent 3 Roleplay）
- [~] 所有 v0.1~v0.5 关键 bug 已关闭（v0.1 除 #32 外全部清零；v0.5 #49 typing_speed 仍未修复）
- [ ] 情感四层架构完整运作
- [ ] Web 端可长期运行不泄漏/不崩溃
- [x] 10+ 单元测试通过（171 用例全部通过）
- [ ] 文档覆盖所有系统模块
- [ ] `python start.py` 统一启动 CLI/Web```
