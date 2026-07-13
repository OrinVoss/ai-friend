# 2026-07-13 修复 WebSocket 连不上（websockets 版本不兼容 + 代理/CSP）

## 现象

浏览器控制台反复报 `WebSocket connection to 'ws://localhost:8000/ws' failed`，
页面 HTTP 资源正常加载但聊天连不上。服务端日志表现为 `[ws] accepted` 后
紧跟 `WebSocket disconnected: None`（从无 `[ws] init`），或请求被当成普通
HTTP 返回 404。

## 根因分析

排查中发现**两个独立问题**：

1. **系统代理破坏 WS 握手**（次要 / 环境侧）
   - 系统代理 `127.0.0.1:10808` 开启时，浏览器把 `ws://localhost` 也走了代理。
   - 实测：走代理做普通 HTTP GET 返回 200，但走代理做 WS 握手返回 **404**
     —— 代理转发 HTTP 正常，但会丢掉/破坏 `Upgrade: websocket` 头。
   - curl 直连（不走代理）握手返回 101，证明服务端本身正常。

2. **`uvicorn 0.30.1` + `websockets 16.1` 不兼容**（主要 / 代码侧，根因）
   - uvicorn 0.30.1 的 WS 实现依赖 `websockets` 的 legacy 协议 API；
     websockets 自 14.0 起废弃、后续版本移除/改变了 legacy 行为。
   - `requirements.txt` 只钉了 `uvicorn==0.30.1`，未钉 `websockets`，
     pip 拉取了最新的 16.1，导致 WS 握手/帧处理损坏。
   - 表现：curl（只做裸握手）看似 101 成功；浏览器 `connection open` 后秒断；
     python-websockets 客户端直接 404 —— 同一端点三种客户端三种结果。

## 修复方案

1. **降级 websockets 到 12.0**（uvicorn 0.30.1 官方兼容版本）
   - `pip install websockets==12.0`
   - `requirements.txt` 新增 `websockets==12.0` 并注释原因。
   - 验证：python-websockets 客户端连 `ws://127.0.0.1:8000/ws` 成功拿到
     `init_ok`（含 role/emotion/name），init 往返正常。

2. **CSP `connect-src` 补齐 127.0.0.1 与 wss 变体**
   - `web/static/index.html` 的 CSP 原本只放行 `ws://localhost:*`，
     现补上 `wss://localhost:* ws://127.0.0.1:* wss://127.0.0.1:*`，
     使得通过 `127.0.0.1:8000` 打开页面时 WS 不再被 CSP 拦截。

3. **代理放行 localhost（用户侧配置，非代码改动）**
   - 在代理客户端（v2rayN / Clash / SwitchyOmega）中将 `localhost`、
     `127.0.0.1` 设为直连（DIRECT / bypass），其余流量照常走 10808。

## 修改文件

- `requirements.txt` — 新增 `websockets==12.0`（钉版本 + 原因注释）
- `web/static/index.html` — CSP `connect-src` 补齐 127.0.0.1 / wss

## 备注

- `localhost` 在 Windows 上可能先解析到 IPv6 `::1`，而服务端绑 `0.0.0.0`（IPv4）。
  浏览器有 Happy Eyeballs 会自动回退到 127.0.0.1，不受影响；纯 python 客户端
  测试时建议直接用 `127.0.0.1`。
- 后续若需升级 websockets，应同步升级 uvicorn 到 >=0.34（支持 websockets 新版）。
