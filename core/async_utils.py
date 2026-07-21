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
    future = _EXECUTOR.submit(ctx.run, asyncio.run, coro)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # AU-002: cancel future on timeout
        # #263: cancel() 对已在运行的线程是 no-op —— 协程仍在后台继续执行，
        # 超时只是放弃等待其结果，并不会终止协程本身。
        future.cancel()
        logger.error(f"[async] coroutine timed out after {timeout}s")
        raise
