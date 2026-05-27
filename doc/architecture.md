# AI 朋友 — 架构与使用文档

> 一个具有人格、情绪、长短期记忆的 AI 朋友控制台应用。基于 DeepSeek API，采用 ReAct Agent 架构。

---

## 快速开始

### 环境要求

- Python 3.12+
- `requests`、`tiktoken` 库

### 启动

```bash
pip install requests tiktoken
python main.py
```

### 自定义人格

编辑 `personality.json`，修改以下字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | AI 的名字 | `"小星"` |
| `traits` | 性格特质及强度 (0~1) | `{"warmth": 0.85, "curiosity": 0.9}` |
| `speaking_style` | 说话风格描述 | `"温暖、自然、有点诗意"` |
| `backstory` | 背景故事 | `"一个对世界充满好奇的伙伴..."` |
| `interests` | 感兴趣的领域 | `["哲学", "心理学", "艺术"]` |

### 内置命令

| 命令 | 功能 |
|------|------|
| `/exit` 或 `/quit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情 |
| `/status` | 查看关系状态和记忆统计 |
| `/forget` | 清除短期记忆 |
| `/help` | 显示帮助 |

---

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                     main.py (入口)                        │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   core/agent.py  core/personality  core/provider
   (ReAct 状态机)   (人格+情绪引擎)   (LLM API 客户端)
        │
        ├── memory/          (记忆系统)
        │   ├── short_term   (对话缓冲)
        │   ├── long_term    (SQLite 持久化)
        │   ├── retrieval    (三层检索)
        │   └── consolidation (记忆合并)
        │
        ├── tools/           (工具系统)
        │   ├── traits       (Tool 基类 + 注册)
        │   └── memory_tools (recall / remember)
        │
        ├── core/dispatcher  (tool_call 解析执行)
        ├── prompts/         (System prompt 组装)
        ├── storage/         (SQLite 存储层)
        ├── ui/              (打字机UI + 非阻塞输入)
        └── models/          (纯数据模型)
```

---

## Agent 循环架构

### 状态机

```
BOOT ──▶ IDLE ──▶ PERCEIVE ──▶ THINK ──▶ ACT ──▶ REFLECT ──▶ IDLE
(启动)   (等待)    (理解+检索)   (调用LLM)  (执行工具)  (更新状态+   (循环)
                                         │         记忆合并)
                                   ┌─────┴──────┐
                                   │ 有 tool_call │
                                   └─────┬──────┘
                                         └──▶ THINK (多轮迭代)
```

### ReAct 工具循环

一次用户输入可能触发多轮 ReAct 循环（最多 5 轮）：

1. **THINK**：构建 system prompt + 调用 LLM
2. **解析**：从 LLM 回复中提取 `<tool_call>` 标签
3. **ACT**：有工具调用 → 执行工具 → 结果喂回 LLM → 回到 THINK
4. **完成**：无工具调用 → 输出最终回复 → REFLECT

### 工具调用格式

