# AI Friend

具有人格、情绪和长短期记忆的 AI 朋友。基于 DeepSeek API，采用 ReAct Agent 架构，支持 CLI 和 Web 双端。

## 功能

- **人格系统** — 自定义名字、性格特质、说话风格、背景故事
- **情绪引擎** — VAD 二维空间 + 8 维 Plutchik 基础情绪 + 惯性 + 心境，回复长度随情绪变化
- **短期记忆** — 最近对话缓冲，动态塞入上下文
- **长期记忆** — LLM 自动抽取事实、总结体验、生成反思，存入 SQLite
- **三层检索** — 评分过滤 → LLM 重排序 → 按需回溯
- **上下文压缩** — 达到 80% 阈值时自动压缩旧对话
- **工具系统** — recall / remember / read_file / notify，LLM 自主调用
- **双端界面** — CLI 控制台 + Web（暗色主题，分段独立气泡 + 情绪调速）
- **主动对话** — 空闲时根据情绪、时间、关系动态计算是否主动开启话题
- **会话管理** — 多标签页独立会话，后台 proactive 协程

## 快速开始

```bash
pip install requests tiktoken plyer fastapi uvicorn
```

```bash
cp config.example.json config.json
# 编辑 config.json 填入 API Key
```

```bash
# CLI 模式
python main.py

# Web 模式
python web_main.py
# → http://localhost:8000
```

## 配置

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "sk-your-key",
  "api_model": "deepseek-v4-flash",
  "thinking": "disabled",
  "max_tokens": 512,
  "temperature": 0.8
}
```

## 人格定制

编辑 `personality.json`：

```json
{
  "name": "小星",
  "traits": {
    "playfulness": 0.95,
    "warmth": 0.85,
    "humor": 0.9,
    "empathy": 0.8,
    "sass": 0.75
  },
  "speaking_style": "幽默、嘴贫、爱开玩笑...",
  "backstory": "一个嘴欠但心暖的损友..."
}
```

## 项目结构

```
├── main.py                  CLI 入口
├── web_main.py              Web 入口
├── config.py                配置加载
├── personality.json         人格定义
├── data/                    数据库目录
├── changes/                 修改记录
├── doc/                     文档
│
├── core/                    核心引擎（Agent / 人格 / Provider / Dispatcher）
├── memory/                  记忆系统（短期 / 长期 / 检索 / 合并）
├── tools/                   工具系统（traits / memory_tools / file_tools / notify）
├── storage/                 SQLite 存储
├── prompts/                 提示词模板
├── ui/                      CLI 界面
└── web/                     Web 界面（FastAPI + WebSocket）
```

## 内置命令（CLI）

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情 |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |

## License

MIT
