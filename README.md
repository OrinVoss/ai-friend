# AI Friend

具有人格、情绪和长短期记忆的 AI 朋友。基于 DeepSeek API，采用 ReAct Agent 架构，支持命令行和 Web 双端。

## 功能

- **人格系统** — 可自定义的名字、性格特质、说话风格、背景故事
- **情绪引擎** — 8 维 Plutchik 基础情绪 + 心境 + 惯性，情绪随对话自然变化
- **短期记忆** — 最近对话缓冲，动态塞入上下文
- **长期记忆** — LLM 自动抽取事实、总结体验、生成反思，存入 SQLite
- **三层检索** — 评分过滤 → LLM 重排序 → 按需回溯，记忆规模增长不退化的
- **上下文压缩** — 达到 80% 阈值时自动压缩旧对话
- **工具系统** — `recall` / `remember` / `read_file` / `notify` 等工具，LLM 自主调用
- **双端界面** — 命令行控制台 + Web 界面（暗色主题，流式分段输出）
- **主动对话** — 空闲时根据情绪、时间、关系动态计算是否主动找话说

## 快速开始

```bash
pip install requests tiktoken plyer fastapi uvicorn
```

```bash
cp config.example.json config.json
# 编辑 config.json 填入你的 API key
```

```bash
# 命令行模式
python main.py

# Web 模式
python web_main.py
# → http://localhost:8000
```

## 配置

见 `config.example.json`，复制为 `config.json` 后修改：

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "sk-your-key-here",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "max_tokens": 512,
  "temperature": 0.8
}
```

## 人格定制

编辑 `personality.json`：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | AI 的名字 | `"小星"` |
| `traits` | 性格特质及强度 | `{"playfulness": 0.9, "warmth": 0.8}` |
| `speaking_style` | 说话风格 | `"幽默、嘴贫、爱开玩笑"` |
| `backstory` | 背景故事 | `"一个嘴欠但心暖的损友..."` |
| `interests` | 感兴趣的领域 | `["哲学", "音乐", "科技"]` |

## 项目结构

```
├── main.py                  # 命令行入口
├── web_main.py              # Web 入口
├── config.py                # 配置加载
├── personality.json         # 人格定义
│
├── core/
│   ├── agent.py             # 状态机 + ReAct 循环
│   ├── personality.py       # 情绪动力学
│   ├── provider.py          # API 客户端
│   └── dispatcher.py        # tool_call 解析执行
│
├── memory/
│   ├── short_term.py        # 对话缓冲
│   ├── long_term.py         # SQLite 长期记忆
│   ├── consolidation.py     # 记忆合并
│   └── retrieval.py         # 三层检索
│
├── tools/                   # 工具系统
├── web/                     # FastAPI + WebSocket
├── storage/                 # SQLite 层
├── prompts/                 # 提示词模板
├── ui/                      # 命令行界面
├── models/                  # 数据模型
└── doc/                     # 文档
```

## 内置命令 (CLI)

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情 |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |
| `/help` | 帮助 |

## License

MIT
