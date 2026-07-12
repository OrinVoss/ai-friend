# 2026-07-12 修复 web/server.py middleware 错误 + proxy 导致启动挂死

## 修改原因

Web 服务启动后返回 500 Internal Server Error，原因是 security headers
middleware 注册方式错误；同时 web_main.py 因系统代理导致 _auto_start_embedding
中 urllib 请求挂死，服务无法正常启动。

## 修改文件

- `web/server.py` — 
  1. `_add_security_headers` 从 `Middleware()` 列表改为 `@app.middleware("http")`
     装饰器，修复 TypeError: missing 1 required positional argument: 'call_next'
  2. 添加 `ensure_session()` 函数，首次请求时懒加载 session_manager，作为
     lifespan 未正常触发的兜底
  3. lifespan 函数添加 try/except 异常日志，便于诊断启动问题
