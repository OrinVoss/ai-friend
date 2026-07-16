# 统一管线 P0：SessionFactory 共享装配

对应 `doc/refactor/systems/unified-pipeline.md` 的 P0（装配统一）。行为不变，消灭双装配漂移，顺带消除 Web 端 Repository 共享竞态。

## 问题

CLI（`main.py`）和 Web（`web/session.py` WebAgent）各自手工装配同一套组件栈（repo → ltm → retriever → consolidator → tools → agent），两份代码已经漂移：CLI 注册 `file_tree`、传 LLM rerank fn，Web 都不做；且 Web 端所有 session 共享**同一个** `Repository` 实例，靠 `repo.session_id = session_id` 改写可变字段——多角色同时活跃时互相踩（web.md P0 立案的竞态）。

## 改动

- `core/session_factory.py`（新建）
  - `build_provider(config)` / `build_embed_engine(config)`：进程共享组件的单一构造点（原先两处各写一遍参数）
  - `assemble_session(...) -> SessionBundle`：每 session 装配完整栈，**Repository 每 session 独立实例**（竞态消除）
  - 两处历史差异保留为显式参数（P0 不改行为）：`include_file_tree`（CLI=True / Web=False）、`enable_llm_rerank`（CLI=True / Web=False）
- `main.py`：手工装配（约 70 行）替换为工厂三行调用；CLI 传 `include_file_tree=True, enable_llm_rerank=True`
- `web/session.py`
  - `WebAgent.__init__` 改为调 `assemble_session`；签名去掉共享 `repo` 参数（`SessionManager.get_or_create` 同步更新）
  - `SessionManager.open()` 的共享 provider/embed engine 改由工厂构造
  - `SessionManager.repo` 保留，仅用于 `session_roles` 全局映射（该表不按 session 隔离）
  - 统一 consolidator 的 monitor source 为 `"consolidation"`（原 Web 用 `"session"`、CLI 用 `"consolidation"`，同一用途两种标签）
- `tests/test_session_factory.py`（新建，5 用例）：
  - 两个 session 的 Repository 独立、互不可见对方 facts（竞态回归）
  - CLI/Web 工具集差异（file_tree）与 rerank 差异按参数保留
  - bundle 接线完整性（agent ↔ registry/retriever/consolidator）
- `doc/refactor/systems/unified-pipeline.md`：P0 标记完成
- `README.md` / `doc/architecture.md`：core 模块 16 → 17，补 session_factory；README 测试 410 → 422 用例 / 33 文件，补 3 个新测试文件

## 测试

- 新增 5 用例 + 相关 session 测试共 26 过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **422 passed, 2 skipped**（基线 417）

## 后续（P1-P3，按 unified-pipeline.md）

- P1 管线统一：MessageHandler 包 ConversationEngine 事件接口，CLI 经 `cli_shared_pipeline` 开关灰度切换，删 CliController 内联 ReAct
- P2 Runtime 下沉：主动/睡眠循环抽 RuntimeDriver，CLI 获得睡眠/主动行为
- P3 收尾：删死代码、命令层统一、文档对齐
