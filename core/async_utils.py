"""Unified async-to-sync bridge. (#134)

Replaces duplicated _run_sync implementations in long_term.py and repository.py.
"""

import asyncio
import concurrent.futures
import contextvars
import logging

logger = logging.getLogger(__name__)

# AU-001: module-level singleton executor
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def run_async(coro, timeout: float = 60.0):
    """Run an async coroutine from synchronous code safely.

    - If no event loop is running, uses asyncio.run() directly.
    - If an event loop IS running (e.g. Web server), bridges via
      ThreadPoolExecutor with a single worker thread.
    - Timeouts propagate cancellation into the running coroutine so that
      cleanup (e.g. DB rollback) can execute instead of leaving zombie work.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # #263: 无循环分支同样应用 timeout，wait_for 超时会掐断协程
        return asyncio.run(asyncio.wait_for(coro, timeout))

    # Already inside an event loop — use a thread to run the coroutine.
    # A3（2026-07-21）：copy_context 显式传播——ThreadPoolExecutor 不会自动
    # 携带 ContextVar，request_id 等上下文需要随任务进入 worker 线程。
    ctx = contextvars.copy_context()
    holder: dict = {}  # worker 启动后填入 task 句柄，供超时取消

    async def _body():
        task = asyncio.ensure_future(coro)
        holder["task"] = task
        return await task

    future = _EXECUTOR.submit(ctx.run, asyncio.run, _body())
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # #263 AU-002/AU-003: 取消传播进协程——CancelledError 会进入协程的
        # try/finally（DB rollback 等清理得以执行），不再留僵尸线程。
        task = holder.get("task")
        if task is not None and not task.done():
            task.get_loop().call_soon_threadsafe(task.cancel)
            try:
                future.result(timeout=5)  # 给清理代码短暂收尾窗口
            except Exception:
                pass  # CancelledError/超时都属预期，结果已被放弃
        else:
            future.cancel()  # worker 尚未排上队，直接取消
        logger.error(f"[async] coroutine timed out after {timeout}s, cancelled")
        raise
