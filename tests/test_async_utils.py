"""Tests for core/async_utils.py (#263: timeout 传播)"""
import asyncio
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


if __name__ == "__main__":
    unittest.main()
