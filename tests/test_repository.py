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
                await c.execute("DELETE FROM facts_v2")
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

    def test_upsert_revives_soft_deleted_fact(self):
        """#217: 矛盾软删 → 用户重述 → upsert 命中冲突后复活且可检索。"""
        fid = asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.9))
        # FactChecker 矛盾解决 → 软删（is_active=0, composite_score=0）
        asyncio.run(self.repo.deactivate_fact(fid))
        self.assertEqual(asyncio.run(self.repo.get_active_facts(limit=10)), [])
        self.assertEqual(asyncio.run(self.repo.search_facts("披萨", limit=10)), [])

        # 用户重新陈述同名事实 → upsert 冲突更新 → 复活并恢复可见
        asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.9))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertTrue(facts[0].is_active)
        self.assertEqual(facts[0].fact_value, "披萨")
        self.assertGreater(facts[0].composite_score, 0)
        results = asyncio.run(self.repo.search_facts("披萨", limit=10))
        self.assertEqual(len(results), 1)

    def test_upsert_revives_with_new_value(self):
        """#217: 软删后以新值重述 → 复活且按 confidence 规则更新 value。"""
        fid = asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.5))
        asyncio.run(self.repo.deactivate_fact(fid))

        asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "寿司", confidence=0.9))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].fact_value, "寿司")
        self.assertTrue(facts[0].is_active)

    def test_get_similar_facts_session_isolated(self):
        """Facts from other sessions must not leak into similarity results."""
        asyncio.run(self.repo.upsert_fact("preference", "最爱颜色", "蓝", confidence=0.9))
        other = Repository(self.db)
        other.session_id = "sess_other"
        asyncio.run(other.upsert_fact("preference", "最爱食物", "披萨", confidence=0.8))

        similar = asyncio.run(self.repo.get_similar_facts("preference", "最爱", limit=5))
        self.assertEqual(len(similar), 1)
        self.assertEqual(similar[0].fact_key, "最爱颜色")

    def test_deactivate_fact_other_session_noop(self):
        """deactivate_fact with another session's id must not take effect."""
        other = Repository(self.db)
        other.session_id = "sess_other"
        fid = asyncio.run(other.upsert_fact("event", "他的事", "x", confidence=0.5))
        asyncio.run(self.repo.deactivate_fact(fid))

        facts = asyncio.run(other.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)

    def test_by_id_writes_other_session_noop(self):
        """update_fact_score / increment_fact_recall / update_fact_confidence
        with another session's id must not take effect."""
        other = Repository(self.db)
        other.session_id = "sess_other"
        fid = asyncio.run(other.upsert_fact("preference", "颜色", "蓝", confidence=0.9))

        asyncio.run(self.repo.update_fact_score(fid, 0.01))
        asyncio.run(self.repo.increment_fact_recall(fid))
        asyncio.run(self.repo.update_fact_confidence(fid, 0.1))

        facts = asyncio.run(other.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].confidence, 0.9)          # unchanged
        # facts_v2 首次写入即 verification_count=1（promote 即首次验证），
        # 跨 session 的 increment_fact_recall 不得再 +1
        self.assertEqual(facts[0].recall_count, 1)          # unchanged
        self.assertGreater(facts[0].composite_score, 0.5)   # unchanged

    def test_facts_v2_writes_other_session_noop(self):
        """update_fact_v2_status / verify_fact_v2 / decay_fact_v2 with another
        session's id must not take effect."""
        other = Repository(self.db)
        other.session_id = "sess_other"
        fid = asyncio.run(other.upsert_fact_v2(
            "preference", "食物", "披萨", confidence=0.8, freshness=1.0))

        asyncio.run(self.repo.update_fact_v2_status(fid, "contradicted"))
        asyncio.run(self.repo.verify_fact_v2(fid))
        asyncio.run(self.repo.decay_fact_v2(fid, 0.01))

        fact = asyncio.run(other.get_fact_v2_by_id(fid))
        self.assertEqual(fact.status, "active")             # unchanged
        self.assertEqual(fact.verification_count, 1)        # only upsert's own
        self.assertAlmostEqual(fact.confidence, 0.8)        # unchanged
        self.assertAlmostEqual(fact.freshness, 1.0)         # unchanged

    def test_embedding_version_stamped(self):
        """Writes through upsert_fact must stamp the current EMBEDDING_VERSION."""
        from models.memory import EMBEDDING_VERSION
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        blob = EmbeddingEngine.vec_to_bytes(np.ones(8, dtype=np.float32))
        asyncio.run(self.repo.upsert_fact(
            "preference", "颜色", "蓝", confidence=0.9, embedding=blob))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(facts[0].embedding_version, EMBEDDING_VERSION)


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


