# 系统增强总览

> 本项目各子系统的一轮完整增强：每个系统的问题是什么、增强了什么、现在到哪一步。
> 顶层运行形态见 `self-system.md`；本文档是全部增强工作的索引与状态板。
> 最后更新：2026-07-16

---

## 1. 总览表

| 子系统 | 核心问题 | 增强方案 | 文档 | 状态 |
|--------|----------|----------|------|------|
| **顶层设计** | 模块各自为战，没有总装图 | 自我系统：一份自我状态 + 三个生命循环（响应/独处/睡眠） | `self-system.md` | 📐 设计完成 |
| **记忆** (L1) | 对话直接存结论，无验证、无遗忘、无来源 | Observation → Fact → Insight 三层生命周期，可验证/可衰减/可追溯 | `layer1-memory/plan.md` | ✅ 全部完成（2026-07-20） |
| **记忆检索** | 相似度 TopK，给什么信什么 | Memory Agent：向量召回 + 交叉验证 + 置信度 + 证据链 | `memory-agent.md` 等 3 份 | ✅ 完成（P0~P2，2026-07-20） |
| **睡眠** | 只有睡相，没有睡眠的功能 | 睡眠工作层流水线：整理→实质性核查→清理→内驱维护→提炼→做梦 | `sleep-cycle.md` | ✅ 主体完成（最小睡眠巩固 + SL-011/012 兜底） |
| **Prompt** (L2) | 每轮重复构建，token 浪费 | 分层缓存 + block 拆分 + Agent 1→3 上下文复用（短输入跳过已移除） | `layer2-prompt/README.md` | ✅ 完成（含 2026-07-21 收尾） |
| **检索架构** (L3) | 所有 Agent 共享同一份 Context | 多阶段检索 + 按 Agent 定制 Retrieval Profile | `layer3-retrieval/README.md` | ✅ 完成（2026-07-21） |
| **Agent 运行时** (L4) | Handler 直接操作内部状态、魔法数字遍地 | 状态机 + ToolExecutionResult + 注册表隔离 + 常量提取 | `layer4-agent/README.md` | ✅ 收尾完成（2026-07-21） |
| **主动性/独处** | 主动决策单次拍脑袋，没有内心世界 | Think Loop + 内驱状态（挂念清单）+ 独处活动内化 | `layer4-agent/` 3 份文档 | ✅ 完成（Think Loop + 内驱状态一二期 + 回馈闭环） |
| **工具系统** (L5) | 错误不分类、重试盲目、串行、无超时无校验 | ToolResult v2 + 错误感知重试 + 参数校验 + 并行 + 智能截断 + 指标 | `layer5-tool/enhancement-plan.md` | ✅ 完成（2026-07-21） |
| **人格绑定** (L6) | 角色、session、记忆混杂 | RoleSession 一一对应，自我状态按角色隔离 | `layer6-personality/README.md` | ✅ 已实现（2026-07-21） |
| **基础设施与接口** | | | | |
| **日志** | 跨天日志写错文件、全链路无请求关联 ID | 滚动日志 + ContextVar request_id + 观测面整合 | `systems/logging.md` | 部分完成（滚动日志 + 监控面板 + 工具/prompt 指标；request_id 未做） |
| **模型 Provider** | 流式截断静默当成功、embedding 子进程无生命周期 | 修截断语义/重试 + 生命周期闭环 + token 预算集中 | `systems/provider.md` | 部分完成（#213/#261 重试与关闭、embedding 托管与自检；截断语义/预算集中未做） |
| **数据库** | ⚠️ 语义检索静默失效、跨 session 泄漏、零备份自动迁移 | embedding 维度修复 + session 过滤 + 迁移前备份 | `systems/database.md` | ✅ 完成（维度修复、session 过滤、P0-3 自动备份、schema v5） |
| **人格内容** | 运行会话覆盖手改、.bak 时机错误、内容零校验 | 合并保存 + 校验器 + 模板与演化 | `systems/personality.md` | 部分完成（H-06 合并保存、RLock；校验器未做） |
| **情绪** | ⚠️ CLI 路径情绪不更新、按轮衰减不按时间 | 统一情绪入口 + 按时间衰减 | `systems/emotion.md` | 部分完成（H-05/M-07 路径统一、R5 负向权重；按时间衰减未做） |
| **Web** | ⚠️ session_id 共享竞态、零访问控制、REST 阻塞事件循环 | 会话隔离 + token 鉴权 + 异步化 | `systems/web.md` | ✅ 主体完成（统一管线 P0-P3、M-12/M-16/L-04；鉴权未做） |
| **CLI** | ⚠️ 与 Web 双轨管线、情绪/睡眠缺失、原始标记喷给用户 | 症状速修 → 管线收敛 → 终端体验 | `systems/cli.md` | ✅ 主体完成（统一管线 P0-P3、M-15 标记过滤） |

