# AI Friend 项目规则

## 修改记录

每次修改本项目文件时，必须在 `changes/` 目录下创建修改记录文件。

- 文件命名格式：`YYYY-MM-DD-简短描述.md`
- 记录内容：修改的文件、修改原因、修改内容摘要

## 项目路径

D:\桌面\编程作品\AI朋友

## 架构概要

```
CLI (main.py) ──▶ Agent.run() 状态机循环
Web (web_main.py) ──▶ SessionManager ──▶ Agent.process_message()
                           │
共享核心 ──────────────────┘
  三层 Agent 架构：Agent 1 InnerDrive → Agent 2 ToolAgent → Agent 3 Roleplay
  core/inner_drive.py   Agent 1：自主推理 + 记忆检索 + 缺口决策 + 主动行为决策（chat/explore/silent）
  core/tool_agent.py    Agent 2：外部工具执行 + ToolAttemptTracker（3retry×3round）
  core/agent.py         Agent 3：ReAct Agent + 降级（3次工具失败→跳过）+ 破防机制
  core/personality.py   情绪引擎（四层：输入→调制+衰减→怨恨→事件记忆）
  core/embedding_server.py  共享 embedding server 启动（CLI/Web 共用）
  core/provider.py          LLMProvider(ABC) 抽象基类 + DeepSeekProvider 实现（trust_env=False）
  core/async_utils.py       异步→同步桥接（run_async，线程池安全，60s 超时）
  memory/                   短期(LRU+Lock) / 长期(SQLite) / FactChecker(矛盾+衰减) / 检索(三层)
  storage/repository.py     session_id 隔离 + commit 强制 + get_similar_facts
  tools/                    Agent 1,3: recall/remember / Agent 2: web_fetch/web_search/read_file/glob/grep/music/notify
  models/personality.py     EmotionalState（VAD + 8 Plutchik + resentment + emotion_events）
  web/server.py             FastAPI + WebSocket + Pydantic 校验 + CORS/速率限制/CSP
  web/session.py            SessionManager（24h TTL + 引用计数）+ WebAgent（封装 Agent 私有接口）
  web/schemas.py            Pydantic 请求/响应模型（ChatRequest / ChatResponse / ...）
  web/rate_limit.py         内存滑动窗口限流中间件
  web/static/style.css      CSS 变量统一暗色主题颜色
```

## 关键命令

- `pip install -r requirements.txt` — 安装依赖
- `python main.py` — CLI 模式启动（自动启动嵌入服务器）
- `python web_main.py` — Web 模式启动（http://localhost:8000，自动启动嵌入服务器）
- 提交前运行 `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py` 检查语法

## Bug 修复流程

- 发现 bug 后**先创建 GitHub issue**，再修复代码
- Issue 需包含：现象描述、根因分析、修复方案
- 修复 commit message 引用 issue 编号（如 `Fix #59: ...`）
- 修复后更新 changes/ 修改记录

## 文档规范

- 写技术文档时善于使用 ASCII 图（流程图、状态机、架构图、数据流图）来表达
- 更新代码的同时更新对应的 doc、README、changes、CLAUDE.md
- README 和 doc/architecture.md、doc/api.md、CLAUDE.md 保持同步更新
- doc/ 下现有 13 份文档：architecture.md, technical.md, message-flow.md, api.md, config-reference.md, personality-guide.md, testing-guide.md, tool-development.md, prompt-reference.md, deployment.md, startup-flow.md, incident-dispatcher-alias-conflict.md, known-issues.md
- 严重 bug 修复后需撰写 `doc/incident-*.md` 事件报告（现象、根因、修复、经验教训）
- 存在但不紧急的问题记录到 `doc/known-issues.md`，按模板格式维护

## 代码规范

- API 调用使用 `trust_env=False` 避免 Windows 系统代理拖慢请求
- Web 端每次请求结束时调用 `record_emotion_event()` 记录强情绪
- 主动回复（handle_proactive/handle_explore）加入短期记忆和数据库（`add_to_history=True`），确保刷新后可见
- 环境变量优先级高于 config.json（DEEPSEEK_API_KEY 等）
- Provider 必须继承 `LLMProvider(ABC)`，通过抽象接口注入 Agent
- Web 层通过 `WebAgent` 公共接口与 Agent 交互，禁止直接访问 `agent._xxx`
- REST API 入参/返回使用 `web/schemas.py` 中的 Pydantic 模型，自动获得 422 校验
- CSS 颜色统一使用 `web/static/style.css` 中的 CSS 变量，禁止硬编码色值
- CORS 来源通过 `config.allowed_origins` 扩展；速率限制/CSP 安全头由 `web/server.py` 统一添加
