# 重构进度总览

> 最后更新：2026-07-14

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

| Layer | 主题 | 状态 | 负责人 |
|-------|------|------|--------|
| Layer 1 | Memory 生命周期（Observation → Fact → Insight） | 一期已完成，双写阶段 | Kimi |
| Layer 2 | Prompt 分层与静态化 | 大部分已完成 | Kimi |
| Layer 3 | 多阶段 Retrieval | 未开始 | - |
| Layer 4 | Agent Runtime 解耦 | 部分已完成 | Kimi |
| Layer 5 | Tool Agent 精简 | 大部分已完成（Prompt 已精简） | Kimi |
| Layer 6 | Personality / Session / 记忆绑定 | 未开始 | - |

---

## Layer 1: Memory 生命周期

**状态**：一期已完成并推送

**已完成**：
- [x] 新增 `observations` / `facts_v2` 表
- [x] 新增 `Observation` / `FactV2` 数据模型
- [x] 实现 `MemoryLifecycleManager`（observe / promote / verify / contradict / decay / gc）
- [x] `MemoryConsolidator` 双写 Observation + FactV2
- [x] 新增配置开关 `use_observation_fact`（默认 false）
- [x] 测试覆盖（19 个新测试 + 全量 401 passed）
- [x] Changes 文档：`changes/2026-07-14-memory-layer1-observation-fact.md`

**待完成（二期）**：
- [ ] 用 Insight 替换 Reflection
- [ ] Retrieval 切换到 `facts_v2` + `insights_v2`
- [ ] 完整 GC：merge / decay / obsolete / archive
- [ ] 删除旧 `user_facts` / `reflections` 表

**阻塞项**：无

---

## Layer 2: Prompt 分层与静态化

**状态**：大部分已完成

**已完成**：
- [x] 分层 Prompt Cache（`core/prompt_cache.py`）
- [x] `prompts/system.py` 拆分为独立 block
- [x] Agent 1 短输入跳过 LLM
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

**状态**：未开始

**待完成**：
- [ ] Query → Intent → Fact → Episode → Reflection → Rank → Context Builder
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

**状态**：未开始

**待完成**：
- [ ] 角色定义文件规范化（`personalities/{role_id}.json`）
- [ ] Session 创建时绑定 `role_id`
- [ ] 多角色数据隔离验证
- [ ] 角色管理接口（CLI / Web）

**阻塞项**：需要先明确多角色产品形态

---

## 近期待办

1. 运行 `use_observation_fact=true` 一段时间，验证 `facts_v2` 数据质量
2. 同一喜好重复 3 次后，确认 `verification_count >= 3` 且 `confidence` 上升
3. 用户更正信息后，确认旧 FactV2 被标记为 `contradicted`
4. 监控 Prompt Cache 实际命中率与 token 节省效果
5. 根据验证结果，决定是否启动 Layer 1 二期

## 相关文档

- `doc/refactor/layer1-memory/`
- `doc/refactor/layer2-prompt/`
- `doc/refactor/layer3-retrieval/`
- `doc/refactor/layer4-agent/`
- `doc/refactor/layer5-tool/`
- `doc/refactor/layer6-personality/`
- `doc/systematic-solution.md`
