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
  core/inner_drive.py   Agent 1：自主推理 + 记忆检索 + 缺口决策（输出自然语言工具请求）
  core/tool_agent.py    Agent 2：外部工具执行 + ToolAttemptTracker（3retry×3round）
  core/agent.py         Agent 3：ReAct Agent（状态机 + event-driven 双路径）
  core/personality.py   情绪引擎（四层：输入→调制+衰减→怨恨→事件记忆）
  core/provider.py      DeepSeek API 客户端（trust_env=False）
  memory/               短期(LRU+Lock) / 长期(SQLite) / 检索(三层) / 合并
  tools/                Agent 1,3: recall/remember / Agent 2: web_fetch/web_search/read_file/glob/grep/music/notify
  models/personality.py EmotionalState（VAD + 8 Plutchik + resentment + emotion_events）
```

## 关键命令

- `pip install -r requirements.txt` — 安装依赖
- `python main.py` — CLI 模式启动
- `python web_main.py` — Web 模式启动（http://localhost:8000）
- 提交前运行 `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py` 检查语法

## Bug 修复流程

- 发现 bug 后**先创建 GitHub issue**，再修复代码
- Issue 需包含：现象描述、根因分析、修复方案
- 修复 commit message 引用 issue 编号（如 `Fix #59: ...`）
- 修复后更新 changes/ 修改记录

## 文档规范

- 写技术文档时善于使用 ASCII 图（流程图、状态机、架构图、数据流图）来表达
- 更新代码的同时更新对应的 doc、README、changes
- README 和 doc/architecture.md 保持同步更新

## 代码规范

- API 调用使用 `trust_env=False` 避免 Windows 系统代理拖慢请求
- Web 端每次请求结束时调用 `record_emotion_event()` 记录强情绪
- 主动回复不加入短期记忆（`add_to_history=False`）
- 环境变量优先级高于 config.json（DEEPSEEK_API_KEY 等）