LLM 输出中的工具调用格式：

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "用户喜欢什么"}}
</tool_call>
```

支持工具：

| 工具 | 功能 |
|------|------|
| `recall` | 回忆关于用户的信息或共同经历 |
| `remember` | 主动记住用户的重要信息 |
| `read_file` | 读取本地文件内容（代码、文档、配置等） |

### 主动发起对话

空闲超过 60 秒后，AI 可以根据以下因素主动发起对话：

- 空闲时间（越长越可能）
- 当前情绪 arousal（越高越活跃）
- 最近是否道别（道别后降低概率）

---

## 记忆系统

### 三层检索架构

记忆检索分为三层，解决规模退化问题：

**Layer 1: Hot Memory（常驻）**
- 最高分 facts、最新 experiences、当前关系状态
- 每次 REFLECT 阶段刷新

**Layer 2: Query-Guided（每轮检索）**

Step A — 评分过滤（纯公式，无 LLM）：
```
score = w₁ × 时效性 + w₂ × 重要性 + w₃ × 回忆衰减 + w₄ × 分类提升 + w₅ × 关键词命中
```

Step B — LLM 重排序（候选 > 15 条时触发）：
```
用户说: "..."
哪些记忆相关？回复序号，逗号分隔。
→ 只取 LLM 选中的 3-8 条注入实际 prompt
```

**Layer 3: On-Demand（按需回溯）**
- LLM 可在回复中输出 `<tool_call>{"name": "recall", ...}</tool_call>` 主动回忆
- 不占用每轮 prompt 空间

### 记忆生命周期

| 阶段 | 触发条件 | 操作 |
|------|----------|------|
| 记录 | 每轮对话 | 存入 conversation_turns |
| 合并 | 每 5 轮 / 高强度情绪 | 抽取 facts + 总结 experiences |
| 归档 | score < 0.2 | 排除出常规检索 |
| 衰减 | 每天未 recall | composite_score × 0.99 |
| 软删除 | 归档 > 90 天 | 自动清理 |

### 上下文压缩

- 模型上下文：**180,000 tokens**（DeepSeek v4）
- 压缩阈值：**80%（~144,000 tokens）**
- 触发方式：每次请求动态计算 token，超过阈值自动触发
- 压缩方式：用 LLM 将旧对话生成摘要 → 注入 system prompt → 清空短期 buffer
- Token 估算：优先使用 `tiktoken`（cl100k_base），不可用时用智能启发式（CJK ÷ 1.5, ASCII ÷ 4）

---

## 情绪与人格

### 情绪模型

二维情绪空间：

| 维度 | 范围 | 说明 |
|------|------|------|
| valence | -1.0 ~ 1.0 | 积极/消极 |
| arousal | 0.0 ~ 1.0 | 兴奋/平静 |

`(valence, arousal)` → 情绪标签：

| valence | arousal | 情绪 |
|---------|---------|------|
| > 0.5 | > 0.6 | excited |
| > 0.5 | < 0.4 | content |
| > 0 | 0.4-0.6 | engaged |
| < 0 | > 0.5 | anxious |
| < -0.3 | < 0.4 | melancholy |
| < -0.5 | > 0.6 | frustrated |
| 其他 | | neutral |

### 情绪动力学

1. **交互影响**：根据用户情感、是否分享个人信息、话题活跃度计算 delta
2. **特质调制**：高 empathy → 情感反应 1.5×，高 playfulness → arousal 衰减更慢
3. **自然衰减**：每次交互后趋向 baseline

### 关系指标

| 指标 | 范围 | 更新方式 |
|------|------|----------|
| trust | 0~1 | 用户积极情感时增加 |
| familiarity | 0~1 | 每次对话缓慢增加 |
| intimacy | 0~1 | 用户分享个人信息时增加 |
| playfulness | 0~1 | 用户幽默互动时增加 |

---

## 项目结构

```
ai_friend/
├── main.py                 # 入口
├── config.py               # 配置加载
├── personality.json        # 人格定义
├── ai_friend.db            # SQLite (自动创建)
│
├── core/
│   ├── agent.py            # ReAct 状态机主循环
│   ├── personality.py      # 人格 + 情绪动力学
│   ├── provider.py         # Kimi API 客户端 (streaming)
│   └── dispatcher.py       # tool_call 解析 + 执行
│
├── memory/
│   ├── short_term.py       # 对话缓冲
│   ├── long_term.py        # 长期记忆 CRUD
│   ├── retrieval.py        # 三层检索
│   └── consolidation.py    # 记忆合并 (LLM 抽取)
│
├── tools/
│   ├── traits.py           # Tool 基类 + ToolRegistry
│   └── memory_tools.py     # recall / remember 工具
│
├── models/                 # 纯数据模型
├── storage/                # SQLite 存储层
├── prompts/                # System prompt 组装
├── ui/                     # 打字机效果 + 非阻塞输入
├── utils/                  # 工具函数
└── doc/                    # 文档
```

---

## API 配置

默认使用 DeepSeek v4 API。可通过 `config.json` 覆盖：

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "your-key-here",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "max_tokens": 512,
  "short_term_capacity": 500,
  "consolidation_interval": 5,
  "proactive_min_idle": 60.0,
  "typing_speed": 0.02
}
```

---

## 数据库 Schema

SQLite 自动创建，5 张核心表：

| 表 | 用途 |
|----|------|
| `user_facts` | 用户事实（含评分和置信度） |
| `experiences` | 共享体验（含情感色调和重要性） |
| `reflections` | 反思洞察 |
| `relationship_metrics` | 关系指标 |
| `conversation_turns` | 完整对话历史 |

---

## 错误处理策略

| 场景 | 处理 |
|------|------|
| API 不可达 | 指数退避重试 (2s/4s/8s) |
| 流中断 | 显示已累积内容，进入 REFLECT |
| 数据库异常 | WAL 模式避免锁 |
| personality.json 不存在 | 自动使用默认人格 |
| Ctrl+C | 优雅关闭，保存状态 |
| 工具执行失败 | 结果反馈给 LLM 自主处理 |
| 上下文超限 | 自动压缩后重试 |
