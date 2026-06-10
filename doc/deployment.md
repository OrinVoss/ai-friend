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
uvicorn web.server:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 嵌入服务部署

本地语义搜索依赖 llama.cpp 嵌入服务。

### 1. 下载模型

```bash
# 从 Hugging Face 下载 Qwen3.5-0.8B-Q6_K.gguf
# 放到 models/ 目录
models/
  └── Qwen3.5-0.8B-Q6_K.gguf  (~640MB)
```

### 2. 启动 llama-server

```bash
# Windows
start_embedding_server.bat

# 或手动启动
llama-server.exe -m models/Qwen3.5-0.8B-Q6_K.gguf \
  --host 127.0.0.1 --port 8080 \
  --embeddings --n-gpu-layers 999

# macOS / Linux
llama-server -m models/Qwen3.5-0.8B-Q6_K.gguf \
  --host 127.0.0.1 --port 8080 \
  --embeddings --n-gpu-layers 999
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

    # 安全头
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header Content-Security-Policy "default-src 'self'";
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
| `personality.json` | 人格定义 + 情绪状态 | 定期备份 |

### 备份脚本

```bash
# Windows 批处理
@echo off
set BACKUP_DIR=D:\backups\ai-friend
mkdir %BACKUP_DIR% 2>nul
copy data\ai_friend.db %BACKUP_DIR%\ai_friend_%date:~0,4%%date:~5,2%%date:~8,2%.db
copy personality.json %BACKUP_DIR%\personality_%date:~0,4%%date:~5,2%%date:~8,2%.json
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
| `AI_FRIEND_DB_PATH` | — | 数据库路径覆盖 |
| `AI_FRIEND_LOG_LEVEL` | — | 日志级别覆盖 |

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
- [ ] 设置 Nginx/Caddy 反向代理 + HTTPS
- [ ] 配置合适的 CORS 和 CSP 头
- [ ] 限制 `allowed_read_paths` 范围
- [ ] 数据库文件备份策略
- [ ] 单人使用无需多 session 安全加固

### 已知限制

| # | 问题 | 影响 |
|---|------|------|
| #24 | 无 CORS 配置 | 本地使用不影响 |
| #43 | REST API 无 Pydantic 验证 | 单人使用不影响 |
| #46 | 同步调用占用线程池 | 高并发下可能阻塞 |
| #154 | 数据库无连接池 | 高并发下性能受限 |
