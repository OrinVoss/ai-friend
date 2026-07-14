"""Tests for storage/repository.py — fact CRUD + new #6 methods."""
import unittest
import asyncio

from storage.database import Database
from storage.repository import Repository
from models.memory import UserFact


class TestRepositoryFacts(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())
        self.repo = Repository(self.db)
        # Clean: delete all facts between tests
        async def _clean():
            async with self.db.cursor() as c:
                await c.execute("DELETE FROM user_facts")
        asyncio.run(_clean())

    def tearDown(self):
        asyncio.run(self.db.close())

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


class TestRepositoryRelationship(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())
        self.repo = Repository(self.db)
        self.repo.session_id = "sess_x"
        async def _clean():
            async with self.db.cursor() as c:
                await c.execute("DELETE FROM relationship_metrics")
                await c.execute("DELETE FROM relationship_snapshots")
        asyncio.run(_clean())

    def tearDown(self):
        asyncio.run(self.db.close())

    def test_ensure_relationship_defaults_seeds_four_dimensions(self):
        asyncio.run(self.repo.ensure_relationship_defaults())
        rels = asyncio.run(self.repo.get_all_relationships())
        self.assertEqual(set(rels.keys()), {"trust", "familiarity", "intimacy", "playfulness"})
        for v in rels.values():
            self.assertEqual(v, 0.3)

    def test_upsert_relationship_inserts_and_updates(self):
        asyncio.run(self.repo.upsert_relationship("trust", 0.55))
        rels = asyncio.run(self.repo.get_all_relationships())
        self.assertEqual(rels["trust"], 0.55)
        asyncio.run(self.repo.upsert_relationship("trust", 0.77))
        rels = asyncio.run(self.repo.get_all_relationships())
        self.assertEqual(rels["trust"], 0.77)

    def test_relationship_isolated_by_session(self):
        asyncio.run(self.repo.upsert_relationship("trust", 0.9))
        other = Repository(self.db)
        other.session_id = "sess_y"
        rels = asyncio.run(other.get_all_relationships())
        self.assertEqual(rels, {})

    def test_relationship_snapshot_created(self):
        asyncio.run(self.repo.upsert_relationship("familiarity", 0.6))
        history = asyncio.run(self.repo.get_relationship_history(days=7))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["dimension"], "familiarity")
        self.assertEqual(history[0]["value"], 0.6)


class TestRepositorySessionRole(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())
        self.repo = Repository(self.db)
        async def _clean():
            async with self.db.cursor() as c:
                await c.execute("DELETE FROM session_roles")
        asyncio.run(_clean())

    def tearDown(self):
        asyncio.run(self.db.close())

    def test_set_and_get_role_for_session(self):
        asyncio.run(self.repo.set_session_role("sess_1", "小星"))
        role = asyncio.run(self.repo.get_role_for_session("sess_1"))
        self.assertEqual(role, "小星")

    def test_get_role_for_session_missing(self):
        role = asyncio.run(self.repo.get_role_for_session("sess_unknown"))
        self.assertIsNone(role)

    def test_set_session_role_updates(self):
        asyncio.run(self.repo.set_session_role("sess_1", "小星"))
        asyncio.run(self.repo.set_session_role("sess_1", "default"))
        role = asyncio.run(self.repo.get_role_for_session("sess_1"))
        self.assertEqual(role, "default")


if __name__ == "__main__":
    unittest.main()