✅ = 代码已落地　📐 = 文档设计完成待实现　⚠️ = 发现现存 bug/漏洞，见对应文档

---

## 2. 增强的统一主线

所有增强看似分散，其实遵循同一组原则——这也是检验后续新设计的标尺：

1. **状态唯一**：人格/情绪/内驱/记忆各一份，所有循环共享，不搞模块私有副本
2. **万物有生命周期**：记忆（创建→验证→衰减→删除）、挂念（active→resolved/expired/decayed）——没有只增不减的存储
3. **结构化输出替代关键词匹配**：JSON Schema 约束 LLM 输出（#ID-001 以来的一贯方向），向量模型替代关键词表（线索提取等语义召回场景）
4. **确定性组件 + LLM 最后一步**：Memory Agent 本体不调 LLM；检索/验证/打分确定性可测，语言理解交给本来就存在的 Agent 3
5. **灰度可回退**：双写并行、配置开关（`use_memory_agent` / `proactive_think_loop`），任何增强都能一键退回（`use_observation_fact` 已于 2026-07-18 完整上线后移除）
6. **分期落地**：每期独立可上线，依赖关系显式标注，不憋大招

---

## 3. 建设路线图（按依赖排序）

```
Phase 1（当前）
  ├── ~~开启 use_observation_fact 灰度~~ 已直接完整上线（2026-07-18），线上观察 facts_v2 数据质量
  ├── Memory Agent P0（answer / correct_fact + 测试）
  └── Think Loop + 挂念清单最小版  ← 独处循环开始转

Phase 2
  ├── 内驱状态完整版（类型化 + 生命周期 + 浮现规则）
  ├── 独处内化（solo-activity）     ← 独处有经历
  ├── 睡眠 Stage 4（内驱维护）
  └── 响应路径挂念浮现（surface_for_query）

Phase 3
  ├── Memory Agent 接入 Agent 1（替代 retriever，use_memory_agent 灰度）
  ├── 睡眠 Stage 2（实质性核查）
  ├── Layer 3 多阶段检索
  └── insights_v2 + Insight 替换 Reflection

Phase 4
  └── Layer 6 角色绑定  ← 每个角色一份完整自我状态

平行轨道（无依赖，随时可做）
  └── 工具系统增强 P0 → P1 → P2
```

---

## 4. 文档索引

### 顶层

- `self-system.md` — 自我系统统一架构（**入口**，先读这份）
- `progress.md` — 六层进度总览
- `../systematic-solution.md` — 六层系统性方案（原始问题清单）

### Layer 1 记忆 `layer1-memory/`

- `plan.md` — 生命周期完整实施方案（SQL / 模型 / 迁移策略）
- `insights-from-hms.md` — HMS 启发（存储≠回忆、遗忘是能力、vough/mimi）
- `memory-agent.md` — Memory Agent 设计（确定性管道 + 集成点）
- `memory-agent-clues.md` — 线索提取（向量召回，时间用规则）
- `memory-agent-verification.md` — 交叉验证算法（权重 / 分类型时间线 / 矛盾传播）
- `sleep-cycle.md` — 睡眠循环工作层
- `progress.md` — Layer 1 进度

### Layer 4 独处循环三零件 `layer4-agent/`

- `proactive-think-loop.md` — 主动沉思循环（有界 3 轮，只读回忆）
- `inner-drive-state.md` — 内驱状态（挂念/好奇/反思/计划/灵感 + 生命周期 + 浮现规则 + 回馈闭环）
- `solo-activity.md` — 独处活动与内化（感悟 → 记忆/谈资/情绪）

### 其余各层

- `layer2-prompt/README.md` — Prompt 分层 + 短输入过滤方案
- `layer3-retrieval/README.md` — 多阶段检索架构
- `layer5-tool/enhancement-plan.md` — 工具系统增强
- `layer6-personality/README.md` — RoleSession 绑定

### 基础设施与接口 `systems/`

- `logging.md` — 日志系统增强（滚动日志、request_id 全链路追踪、观测面整合）
- `provider.md` — 模型系统增强（截断语义、重试策略、embedding 生命周期、token 预算集中）
- `database.md` — 数据库系统增强（语义检索修复、session 隔离、备份与迁移安全）
- `personality.md` — 人格内容管理（合并保存、校验、模板与演化）
- `emotion.md` — 情绪系统增强（统一入口、按时间衰减、影响面收口）
- `web.md` — Web 系统增强（会话隔离、鉴权、异步化、前端修复）
- `cli.md` — CLI 系统增强（管线收敛、终端体验）
- `unified-pipeline.md` — CLI 与 Web 统一管线（一个引擎、两个前端、共享装配与 Runtime）