class TestBulkUpdateEmbeddings(unittest.TestCase):
    """H-08/H-02: bulk_update_embeddings 的 session 隔离与显式 commit。"""

    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())
        self.repo = Repository(self.db)
        async def _clean():
            async with self.db.cursor() as c:
                await c.execute("DELETE FROM facts_v2")
        asyncio.run(_clean())

    def tearDown(self):
        asyncio.run(self.db.close())

    @staticmethod
    def _blob():
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        return EmbeddingEngine.vec_to_bytes(np.ones(8, dtype=np.float32))

    def test_bulk_update_scoped_to_session(self):
        """H-08: 只更新本 session 的行，其他 session 的同 id 行不动。"""
        from models.memory import EMBEDDING_VERSION
        blob = self._blob()

        other = Repository(self.db)
        other.session_id = "sess_other"
        other_fid = asyncio.run(other.upsert_fact(
            "preference", "颜色", "蓝", confidence=0.9))

        # 本 session 拿着 other session 的行 id 回写 → 必须无效
        asyncio.run(self.repo.bulk_update_embeddings("facts_v2", [(other_fid, blob)]))
        facts = asyncio.run(other.get_active_facts(limit=10))
        self.assertIsNone(facts[0].embedding)
        self.assertEqual(facts[0].embedding_version, 0)

        # other session 自己回写 → 生效
        asyncio.run(other.bulk_update_embeddings("facts_v2", [(other_fid, blob)]))
        facts = asyncio.run(other.get_active_facts(limit=10))
        self.assertIsNotNone(facts[0].embedding)
        self.assertEqual(facts[0].embedding_version, EMBEDDING_VERSION)

    def test_bulk_update_commits(self):
        """H-02: bulk_update_embeddings 必须显式 commit。"""
        from unittest.mock import AsyncMock
        fid = asyncio.run(self.repo.upsert_fact(
            "preference", "食物", "披萨", confidence=0.9))

        spy = AsyncMock(wraps=self.db.commit)
        self.db.commit = spy
        asyncio.run(self.repo.bulk_update_embeddings("facts_v2", [(fid, self._blob())]))
        spy.assert_awaited()

    def test_bulk_update_empty_noop(self):
        """空 updates 直接返回，不触碰连接。"""
        from unittest.mock import AsyncMock
        spy = AsyncMock(wraps=self.db.commit)
        self.db.commit = spy
        asyncio.run(self.repo.bulk_update_embeddings("facts_v2", []))
        spy.assert_not_awaited()


