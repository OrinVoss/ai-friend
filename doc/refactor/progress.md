# 重构进度总览

> 最后更新：2026-07-16

## 整体架构六层方案

来源：`doc/systematic-solution.md`

```
Layer 1: Memory 生命周期（Observation → Fact → Insight）
Layer 2: Prompt 分层与静态化
Layer 3: 多阶段 Retrieval
Layer 4: Agent Runtime 解耦
Layer 5: Tool Agent 精简
Layer 6: Personality / Session / 记忆绑定
```

## 当前总览

| Layer | 主题 | 代码状态 | 文档状态 | 负责人 |
|-------|------|----------|----------|--------|
| Layer 1 | Memory 生命周期（Observation → Fact → Insight） | ✅ 全部完成（一期 Fact + 二期 Insight + Memory Agent P0~P2，2026-07-20） | 完整（含 HMS 启发、Memory Agent 设计） | Kimi |
| Layer 2 | Prompt 分层与静态化 | 大部分已完成 | 完整（含短输入过滤优化方案） | Kimi |
| Layer 3 | 多阶段 Retrieval | 未开始 | 设计完成 | Kimi |
| Layer 4 | Agent Runtime 解耦 | 部分已完成 | 完整 | Kimi |
| Layer 5 | Tool Agent 精简 | 大部分已完成（Prompt 已精简） | 完整 | Kimi |
| Layer 6 | Personality / Session / 记忆绑定 | 未开始 | 设计完成 | Kimi |

---

## Layer 1: Memory 生命周期

**代码状态**：一期已完成并推送

**已完成（代码）**：
- [x] 新增 `observations` / `facts_v2` 表
- [x] 新增 `Observation` / `FactV2` 数据模型
- [x] 实现 `MemoryLifecycleManager`（observe / promote / verify / contradict / decay / gc）
- [x] `MemoryConsolidator` 双写 Observation + FactV2
- [x] ~~新增配置开关 `use_observation_fact`（默认 false）~~（2026-07-18 完整上线后删除）
- [x] 测试覆盖（19 个新测试 + 全量 401 passed）
- [x] Changes 文档：`changes/2026-07-14-memory-layer1-observation-fact.md`
- [x] **Layer 1 完整上线（2026-07-18）**：跳过灰度直接上线——user_facts 数据迁移至 facts_v2（schema v4），读路径经 repository 适配器全部切到 facts_v2，单写 promote，旧表归档为 user_facts_archive，开关删除。见 `changes/2026-07-18-memory-layer1-full-launch.md`
- [x] **Layer 1 二期 Insight 上线（2026-07-20）**：直接切换——reflections 数据迁移至 insights_v2（schema v5，有损：旧数据无证据链），读路径经 repository 适配器切到 insights_v2，生成路径改为结构化 Insight JSON（INSIGHT_GENERATION/L2/L3_PROMPT → lifecycle.create_insight），旧表归档为 reflections_archive。见 `changes/2026-07-20-insight-replaces-reflection.md`

**已完成（文档）**：
- [x] 完整实施方案：`layer1-memory/plan.md`
- [x] HMS 启发记录：`layer1-memory/insights-from-hms.md`
- [x] Memory Agent 设计：`layer1-memory/memory-agent.md`
- [x] 线索提取规则：`layer1-memory/memory-agent-clues.md`
- [x] 交叉验证算法：`layer1-memory/memory-agent-verification.md`

**待完成（二期，分阶段）**：

Phase 1（下一步）：
- [x] `insights_v2` 表 + `InsightV2` 模型（2026-07-20，schema v5）
- [x] 用 Insight 替换 Reflection（2026-07-20：直接切换而非双写——迁移 + 适配器重定向 + 旧表归档 reflections_archive）
- [x] Memory Agent P0 实现（answer / correct_fact + 测试）（2026-07-16）
- [x] ~~开启 `use_observation_fact=true` 灰度验证 `facts_v2` 数据质量~~（2026-07-18：跳过灰度，直接完整上线）
- [x] 批量验证旧 Fact（最小版睡眠巩固，`batch_verify_facts`，2026-07-16）

Phase 1.5（Memory Agent P1，2026-07-16 完成）：
- [x] `_extract_clues()`：时间解析（绝对日期范围）+ 意图向量锚点
- [x] `_cross_verify()`：分类型时间线、矛盾检测、stale 检测、综合置信度
- [x] `verify_fact()` 主动验证

Phase 2：
- [x] Memory Agent 完整交叉验证（矛盾传播、LLM 线索提取）（2026-07-20，`changes/2026-07-20-memory-agent-p2.md`：矛盾向上传播 + Insight 证据池 + 向量锚点指代解析）
- [x] Memory Agent 接入 InnerDrive（`use_memory_agent` 灰度开关，默认 false，2026-07-16）
- [x] Retrieval 切换到 `facts_v2` + `insights_v2`（facts_v2：2026-07-18；insights_v2：2026-07-20 经适配器）
- [x] 完整 GC：decay / obsolete / archive / expire_due_insights（merge 保持占位，语义近重复合并推迟）（2026-07-20）
- [x] 旧数据迁移 + 旧表归档（user_facts_archive / reflections_archive；物理 DROP 留待观察期后手动执行）（2026-07-18 / 2026-07-20）

