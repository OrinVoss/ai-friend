"""M-03: Database.prune_old_turns 真 per-session 修剪。"""
import asyncio
import unittest

from storage.database import Database


class TestPruneOldTurns(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())

    def tearDown(self):
        asyncio.run(self.db.close())

    def _insert(self, session: str, n: int) -> None:
        async def run():
            async with self.db.cursor() as c:
                for i in range(n):
                    await c.execute(
                        "INSERT INTO conversation_turns"
                        " (turn_number, role, content, session_id)"
                        " VALUES (?, 'user', ?, ?)", (i, f"{session}-msg{i}", session))
            await self.db.commit()
        asyncio.run(run())

    def _contents(self, session: str) -> list[str]:
        async def run():
            async with self.db.cursor() as c:
                await c.execute(
                    "SELECT content FROM conversation_turns"
                    " WHERE session_id = ? ORDER BY id", (session,))
                return [r[0] for r in await c.fetchall()]
        return asyncio.run(run())

    def test_prune_per_session_all_sessions(self):
        """不传 session_id：每个 session 各保留最新 keep_max 条。"""
        self._insert("a", 5)
        self._insert("b", 3)
        deleted = asyncio.run(self.db.prune_old_turns(keep_max=2))
        self.assertEqual(deleted, 4)  # a 删 3 条，b 删 1 条
        self.assertEqual(self._contents("a"), ["a-msg3", "a-msg4"])
        self.assertEqual(self._contents("b"), ["b-msg1", "b-msg2"])

    def test_prune_single_session_only(self):
        """传 session_id：只修剪该 session，其他 session 不动。"""
        self._insert("a", 5)
        self._insert("b", 5)
        deleted = asyncio.run(self.db.prune_old_turns(keep_max=1, session_id="a"))
        self.assertEqual(deleted, 4)
        self.assertEqual(self._contents("a"), ["a-msg4"])
        self.assertEqual(len(self._contents("b")), 5)

    def test_prune_under_limit_noop(self):
        """各 session 都不超限时零删除。"""
        self._insert("a", 2)
        self._insert("b", 2)
        deleted = asyncio.run(self.db.prune_old_turns(keep_max=5))
        self.assertEqual(deleted, 0)
        self.assertEqual(len(self._contents("a")), 2)
        self.assertEqual(len(self._contents("b")), 2)


if __name__ == "__main__":
    unittest.main()
