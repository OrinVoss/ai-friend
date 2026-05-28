# 里程碑与 Issue

## 版本规划

| 版本 | 聚焦 | Issues |
|------|------|--------|
| v0.1 | 基础架构稳定：异步 DB、配置管理、工具解析、会话隔离、安全加固 | 22 |
| v0.2 | 记忆系统升级：向量检索、分层次反思、情感值归一化、数据隔离 | 9 |
| v0.3 | 情感与人格：情绪模型增强、人格特质深度化、梦境机制、Provider 抽象 | 5 |
| v0.4 | 主动性与规划：主动性升级、Web 安全、REST API 加固、性能优化 | 6 |
| v0.5 | 工程与质量：单元测试、前端优化、文档、错误处理 | 13 |

**总计**: 55 issues

## Issue 列表

### v0.1 — 基础架构稳定

- 重构：拆分 Agent God Class
- 重构：统一 CLI/API 双代码路径
- 异步数据库驱动：替换 sqlite3 为 aiosqlite
- 工具调用解析：用结构化输出替代正则提取
- 配置管理：支持环境变量覆盖
- 会话隔离：conversation_turns 加 session_id 列
- Session 泄漏：WebAgent 字典永不清理
- 多 proactive_loop 竞争条件
- 安全：API Key 改为环境变量读取
- 工厂函数：消除 main.py/session.py 重复初始化
- 性能：情感分析每轮重复调用两次
- 安全：ReadFileTool 路径穿越
- 线程安全：ConversationBuffer 加锁
- 错误处理：bare except 静默吞异常
- Token 估算：替换 cl100k_base 为 DeepSeek tokenizer
- Bug：API 路径上下文压缩永不触发
- 配置：config.json 与 config.py 默认值不一致
- Schema 迁移：ALTER TABLE 每次启动都执行
- 数据安全：Reflections 直接 DELETE 无软删除
- Bug：format_for_prompt 截断方向错误
- 超时：provider 180s timeout 硬编码
- 工程：缺 requirements.txt / pyproject.toml

### v0.2 — 记忆系统升级

- 向量检索：引入 Embedding 语义检索
- 分层次反思：深层/浅层反思分离
- 虚假记忆修正：矛盾事实置信度递减
- 情感值饱和：decay_rate 过低丧失动态范围
- 特质忽略：humor/sass 无实际效果
- Bug：_score_facts 原地覆写不写回 DB
- Bug：consolidation pending 重复处理
- 数据隔离：LongTermMemory 无 session_id 过滤
- 性能：情感分析三处重复调用

### v0.3 — 情感与人格

- 情绪模型：引入对话节奏多维影响
- 人格特质：影响记忆/检索/规划全环节
- Provider：定义 BaseProvider ABC
- 情感值归一化：达上下限后重置机制
- 梦境机制：午睡和夜间做梦巩固记忆，时长随情绪变化

### v0.4 — 主动性与规划

- 主动性：基于未完成话题/长期目标驱动
- Web 安全：添加 CORS/速率限制/CSP
- REST API：添加 Pydantic 输入验证
- 性能：每消息写 personality.json 到磁盘
- 封装：Web 层访问 agent 私有方法
- 性能：默认线程池耗尽风险

### v0.5 — 工程与质量

- 测试：搭建单元测试体系（pytest + mock）
- 前端：角色名硬编码 + 缺心跳 + 缺异常处理
- Shutdown：不关闭 DB/取消 task
- Prompt：对话示例可配置化减少浪费
- Bug：异常退出不清理 react 状态
- 前端：segment 独立气泡应合并
- UI：CJK 终端换行宽度计算错误
- Bug：CLI 打字速度忽略配置值
- 文档：architecture.md 过期 + 缺 Web 端文档
- 错误处理：WebSocket 异常静默
- 前端：缺 ARIA/键盘导航
- 安全：前端缺 CSP 头
- CSS：颜色值集中为 CSS 自定义属性
