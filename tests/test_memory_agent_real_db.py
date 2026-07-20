"""Regression: MemoryAgent against a real aiosqlite Database.

2026-07-20 production deadlock: `_retrieve_parallel` used asyncio.gather
over four repo calls; Database.cursor() holds a threading.Lock across
awaits (H-03), so the second coroutine's blocking acquire froze the whole
event loop — Agent 1 hung permanently. The gather is now sequential; this
test runs the real pipeline and fails (instead of hanging) if anything
like it comes back.
"""
import asyncio
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

from core.async_utils import run_async
from memory.lifecycle import MemoryLifecycleManager
from memory.long_term import LongTermMemory
from memory.memory_agent import MemoryAgent
from storage.database import Database
from storage.repository import Repository


class TestMemoryAgentRealDb(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = f"{self._tmp.name}/test.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_answer_completes_on_real_db(self):
        db = Database(self.db_path, backup_enabled=False)
        asyncio.run(db.open())
        repo = Repository(db)
        asyncio.run(repo.upsert_fact_v2("preference", "最爱食物", "披萨",
                                        confidence=0.9))
        ltm = LongTermMemory(repo)
        agent = MemoryAgent(ltm, MemoryLifecycleManager(ltm), MagicMock(),
                            embedding_engine=None)

        box = {}

        def _work():
            try:
                box["r"] = run_async(agent.answer("我最喜欢吃什么"), timeout=30)
            except Exception as e:  # noqa: BLE001 — surfaced via assertion
                box["e"] = e

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        t.join(timeout=20)
        try:
            self.assertFalse(t.is_alive(),
                             "MemoryAgent.answer() deadlocked on a real DB")
            self.assertNotIn("e", box, f"answer() raised: {box.get('e')}")
            self.assertIn("披萨", box["r"].answer)
        finally:
            asyncio.run(db.close())

    def test_cursor_lock_timeout_raises_instead_of_deadlock(self):
        """Two concurrent cursor() users on one loop: the second must get a
        loud RuntimeError within CURSOR_LOCK_TIMEOUT, not a silent freeze."""
        db = Database(self.db_path, backup_enabled=False)
        asyncio.run(db.open())
        db.CURSOR_LOCK_TIMEOUT = 0.5  # 缩短测试时间

        async def _two_concurrent():
            async with db.cursor():
                # 持锁期间同一 loop 再进 cursor() —— 必须快速报错
                async with db.cursor():
                    pass

        with self.assertRaises(RuntimeError):
            asyncio.run(asyncio.wait_for(_two_concurrent(), timeout=5))
        asyncio.run(db.close())


if __name__ == "__main__":
    unittest.main()
