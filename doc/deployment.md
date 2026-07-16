# 部署手册

> 生产环境部署指南。

---

## 环境要求

| 组件 | 要求 |
|------|------|
| Python | 3.12+ |
| 操作系统 | Windows 10/11（主），Linux/macOS（部分支持） |
| RAM | 最低 512MB（无嵌入），推荐 4GB+（含嵌入） |
| GPU | 可选，用于嵌入模型加速（CUDA） |
| 依赖 | `pip install -r requirements.txt` |

---

## 标准部署

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制配置模板
cp config.example.json config.json

# 编辑配置文件，或直接设置环境变量
set DEEPSEEK_API_KEY=sk-your-key-here
```

### 3. 启动

```bash
# 开发模式 — Web
python web_main.py

# 开发模式 — CLI
python main.py

# 生产模式 — Web
pip install uvicorn
uvicorn web.server:app --host 0.0.0.0 --port 8000
```

> 注意：会话、WebSocket 连接、速率限制等状态都保存在进程内存中
> （`web/server.py` 的模块级 `session_manager`），只能单进程运行，
> **不要** 使用 `--workers` 多进程模式。

---

## 嵌入服务部署

本地语义搜索依赖 llama.cpp 嵌入服务。

**自动启动**：`main.py` 和 `web_main.py` 启动时都会调用
`core/embedding_server.py` 的 `auto_start_embedding()`——若 8080 端口
无服务且模型文件存在，自动拉起 `start_embedding_server.bat`（非阻塞，
后台线程等待就绪，最长 90 秒），服务器输出写入
`logs/embedding_server.log`。模型缺失或服务启动失败时自动降级，见下文。

### 1. 下载模型

```bash
# 从 Hugging Face 下载 Qwen3.5-0.8B-Q6_K.gguf
# 放到 memory/ 目录（llama-server 二进制在 memory/llama-bin/）
memory/
  ├── Qwen3.5-0.8B-Q6_K.gguf  (~640MB)
  └── llama-bin/
        └── llama-server.exe 等
```

### 2. 启动 llama-server

通常无需手动启动（见上文自动启动）。需要手动时：

```bash
# Windows
start_embedding_server.bat

# 或手动启动（与 bat 等效）
memory\llama-bin\llama-server.exe -m memory\Qwen3.5-0.8B-Q6_K.gguf \
  --embeddings --pooling mean --port 8080 \
  -ngl 99 --ctx-size 2048 --batch-size 512 --threads 4 --host 127.0.0.1

# macOS / Linux（需自行准备对应平台的 llama-server 二进制）
llama-server -m memory/Qwen3.5-0.8B-Q6_K.gguf \
  --embeddings --pooling mean --port 8080 \
  -ngl 99 --ctx-size 2048 --batch-size 512 --threads 4 --host 127.0.0.1
```

### 3. 验证

```bash
curl http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": "hello", "model": "default"}'
```

### 优雅降级

嵌入服务不可用时（health_check 失败），系统自动降级为纯关键词检索，不影响核心功能。

---

## Windows 服务注册

### 使用 NSSM（推荐）

```bash
# 下载 nssm.exe
nssm install AIFriend "D:\path\to\python.exe" "D:\path\to\web_main.py"
nssm set AIFriend AppDirectory "D:\path\to\project"
nssm set AIFriend Start SERVICE_AUTO_START
nssm start AIFriend
```

### 使用 Task Scheduler

1. 打开任务计划程序
2. 创建基本任务
3. 触发器：系统启动时
4. 操作：启动程序 → `python web_main.py`
5. 起始于：项目根目录

---

## 反向代理（生产环境）

### Nginx

```nginx
server {
    listen 80;
    server_name ai-friend.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # WebSocket 支持
        proxy_read_timeout 86400;
    }

    # 安全头（与 web/server.py 保持一致）
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header Referrer-Policy strict-origin-when-cross-origin;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://localhost:* http://localhost:* http://127.0.0.1:*; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'";
}
```

### Caddy

```
ai-friend.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

---

## 数据管理

### 数据文件位置

| 文件 | 说明 | 备份建议 |
|------|------|----------|
| `data/ai_friend.db` | SQLite 数据库（全部记忆） | 每日备份 |
| `data/ai_friend.db-wal` / `.db-shm` | WAL 模式伴随文件 | 随主库一起处理 |
| `personalities/*.json` | 角色定义 + 情绪状态 | 定期备份 |

> 系统**没有内置自动备份机制**（P0-4 待办，方案见
> `doc/refactor/systems/database.md`），需自行用脚本或计划任务完成。
> 数据库运行在 WAL 模式（`PRAGMA journal_mode=WAL`，每 1000 页自动
> checkpoint），最新写入可能暂存在 `.db-wal` 中——直接复制 `.db` 文件前
> 应先做 checkpoint（见下文「数据库维护」）或在应用退出后复制
> （应用关闭时会执行 `wal_checkpoint(TRUNCATE)`）。角色文件加载时
> 会自动生成 `.bak` 副本，但这不能替代整体备份。

