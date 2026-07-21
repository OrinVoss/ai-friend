# A1：Web 可选 token 鉴权（web.md 一期）

日期：2026-07-21

## 背景

Web 端此前**零鉴权**：绑定 `0.0.0.0`（穿透/局域网场景）时，任何能访问地址的人都能操作全部 API（聊天、监控、清空监控数据）。按 `doc/refactor/systems/web.md` 一期设计实现可选 token 鉴权。

## 改动

### 服务端

- `config.py` 新增 `web_access_token: str = ""`（**空 = 不启用，行为与现状逐字节一致**）+ env `AI_FRIEND_WEB_ACCESS_TOKEN`；`config.example.json` / `doc/config-reference.md` 同步
- `web/server.py`：
  - `_token_auth` 中间件：启用后 `/api/*` 需要 `Authorization: Bearer <token>` 或 `?token=<token>`（EventSource 不能自定义头）；401 记 warning；静态资源不拦截
  - WS init 消息校验 token 字段，不匹配 `close(code=4001)`
- `web_main.py`：非 loopback 绑定且未设 token 时启动打印醒目告警——**不阻断启动**（避免打断现有穿透部署；告警提示尽快配置）

### 前端

- `web/static/app.js` / `monitor.js`：统一 `authFetch()`（自动带 Bearer 头）+ `withToken()`（SSE query token）；token 存 `localStorage('ai_friend_token')`；401 时弹窗输入令牌并重载；WS init 自动带 token 字段

### 测试（`tests/test_web_auth.py`，+8）

默认开放 / 无凭证 401 / 错 token 401 / Bearer 通过 / query token 通过 / 静态资源不拦截 / WS 坏 token 4001 / WS 免 token 正常。WS 正向用例 mock session_manager 避免真实装配；query token 用例避开 `/api/logs` SSE 流（TestClient 会永远等待），改验路径无关的中间件逻辑。

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**765 passed + 2 skipped**（757 → 765）

## 使用方式

```json
// config.json
"web_access_token": "你的令牌"
```

浏览器首次 401 时输入一次即存 localStorage。空字符串保持现状（回退路径）。

## 备注

- 生产部署当前为 `0.0.0.0` 无 token——启动会看到告警，建议尽快配置。
- `/api/monitor/clear` 改 POST + 限流表扩展属 web.md 二期，不在本项。
