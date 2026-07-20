# 修复：Memory Agent gather 并发查询撞上 cursor() 线程锁——Agent 1 永久死锁

日期：2026-07-20

## 现象

Web 端发消息后 Agent 1 永远不出结果（疑似「太慢」）：日志停在 `[inner_drive] start`，之后任何 DB 调用都 60s 超时，runtime tick 连续报 `coroutine timed out after 60.0s`，最终 4 个 run_async worker 线程被吃完，整个服务卡死。

## 根因

两个独立正确的改动叠加出死锁：

1. **H-03（2026-07-17 审计）**：`Database.cursor()` 把跨事件循环失效的 `asyncio.Lock` 换成进程级 `threading.Lock`，跨 await 持有，保证 4 个 run_async worker 线程间的 execute..commit 互斥。注释明确写了约束：**同一事件循环内禁止两个协程并发进入 cursor()**——第二个协程的阻塞 `acquire()` 会冻死整个 loop 线程。
2. **Memory Agent P0（293fa58）**：`_retrieve_parallel` 用 `asyncio.gather` 并发 4 个 repo 查询——正好踩中这条禁令。写的时候 H-03 还没落地，所以当时没炸。

死锁链条：gather 协程 A 持锁 await aiosqlite → 协程 B `lock.acquire()` 阻塞 → **整个事件循环线程冻结** → A 永远没机会释放锁 → 永久死锁。更恶劣的是 `run_async` 的 60s `wait_for` 超时也救不了——loop 死了，超时回调无法执行，表现为无声 hang。之后 runtime tick 的每个 DB 调用都抢这同一把永不释放的锁，worker 线程一个个被永久消耗。

## 修复

- **`memory/memory_agent.py`**：`_retrieve_parallel` 的 `asyncio.gather` 改为 4 个串行 await。SQLite 查询毫秒级，串行无性能损失。
- **`storage/database.py`**：`cursor()` 锁等待加 `CURSOR_LOCK_TIMEOUT = 30s` 上限，超时抛带明确提示的 `RuntimeError`——把这类「同 loop 并发进 cursor」的静默死锁变成响亮报错。

## 回归测试（`tests/test_memory_agent_real_db.py`，+2）

- 真实 aiosqlite DB 上跑完整 `MemoryAgent.answer()`（线程 + join 超时结构，死锁复现时会失败而不是挂住测试套件）。
- 同 loop 并发进 `cursor()` 必须在超时内抛 RuntimeError，而不是冻结。

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**646 passed**（含并行会话 SL-012 的 +4）

## 教训

- repo/DB 层方法在同一个协程上下文里只能串行 await，禁止 gather——已在 `memory_agent.py` 注释中写明。
- 全局搜过 `asyncio.gather`：除测试外只有这一处命中。
- 出现同类症状（日志停在某步不动 + 其他线程连环 60s 超时）应优先怀疑锁/死锁，而不是「慢」。
