"""Tests for storage/repository.py — fact CRUD + new #6 methods."""
import unittest
import asyncio

from storage.database import Database
from storage.repository import Repository
from models.memory import UserFact


class TestRepositoryFacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(":memory:")
        asyncio.run(cls.db.open())

    def setUp(self):
        self.repo = Repository(self.db)
        # Clean: delete all facts between tests
        async def _clean():
            async with self.db.cursor() as c:
                await c.execute("DELETE FROM user_facts")
        asyncio.run(_clean())

    def test_upsert_fact_new(self):
        """Insert a new fact."""
        fid = asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.9, importance=0.7,
        ))
        self.assertIsNotNone(fid)
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].fact_key, "最爱食物")
        self.assertEqual(facts[0].fact_value, "披萨")
        self.assertEqual(facts[0].confidence, 0.9)

    def test_upsert_fact_update_higher_confidence(self):
        """Higher confidence upsert should update value."""
        asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.7,
        ))
        asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "寿司", confidence=0.9,
        ))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].fact_value, "寿司")
        self.assertEqual(facts[0].confidence, 0.9)

    def test_upsert_fact_update_lower_confidence_keeps_old_value(self):
        """Lower confidence upsert should NOT overwrite value."""
        asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.9,
        ))
        asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "汉堡", confidence=0.5,
        ))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].fact_value, "披萨")
        self.assertEqual(facts[0].confidence, 0.9)

    def test_deactivate_fact(self):
        """Deactivate should set is_active=0 and composite_score=0."""
        fid = asyncio.run(self.repo.upsert_fact(
            "event", "测试事件", "发生了", confidence=0.5,
        ))
        asyncio.run(self.repo.deactivate_fact(fid))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 0)

    def test_update_fact_confidence_lower(self):
        """update_fact_confidence should allow lowering confidence."""
        fid = asyncio.run(self.repo.upsert_fact(
            "identity", "名字", "小明", confidence=0.9,
        ))
        asyncio.run(self.repo.update_fact_confidence(fid, 0.3))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].confidence, 0.3)

    def test_get_similar_facts_same_category(self):
        """get_similar_facts should find facts with same category."""
        asyncio.run(self.repo.upsert_fact("preference", "最爱颜色", "蓝", confidence=0.9))
        asyncio.run(self.repo.upsert_fact("preference", "最爱食物", "披萨", confidence=0.8))
        asyncio.run(self.repo.upsert_fact("identity", "名字", "小明", confidence=1.0))

        similar = asyncio.run(self.repo.get_similar_facts("preference", "最爱", limit=5))
        self.assertGreaterEqual(len(similar), 2)
        categories = {f.category for f in similar}
        self.assertIn("preference", categories)

    def test_get_similar_facts_key_match(self):
        """get_similar_facts should match on key LIKE."""
        asyncio.run(self.repo.upsert_fact("preference", "最爱颜色", "蓝", confidence=0.9))
        asyncio.run(self.repo.upsert_fact("preference", "最爱食物", "披萨", confidence=0.8))

        similar = asyncio.run(self.repo.get_similar_facts("preference", "最爱", limit=5))
        self.assertEqual(len(similar), 2)

    def test_search_facts_filters_low_confidence(self):
        """Facts with confidence < 0.2 should not appear in search."""
        asyncio.run(self.repo.upsert_fact("event", "低置信度事件", "x", confidence=0.1))
        asyncio.run(self.repo.upsert_fact("event", "正常事件", "y", confidence=0.8))

        results = asyncio.run(self.repo.search_facts("事件", limit=10))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].fact_key, "正常事件")

    def test_get_active_facts_filters_low_confidence(self):
        """get_active_facts should exclude confidence < 0.2."""
        asyncio.run(self.repo.upsert_fact("routine", "低自信", "x", confidence=0.15))
        asyncio.run(self.repo.upsert_fact("routine", "高自信", "y", confidence=0.9))

        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].fact_key, "高自信")

    def test_deactivate_fact_excluded_from_search(self):
        """Deactivated facts should be excluded from search."""
        fid = asyncio.run(self.repo.upsert_fact("event", "待删除", "x", confidence=0.5))
        asyncio.run(self.repo.deactivate_fact(fid))

        results = asyncio.run(self.repo.search_facts("待删除", limit=10))
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
