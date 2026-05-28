# AI 朋友 — 架构与使用文档

> 具有人格、情绪、长短期记忆的 AI 朋友。基于 DeepSeek API，采用 ReAct Agent 架构，支持 CLI 和 Web 双端。

---

## 快速开始

### 环境要求

- Python 3.12+
- 依赖：`requests`、`tiktoken`、`plyer`、`fastapi`、`uvicorn`

### 安装

```bash
pip install requests tiktoken plyer fastapi uvicorn
cp config.example.json config.json
# 编辑 config.json 填入 API Key
```

### 启动

```bash
# CLI 模式
python main.py

# Web 模式
python web_main.py
# → http://localhost:8000
```

### 自定义人格

编辑 `personality.json`：

| 字段 | 说明 |
|------|------|
| `name` | AI 名字 |
| `traits` | 性格特质及强度 (0~1) |
| `speaking_style` | 说话风格描述 |
| `backstory` | 背景故事 |
| `interests` | 兴趣领域 |

### 内置命令

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情 |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |
| `/help` | 帮助 |

---

## 架构总览

```
浏览器/终端
    │
    ├── CLI: python main.py → ConsoleInterface
    │
    └── Web: python web_main.py → FastAPI + WebSocket
              │
              ├── web/server.py  (HTTP + WS 端点)
              ├── web/session.py (会话管理)
              └── web/static/    (前端界面)
    │
    ▼
core/agent.py  (ReAct 状态机)
    │
    ├── core/personality.py  (人格 + 情绪引擎)
    ├── core/provider.py     (LLM API 客户端)
    ├── core/dispatcher.py   (tool_call 解析执行)
    │
    ├── memory/
    │   ├── short_term.py    (对话缓冲)
    │   ├── long_term.py     (SQLite 封装)
    │   ├── retrieval.py     (三层检索)
    │   └── consolidation.py (记忆合并)
    │
    ├── tools/               (Tool 系统)
    ├── storage/             (SQLite 存储)
    ├── prompts/             (提示词模板)
    └── models/              (数据模型)
```

---

## Agent 循环

### 状态机

```
BOOT → IDLE → PERCEIVE → THINK → ACT → REFLECT → IDLE
                ↑          │              │
                │    有 tool_call         │
                └────── 继续迭代 ←───────┘
```

- **BOOT**：加载人格，播放欢迎语
- **IDLE**：等待输入；空闲超时则主动发起对话
- **PERCEIVE**：存对话、检索记忆
- **THINK**：组装 system prompt，调用 LLM，解析 tool_call
- **ACT**：有工具调用则执行并继续迭代，否则输出最终回复
- **REFLECT**：情绪更新、记忆合并、定期保存

### 情绪模型

VAD 二维空间 + 8 维 Plutchik 基础情绪：

| 维度 | 范围 | 说明 |
|------|------|------|
| valence | -1~1 | 积极/消极 |
| arousal | 0~1 | 兴奋/平静 |
| joy/trust/fear... | 0~1 | 8 维基础情绪 |

特质调制情绪反应：高 empathy → 情感响应 1.5x，高 playfulness → arousal 衰减慢。

回复长度随情绪变化：兴奋时 768 tokens，平静时 512，难过时 256。

### 记忆系统

三层检索：
1. **Hot Memory**：高分 facts + 最新 experiences（常驻 prompt）
2. **Query-Guided**：评分过滤 → LLM 重排序
3. **On-Demand**：LLM 主动调 recall 工具回溯

记忆合并（consolidation）每 5 轮/高强度情绪时触发，抽取 facts、总结 experiences、生成 reflections。

### 工具系统

LLM 通过 `<tool_call>` 调用工具：

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "..."}}
</tool_call>
```

| 工具 | 功能 |
|------|------|
| `recall` | 回忆用户信息或共同经历 |
| `remember` | 记住用户重要信息 |
| `read_file` | 读取本地文件 |
| `notify` | 发送 Windows 桌面通知 |

### 双端设计

| | CLI | Web |
|------|-----|-----|
| 驱动方式 | 状态机循环 | 事件驱动（process_message） |
| 输入 | 非阻塞 stdin 线程 | WebSocket 消息 |
| 输出 | 打字机效果 | 分段推送 + 间隔控制 |
| 主动对话 | IDLE 状态内轮询 | 后台 proactive_loop 协程 |
| 会话 | 单用户 | SessionManager 多会话隔离 |

---

## API 配置

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "max_tokens": 512,
  "temperature": 0.8,
  "proactive_min_idle": 180,
  "web_port": 8000
}
```

## 项目结构

```
├── main.py                  CLI 入口
├── web_main.py              Web 入口
├── config.py                配置加载
├── CLAUDE.md                项目规则
├── personality.json         人格定义
├── data/                    数据库目录
├── changes/                 修改记录
├── doc/                     文档
│
├── core/                    核心引擎
├── memory/                  记忆系统
├── tools/                   工具系统
├── storage/                 数据存储
├── prompts/                 提示词模板
├── models/                  数据模型
├── ui/                      CLI 界面
└── web/                     Web 界面
```