class TestStoreFactsBulk(unittest.TestCase):
    """#161: store_facts_bulk 单事务批量 upsert。"""

    def setUp(self):
        self.db = Database(":memory:")
        asyncio.run(self.db.open())
        self.repo = Repository(self.db)
        async def _clean():
            async with self.db.cursor() as c:
                await c.execute("DELETE FROM facts_v2")
        asyncio.run(_clean())

    def tearDown(self):
        asyncio.run(self.db.close())

    def test_bulk_matches_sequential_upserts(self):
        """批量路径与逐条 upsert 路径落库结果一致（含冲突更新与复活语义）。"""
        facts = [
            {"category": "preference", "key": "最爱食物", "value": "披萨",
             "confidence": 0.9, "importance": 0.7},
            {"category": "preference", "key": "最爱颜色", "value": "蓝",
             "confidence": 0.8, "importance": 0.5},
            # 同名冲突、更高 confidence → 更新 value
            {"category": "preference", "key": "最爱食物", "value": "寿司",
             "confidence": 0.95, "importance": 0.6},
            # 同名冲突、更低 confidence → 保留旧 value，recall_count 仍 +1
            {"category": "preference", "key": "最爱颜色", "value": "红",
             "confidence": 0.4, "importance": 0.4},
        ]

        other_db = Database(":memory:")
        asyncio.run(other_db.open())
        seq_repo = Repository(other_db)
        try:
            for f in facts:
                asyncio.run(seq_repo.upsert_fact(
                    f["category"], f["key"], f["value"],
                    confidence=f["confidence"], importance=f["importance"]))
            asyncio.run(self.repo.store_facts_bulk(facts))

            bulk_rows = asyncio.run(self.repo.get_active_facts(limit=10))
            seq_rows = asyncio.run(seq_repo.get_active_facts(limit=10))
        finally:
            asyncio.run(other_db.close())

        self.assertEqual(len(bulk_rows), len(seq_rows))
        for b, s in zip(bulk_rows, seq_rows):
            self.assertEqual((b.category, b.fact_key, b.fact_value),
                             (s.category, s.fact_key, s.fact_value))
            self.assertAlmostEqual(b.confidence, s.confidence)
            self.assertAlmostEqual(b.importance, s.importance)
            self.assertEqual(b.recall_count, s.recall_count)
            self.assertAlmostEqual(b.composite_score, s.composite_score)
            self.assertEqual(b.is_active, s.is_active)

    def test_bulk_revives_soft_deleted_fact(self):
        """#161/#217: 批量 upsert 同样复活被软删的同名事实。"""
        fid = asyncio.run(self.repo.upsert_fact(
            "preference", "最爱食物", "披萨", confidence=0.5))
        asyncio.run(self.repo.deactivate_fact(fid))

        asyncio.run(self.repo.store_facts_bulk([
            {"category": "preference", "key": "最爱食物", "value": "披萨",
             "confidence": 0.9},
        ]))
        facts = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts), 1)
        self.assertTrue(facts[0].is_active)
        self.assertGreater(facts[0].composite_score, 0)

    def test_bulk_single_commit(self):
        """N 条事实批量 upsert 只 commit 一次（逐条路径为 N 次）。"""
        from unittest.mock import AsyncMock
        facts = [
            {"category": "preference", "key": f"key{i}", "value": f"v{i}",
             "confidence": 0.8}
            for i in range(3)
        ]
        spy = AsyncMock(wraps=self.db.commit)
        self.db.commit = spy
        asyncio.run(self.repo.store_facts_bulk(facts))
        spy.assert_awaited_once()

        rows = asyncio.run(self.repo.get_active_facts(limit=10))
        self.assertEqual(len(rows), 3)

    def test_bulk_empty_noop(self):
        """空列表直接返回，不触碰连接。"""
        from unittest.mock import AsyncMock
        spy = AsyncMock(wraps=self.db.commit)
        self.db.commit = spy
        self.assertEqual(asyncio.run(self.repo.store_facts_bulk([])), 0)
        spy.assert_not_awaited()


class TestSessionFilteredWrites(unittest.TestCase):
    """M-01/M-02: 按 id 的 UPDATE 必须带 session 过滤。"""

    def _spy_repo(self):
        from unittest.mock import AsyncMock, MagicMock
        db = MagicMock()
        db.commit = AsyncMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        db.cursor.return_value.__aenter__.return_value = cursor
        repo = Repository(db)
        repo.session_id = "sess-x"
        return repo, cursor

    def test_update_experience_score_sql_has_session_filter(self):
        repo, cursor = self._spy_repo()
        asyncio.run(repo.update_experience_score(7, 0.9))
        sql, params = cursor.execute.call_args[0]
        self.assertIn("AND session_id = ?", sql)
        self.assertEqual(params, (0.9, 7, "sess-x"))

    def test_archive_observation_sql_has_session_filter(self):
        repo, cursor = self._spy_repo()
        asyncio.run(repo.archive_observation(3))
        sql, params = cursor.execute.call_args[0]
        self.assertIn("AND session_id = ?", sql)
        self.assertEqual(params, (3, "sess-x"))

    def test_update_experience_score_other_session_noop(self):
        """行为验证：用别的 session 的 exp_id 更新不生效。"""
        db = Database(":memory:")
        asyncio.run(db.open())
        try:
            repo_a = Repository(db)
            repo_a.session_id = "sess-a"
            repo_b = Repository(db)
            repo_b.session_id = "sess-b"
            eid = asyncio.run(repo_b.insert_experience("他的经历", "neutral", 0.5, []))
            asyncio.run(repo_a.update_experience_score(eid, 0.01))
            rows = asyncio.run(repo_b.search_experiences())
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0].composite_score, 0.01)
        finally:
            asyncio.run(db.close())

    def test_archive_observation_other_session_noop(self):
        """行为验证：用别的 session 的 obs_id 归档不生效。"""
        db = Database(":memory:")
        asyncio.run(db.open())
        try:
            repo_a = Repository(db)
            repo_a.session_id = "sess-a"
            repo_b = Repository(db)
            repo_b.session_id = "sess-b"
            oid = asyncio.run(repo_b.insert_observation("他的观察"))
            asyncio.run(repo_a.archive_observation(oid))
            rows = asyncio.run(repo_b.get_recent_observations())
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].is_archived)
        finally:
            asyncio.run(db.close())


if __name__ == "__main__":
    unittest.main()
