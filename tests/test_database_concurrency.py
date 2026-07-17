"""Tests for storage/database.py — H-03: 事务级互斥（threading.Lock）。

run_async 每次调用都新建事件循环，旧的「按 loop id 缓存 asyncio.Lock」方案
在 4 个 worker 线程间毫无互斥。这里用计数器 read..write 事务验证串行化：
没有真互斥时，SELECT 与 UPDATE 之间让出协程必然交织，产生丢失更新。
"""
import asyncio
import threading
import unittest

from core.async_utils import run_async
from storage.database import Database

THREADS = 8
INCREMENTS_PER_THREAD = 10


class TestCursorThreadSafety(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())
        asyncio.run(self._setup_counter())

    def tearDown(self):
        asyncio.run(self.db.close())

    async def _setup_counter(self):
        async with self.db.cursor() as c:
            await c.execute("CREATE TABLE h03_counter (id INTEGER PRIMARY KEY, value INTEGER)")
            await c.execute("INSERT INTO h03_counter (id, value) VALUES (1, 0)")
            await self.db.commit()

    async def _increment(self):
        """一次读-改-写事务；commit 放在 cursor 块内（与 repository 写方法同款）。"""
        async with self.db.cursor() as c:
            await c.execute("SELECT value FROM h03_counter WHERE id = 1")
            row = await c.fetchone()
            # 让出协程放大交织窗口；有真互斥时其他线程根本进不了临界区
            await asyncio.sleep(0.01)
            await c.execute("UPDATE h03_counter SET value = ? WHERE id = 1", (row[0] + 1,))
            await self.db.commit()

    async def _read_counter(self):
        async with self.db.cursor() as c:
            await c.execute("SELECT value FROM h03_counter WHERE id = 1")
            row = await c.fetchone()
            return row[0]

    def test_concurrent_transactions_are_serialized(self):
        """8 线程 × 10 次自增经 run_async 并发执行，无丢失更新即串行化生效。"""
        def worker():
            for _ in range(INCREMENTS_PER_THREAD):
                run_async(self._increment())

        threads = [threading.Thread(target=worker) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(asyncio.run(self._read_counter()), THREADS * INCREMENTS_PER_THREAD)

    def test_concurrent_transactions_via_executor_bridge(self):
        """同上，但走 run_async 的 executor 桥接路径（调用方线程已有 running loop，
        对应 web 模式生产路径）——4 个 executor worker 并发跑协程也必须互斥。"""
        def worker():
            async def main():
                # 在 running loop 里调 run_async（阻塞本线程），协程被提交到
                # core.async_utils._EXECUTOR 的 worker 线程上跑
                for _ in range(INCREMENTS_PER_THREAD):
                    run_async(self._increment())
            asyncio.run(main())

        threads = [threading.Thread(target=worker) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(asyncio.run(self._read_counter()), THREADS * INCREMENTS_PER_THREAD)

    def test_lock_held_for_whole_cursor_body(self):
        """锁在整个 async with 体期间持有（跨 await），退出后释放。"""
        async def check():
            async with self.db.cursor() as c:
                await c.execute("SELECT 1")
                return self.db._lock.locked()

        self.assertTrue(run_async(check()))
        self.assertFalse(self.db._lock.locked())

    def test_lock_released_on_error(self):
        """事务内出错（触发 rollback 分支）后锁仍被释放，后续事务可继续。"""
        async def bad_txn():
            async with self.db.cursor() as c:
                await c.execute("INSERT INTO h03_counter (id, value) VALUES (1, 99)")  # PK 冲突
                await self.db.commit()

        with self.assertRaises(Exception):
            run_async(bad_txn())
        self.assertFalse(self.db._lock.locked())
        self.assertEqual(asyncio.run(self._read_counter()), 0)  # 冲突行未写入


if __name__ == "__main__":
    unittest.main()