Phase 3（按需）：
- [ ] 跨会话模式发现（完整睡眠巩固）
- [ ] 语义重构 LLM 层
- [ ] 证据链可视化（Web 端）

**阻塞项**：无

---

## Layer 2: Prompt 分层与静态化

**状态**：大部分已完成

**已完成**：
- [x] 分层 Prompt Cache（`core/prompt_cache.py`）
- [x] `prompts/system.py` 拆分为独立 block
- [x] ~~Agent 1 短输入跳过 LLM~~（已于 2026-07-16 整体移除：API 成本低，关键词误判不值得）
- [x] Agent 1 向 Agent 3 传递 `context_summary`
- [x] 静态对话示例仅前 N 轮注入
- [x] 指令集中化（`prompts/instructions.py`）
- [x] 工具规则从 ToolRegistry 动态生成（`prompts/tools_description.py`）
- [x] 情绪摘要化（`EmotionalState.to_prompt_summary()`）
- [x] Tool Agent Prompt 精简

**待完成**：
- [ ] 监控 Prompt Cache 命中率与 token 节省
- [ ] 进一步压缩 Agent 3 Prompt

**阻塞项**：无

---

## Layer 3: 多阶段 Retrieval

**代码状态**：未开始
**文档状态**：设计完成

**已完成（文档）**：
- [x] 多阶段检索架构（Query Analyzer → Parallel Retriever → Cross Verifier → Reranker → Context Builder）
- [x] 各 Agent Retrieval Profile（Agent 1/2/3、Fact Extractor、Memory Agent）

**待完成**：
- [ ] `QueryClues` 数据模型 + `ParallelRetriever`
- [ ] `CrossVerifier` 与 `FactChecker` 集成
- [ ] `ContextBuilder` 按 Agent 类型组装
- [ ] 不同 Agent 使用不同 Retrieval 策略
- [ ] React 默认不读取 Reflection

**阻塞项**：等待 Layer 1 二期完成，Insight 替代 Reflection 后 Context Builder 才有意义

---

## Layer 4: Agent Runtime 解耦

**状态**：部分已完成

**已完成**：
- [x] `MessageHandlerState` 状态机
- [x] `ToolExecutionResult` dataclass
- [x] 魔法数字提取为类常量
- [x] Agent 1/2 工具注册表隔离
- [x] Agent 2 执行逻辑拆分
- [x] 主动沉思循环（Proactive Think Loop）：`assess_proactive()` 3 轮有界循环 + JSON schema + 挂念清单一期（2026-07-18，`changes/2026-07-18-proactive-think-loop.md`）
- [x] 内驱状态二期：类型化条目 + 生命周期 + 情绪联动浮现规则 + 响应路径语义浮现 + consolidation 对照解决/线索写入（2026-07-18，`changes/2026-07-18-inner-drive-state-p2.md`）

**待完成**：
- [ ] 为 `Agent` 添加公开方法，避免直接访问内部属性
- [ ] 改进异常处理，错误时向用户反馈
- [ ] 全局请求超时
- [ ] 依赖注入
- [ ] 强化输入清洗

**阻塞项**：等待 Layer 3 确定各 Agent 的 Context 边界

---

## Layer 5: Tool Agent 精简

**状态**：大部分已完成

**已完成**：
- [x] Tool Agent Prompt 不再包含人格/情绪/关系/回忆
- [x] Tool Agent 仅接收 Task / Available tools / Schema / Retry history

**待完成**：
- [ ] 评估是否进一步限制 Tool Agent 的上下文长度

**阻塞项**：无

---

## Layer 6: Personality / Session / 记忆绑定

**代码状态**：未开始
**文档状态**：设计完成

**已完成（文档）**：
- [x] RoleSession 数据模型设计
- [x] 绑定关系图（Role → personality / session / sleep / embedding）
- [x] 实施步骤（5 步）

**待完成**：
- [ ] 强制 `session_id = role_id`
- [ ] 废弃根目录 `personality.json`
- [ ] `PersonalityManager` 统一加载/保存
- [ ] 情绪状态持久化到 personality 文件
- [ ] 多角色数据隔离验证

**阻塞项**：需要先明确多角色产品形态

---

## 近期待办

1. ~~运行 `use_observation_fact=true` 一段时间，验证 `facts_v2` 数据质量~~（2026-07-18 已直接完整上线，改为线上观察 facts_v2 数据质量）
2. 同一喜好重复 3 次后，确认 `verification_count >= 3` 且 `confidence` 上升
3. 用户更正信息后，确认旧 FactV2 被标记为 `contradicted`
4. 监控 Prompt Cache 实际命中率与 token 节省效果
5. ~~启动 Layer 1 Phase 1：`insights_v2` + Insight 替换 Reflection~~（2026-07-20 已完成，直接切换）；剩余：Memory Agent P0 深化、批量验证旧 Fact

## 相关文档

- `doc/refactor/layer1-memory/`（plan / insights-from-hms / memory-agent / clues / verification）
- `doc/refactor/layer2-prompt/`
- `doc/refactor/layer3-retrieval/`
- `doc/refactor/layer4-agent/`
- `doc/refactor/layer5-tool/`
- `doc/refactor/layer6-personality/`
- `doc/systematic-solution.md`
