"""Tests for core/async_utils.py (#263: timeout 传播)"""
import asyncio
import threading
import time
import unittest

from core.async_utils import run_async


class TestRunAsyncNoLoop(unittest.TestCase):
    def test_timeout_applied_in_no_loop_branch(self):
        # #263: 无循环分支的 timeout 必须生效 —— slow coro 被 wait_for 掐断
        async def slow():
            await asyncio.sleep(10)
            return "done"

        t0 = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            run_async(slow(), timeout=0.2)
        self.assertLess(time.monotonic() - t0, 5.0)

    def test_result_returned_within_timeout(self):
        async def fast():
            return 42

        self.assertEqual(run_async(fast(), timeout=5.0), 42)


class TestRunAsyncRunningLoop(unittest.TestCase):
    def test_timeout_propagates_cancellation_into_coro(self):
        # #263 AU-002/AU-003: 在已有事件循环的线程里调 run_async，
        # 超时必须真正取消协程，使其 finally 清理得以执行。
        cleanup_done = threading.Event()
        exception_in_thread = []

        async def slow_with_cleanup():
            try:
                await asyncio.sleep(60)
                return "done"
            finally:
                cleanup_done.set()

        def target():
            try:
                run_async(slow_with_cleanup(), timeout=0.2)
            except asyncio.TimeoutError:
                exception_in_thread.append("timeout")
            except Exception as e:  # pragma: no cover - 调试用
                exception_in_thread.append(repr(e))

        t = threading.Thread(target=target)
        t.start()
        t.join(timeout=10)
        self.assertFalse(t.is_alive())

        self.assertEqual(exception_in_thread, ["timeout"])
        # 给清理代码短暂收尾窗口
        cleanup_done.wait(timeout=1.0)
        self.assertTrue(cleanup_done.is_set())

    def test_result_returned_with_running_loop(self):
        # 有事件循环时正常完成路径不受影响
        async def fast():
            return 99

        def target():
            result.append(run_async(fast(), timeout=5.0))

        result = []
        t = threading.Thread(target=target)
        t.start()
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertEqual(result, [99])


if __name__ == "__main__":
    unittest.main()