### 备份脚本

```bash
# Windows 批处理
@echo off
set BACKUP_DIR=D:\backups\ai-friend
mkdir %BACKUP_DIR% 2>nul
copy data\ai_friend.db %BACKUP_DIR%\ai_friend_%date:~0,4%%date:~5,2%%date:~8,2%.db
xcopy /I /E personalities %BACKUP_DIR%\personalities_%date:~0,4%%date:~5,2%%date:~8,2%
```

### 数据库维护

```bash
# WAL 手动 checkpoint
python -c "
import sqlite3
conn = sqlite3.connect('data/ai_friend.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"

# 查看数据库大小
python -c "import os; print(f'{os.path.getsize(\"data/ai_friend.db\") / 1024:.0f} KB')"
```

---

## 环境变量参考

| 变量 | 必须 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | ✓ | DeepSeek API 密钥 |
| `ANYSEARCH_API_KEY` | — | AnySearch 搜索 API 密钥（需要网络搜索时） |
| `DEEPSEEK_API_ENDPOINT` | — | API 地址覆盖 |
| `DEEPSEEK_API_MODEL` | — | 模型名覆盖 |
| `AI_FRIEND_TIMEOUT` | — | API 超时覆盖 |
| `AI_FRIEND_MAX_TOKENS` | — | 最大 token 覆盖 |
| `AI_FRIEND_TEMPERATURE` | — | 温度覆盖 |
| `AI_FRIEND_DB_PATH` | — | 数据库路径覆盖 |
| `AI_FRIEND_LOG_LEVEL` | — | 日志级别覆盖 |
| `AI_FRIEND_WEB_HOST` | — | Web 监听地址覆盖 |
| `AI_FRIEND_WEB_PORT` | — | Web 监听端口覆盖 |
| `AI_FRIEND_EMBEDDING_ENDPOINT` | — | 嵌入服务端点覆盖 |
| `AI_FRIEND_EMBEDDING_DIM` | — | 嵌入维度覆盖 |
| `AI_FRIEND_SHORT_TERM_CAPACITY` | — | 短期记忆容量覆盖 |
| `AI_FRIEND_MAX_TOOL_ITERATIONS` | — | ReAct 工具循环上限覆盖 |
| `AI_FRIEND_TYPING_SPEED` | — | 打字机速度覆盖 |
| `AI_FRIEND_PROMPT_CACHE_TTL` | — | Prompt 缓存 TTL（秒）覆盖 |
| `AI_FRIEND_AGENT1_SHORT_INPUT_THRESHOLD` | — | Agent 1 短输入阈值覆盖 |
| `AI_FRIEND_CONVERSATION_EXAMPLES_MAX_TURNS` | — | 对话示例轮数上限覆盖 |

---

## 端口和防火墙

| 端口 | 用途 | 说明 |
|------|------|------|
| 8000 | Web 服务 | 前端 + API，可按需修改 |
| 8080 | 嵌入服务 | llama-server，仅本地必需 |

### Windows 防火墙

```powershell
# 开放 8000 端口（局域网访问）
New-NetFirewallRule -DisplayName "AI Friend" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

---

## 安全注意事项

### 生产环境 checklist

- [ ] 使用环境变量注入 API Key（**不要** 写入 config.json）
- [ ] 确认 Web 绑定地址：默认 `web_host=0.0.0.0` 监听所有网卡——仅本机使用改为 `127.0.0.1`；局域网/公网暴露必须先过反向代理 + HTTPS
- [ ] 设置 Nginx/Caddy 反向代理 + HTTPS
- [ ] 配置合适的 CORS（`config.allowed_origins`）和 CSP 头
- [ ] 确认速率限制满足预期（默认 REST/WS 聊天 30/60s）
- [ ] 限制 `allowed_read_paths` 范围
- [ ] 数据库文件备份策略
- [ ] 单人使用无需多 session 安全加固

### 已知限制

| # | 问题 | 影响 |
|---|------|------|
| #46 | 同步调用占用线程池 | 高并发下可能阻塞 |
| #154 | 数据库无连接池 | 高并发下性能受限 |

### 已关闭（2026-07-12）

| # | 标题 | 状态 |
|---|------|------|
| #24 | CORS/速率限制/CSP 细化 | ✅ 已关闭 |
| #43 | REST API Pydantic 验证 | ✅ 已关闭 |
| #58 | main.py / web_main.py 启动代码重复 | ✅ 已关闭 |
