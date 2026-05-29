# 里程碑与 Issue

> 最后更新：2026-05-29 | 总计 76 issues（24 已完成，52 开放）

## 版本规划

| 版本 | 聚焦 | Issues | 已完成 | 开放 |
|------|------|--------|--------|------|
| v0.1 | 基础架构稳定 | 29 | 17 | 12 |
| v0.2 | 记忆系统升级 | 9 | 0 | 9 |
| v0.3 | 情感与人格 | 9 | 4 | 5 |
| v0.4 | Web 工程化 | 8 | 1 | 7 |
| v0.5 | 前瞻与质量 | 21 | 2 | 19 |

---

## v0.1 — 基础架构稳定（17/29 完成）

### 已完成

| # | 标签 | 标题 |
|---|------|------|
| #3 | enhancement | 配置管理：支持环境变量覆盖 |
| #11 | bug | Session 泄漏：WebAgent 字典永不清理 |
| #12 | bug | 竞争条件：多 proactive_loop 冲突 |
| #13 | security | 安全：API Key 改为环境变量读取 |
| #14 | refactoring | 工厂函数：消除 main.py/session.py 重复初始化 |
| #15 | performance | 性能：情感分析每轮重复调用两次 |
| #16 | security | 安全：ReadFileTool 路径穿越 |
| #17 | bug | 线程安全：ConversationBuffer 加锁 |
| #18 | bug | 错误处理：bare except 静默吞异常 |
| #31 | refactoring | 重构：统一 CLI/API 双代码路径 |
| #33 | bug | Bug：API 路径上下文压缩永不触发 |
| #34 | bug | 配置：config.json 与 config.py 默认值不一致 |
| #35 | bug | Schema 迁移：ALTER TABLE 每次启动都执行 |
| #36 | bug | 数据安全：Reflections 直接 DELETE 无软删除 |
| #37 | bug | Bug：format_for_prompt 截断方向错误 |
| #38 | bug | 超时：provider 180s timeout 硬编码 |
| #39 | infrastructure | 工程：缺 requirements.txt |

### 开放

| # | 标签 | 标题 | 说明 |
|---|------|------|------|
| #1 | performance | 替换 sqlite3 为 aiosqlite | 大重构，后续迭代 |
| #2 | enhancement | 用结构化输出替代正则提取 tool_call | 需 API 支持 |
| #10 | bug | conversation_turns 加 session_id | schema 变更 |
| #30 | refactoring | 拆分 Agent God Class | 大重构 |
| #32 | bug | 替换 cl100k_base 为 DeepSeek tokenizer | 调研中 |
| #68 | bug | process_message 与状态机双重处理 | |
| #69 | bug | 破防机制 Web 路径情感分析滞后一轮 | |
| #70 | bug | 工具调用循环后续轮 token 限制过低 | |
| #71 | bug | _compress_context 缺少递归保护 | |
| #72 | performance | reversed(get_all) 频繁创建迭代器 | |
| #73 | bug | personality.save 重复保存 | |
| #74 | bug | _tool_registry 初始化为 None | |
| #75 | bug | CLI 路径 sentiment + consecutive_negative 重复 | |

---

## v0.2 — 记忆系统升级（0/9 完成）

| # | 标签 | 标题 |
|---|------|------|
| #4 | enhancement | 向量检索：引入 Embedding 语义检索 |
| #5 | enhancement | 分层次反思：深层/浅层反思分离 |
| #6 | enhancement | 虚假记忆修正：矛盾事实置信度递减 |
| #19 | bug | 情感值饱和：decay_rate 过低丧失动态范围 |
| #20 | bug | 特质忽略：humor/sass 无实际效果 |
| #21 | bug | _score_facts 原地覆写不写回 DB |
| #22 | bug | consolidation pending 重复处理 |
| #40 | bug | LongTermMemory 无 session_id 过滤 |
| #41 | performance | 情感分析三处重复调用 |

---

## v0.3 — 情感与人格（4/9 完成）

### 已完成

| # | 标签 | 标题 |
|---|------|------|
| #59 | bug | Bug：主动回复循环触发导致刷屏 |
| #76 | enhancement | 情绪记仇/怨恨机制 — 高 anger 后信任恢复减速 |
| #77 | enhancement | 情绪维度分速衰减 — 不同情绪不同半衰期 |
| #78 | enhancement | 情绪事件的对话记忆 — AI 记得为什么生气 |

### 开放

| # | 标签 | 标题 |
|---|------|------|
| #7 | enhancement | 情绪模型：引入对话节奏多维影响 |
| #8 | enhancement | 人格特质：影响记忆/检索/规划全环节 |
| #23 | refactoring | Provider：定义 BaseProvider ABC |
| #42 | enhancement | 情感值归一化：达上下限后重置机制 |
| #55 | enhancement | 梦境机制：午睡和夜间做梦巩固记忆 |

---

## v0.4 — Web 工程化（1/8 完成）

| # | 标签 | 标题 | 状态 |
|---|------|------|------|
| #9 | enhancement | 主动性：基于未完成话题/长期目标驱动 | ✅ |
| #24 | security | Web 安全：添加 CORS/速率限制/CSP | |
| #43 | enhancement | REST API：添加 Pydantic 输入验证 | |
| #44 | performance | 性能：每消息写 personality.json | |
| #45 | refactoring | 封装：Web 层访问 agent 私有方法 | |
| #46 | performance | 性能：默认线程池耗尽风险 | |
| #57 | bug | 持久化：Web 端持久化全面排查与修复 | |
| #58 | refactoring | 重构：统一启动入口 + 消除重复初始化 | |

---

## v0.5 — 前瞻与质量（2/21 完成）

| # | 标签 | 标题 | 状态 |
|---|------|------|------|
| #60 | enhancement | 情绪模型从单向度升级为多维对话动态 | |
| #63 | enhancement | 人格特质渗透到全认知链路（OCEAN） | |
| #64 | enhancement | 主动对话加入内在驱动力模型 | |
| #65 | enhancement | 记忆检索引入向量语义搜索 | |
| #66 | enhancement | 记忆反思机制升级为分层反思 | |
| #67 | bug | 虚假记忆检测与矛盾修正机制 | |
| #25 | infrastructure | 测试：搭建单元测试体系（pytest） | |
| #26 | bug | 前端：角色名硬编码 + 缺心跳 | |
| #27 | bug | Shutdown：不关闭 DB/取消 task | |
| #28 | enhancement | Prompt：对话示例可配置化 | |
| #29 | bug | 异常退出不清理 react 状态 | |
| #47 | enhancement | 前端：segment 独立气泡应合并 | |
| #48 | bug | UI：CJK 终端换行宽度计算错误 | |
| #49 | bug | CLI 打字速度忽略配置值 | |
| #50 | documentation | 文档过期 + 缺 Web 端文档 | |
| #51 | bug | WebSocket 异常静默 | |
| #52 | enhancement | 前端缺 ARIA/键盘导航 | |
| #53 | security | 前端缺 CSP 头 | |
| #54 | refactoring | CSS 颜色集中为自定义属性 | |
