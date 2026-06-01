"""Unified async-to-sync bridge. (#134)

Replaces duplicated _run_sync implementations in long_term.py and repository.py.
"""

import asyncio
import concurrent.futures
import logging

logger = logging.getLogger(__name__)


def run_async(coro, timeout: float = 60.0):
    """Run an async coroutine from synchronous code safely.

    - If no event loop is running, uses asyncio.run() directly.
    - If an event loop IS running (e.g. Web server), bridges via
      ThreadPoolExecutor with a single worker thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Already inside an event loop — use a thread to run the coroutine
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.error(f"[async] coroutine timed out after {timeout}s")
            raise
