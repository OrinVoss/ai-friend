# 2026-06-25 Week 2 收尾 — 核心层 P1 全部完成

## 修改原因

完成 v0.5 计划第 2 周（稳固期）剩余的 P1 可靠性缺陷，覆盖睡眠系统隔离、Web
安全增强、Session 资源管理、检索/上下文性能与正确性修复，并同步全部文档。
目标"解决剩余的 bug，更新所有文档，本地推送"。

## 修改文件与摘要

### 核心层

- `core/sleep_manager.py` — SL-001 按 session_id 命名睡眠状态文件；SL-002 用
  `asyncio.Lock` 保护 `_sleeping` 过渡临界区；SL-010 `get_sleep_state`/`generate_dream`
  改为 `async def`，proactive_loop 直接 `await`，不再经 `run_in_executor` 阻塞线程池。
- `core/agent.py` — 睡眠状态文件改为 `.sleep_state.{session_id}`，`_get_sleep_state`/
  `_generate_dream` 转发改为 async。
- `core/message_handler.py` — MH-001 传全部 ToolRequest 给 Agent 2（新增 `run_with_requests`），
  多工具请求不再丢失；MH-007 `_build_messages` token 估算从 `messages[-5:]` 改为累计
  `running_total`，长历史不再越过压缩阈值。
- `core/tool_agent.py` — 新增 `run_with_requests()` 批量执行多个 ToolRequest 并合并结果。
- `core/inner_drive.py` / `core/cli_controller.py` — `format_for_prompt(max_chars=)` 跟随
  ST-003 改为 `max_tokens=`（3000→1800, 2000→1200）。
- `memory/short_term.py` — ST-002 修正 `get_all_reversed` 注释；ST-003 `format_for_prompt`
  参数 `max_chars` → `max_tokens`，去掉 `*0.6` 折算。
- `memory/retrieval.py` — RT-006 `retrieve_for_query` 只编码 query 一次，向量透传给
  `_hybrid_score` / `_search_experiences_semantic`，避免重复编码。
- `storage/database.py` — S-006 `initialize()` 末尾 `INSERT OR IGNORE` stamp schema_version=1
  并 commit，让 schema_version 表真正可用作迁移版本门控。

### Web 层

- `web/server.py` — WS-003 CORSMiddleware（仅 localhost:8000/127.0.0.1:8000）；
  WS-028 CSP 中间件；WS-027 X-Frame-Options DENY + nosniff + Referrer-Policy；
  WS-021 `receive_text` 协议层 max_size=102400（应用层 len 校验保留）；lifespan shutdown
  调用 `cleanup_old()`；`_proactive_loop` 改为 `await ag._get_sleep_state()`/`await ag._generate_dream()`。
- `web/session.py` — SN-005/006 SessionManager 级别共享 Provider + EmbeddingEngine，
  每个 WebAgent 复用而非各自新建；SN-013 新增 `WebAgent.close()`，remove/evict/shutdown
  均调用；SN-016 lifespan shutdown 调用 `cleanup_old()`，消除死代码。

### 测试

- `tests/test_sleep_manager.py` — 用例改用 `asyncio.run()` 适配 async API。
- `tests/real_api/test_dream.py` — 同上。
- `tests/test_embeddings.py` — 真实服务器不可达时 `skipTest`（#196），离线/CI 不再失败。

### 配置 / 忽略

- `.gitignore` — 新增 `.sleep_state.*` 忽略多 session 睡眠状态文件。

### 文档

- `doc/v05-plan/week-2-stabilization.md` — 45 项全部标记 ✅，测试数 288 passed + 2 skipped。
- `doc/v05-plan/README.md` — 第 1-2 周 P0/P1 全部完成 ✅。
- `doc/technical.md` — 标注 SL-010 async 化、SL-002 锁保护；新增 `run_with_requests`；
  移除已删 `process_dream` 行。
- `doc/message-flow.md` — proactive_loop 流程图改为 `await _get_sleep_state`/`await _generate_dream`。
- `doc/api.md` — Session 隔离表补齐 R/SN/SL 修复项；安全加固状态表替换"已知安全缺口"。
- `README.md` — 测试用例数 290 → 288 passed + 2 skipped；v0.5 计划状态标注第 1-2 周完成。

## 验证

- `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py` ✅
- `pytest tests/ --ignore=tests/real_api` → 288 passed, 2 skipped ✅
