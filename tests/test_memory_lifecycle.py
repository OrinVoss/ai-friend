"""Tests for memory/lifecycle.py — Layer 1 Memory lifecycle (#ML-001)."""
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from memory.lifecycle import MemoryLifecycleManager
from models.memory import FactV2, Observation


class _AsyncIter:
    """Tiny helper to let `async with cursor() as c` work in mocks."""
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, *args):
        return None


class TestMemoryLifecycleManager(unittest.TestCase):
    def setUp(self):
        self.ltm = MagicMock()
        self.ltm.repo = MagicMock()
        self.ltm.repo.db.cursor.return_value = _AsyncIter(MagicMock())
        self.ltm.repo.db.commit = AsyncMock()
        self.ltm.repo.session_id = "test-session"
        self.manager = MemoryLifecycleManager(self.ltm)

    def test_observe_creates_observation(self):
        """observe() should insert an observation and return an Observation model."""
        self.ltm.repo.insert_observation = AsyncMock(return_value=42)

        result = self._run(self.manager.observe(
            content="用户说喜欢咖啡",
            source_turn=7,
            episode_turn_start=5,
            episode_turn_end=7,
        ))

        self.assertIsInstance(result, Observation)
        self.assertEqual(result.id, 42)
        self.assertEqual(result.content, "用户说喜欢咖啡")
        self.assertEqual(result.source_turn, 7)
        self.ltm.repo.insert_observation.assert_awaited_once()

    def test_find_similar_observations_uses_keyword_search(self):
        """find_similar_observations should delegate to repo.search_observations."""
        expected = [Observation(id=1, content="obs")]
        self.ltm.repo.search_observations = AsyncMock(return_value=expected)

        result = self._run(self.manager.find_similar_observations("喜欢 咖啡", limit=3))

        self.assertEqual(result, expected)
        self.ltm.repo.search_observations.assert_awaited_once_with("喜欢", 3)

    def test_promote_fact_creates_fact_v2(self):
        """promote_fact should upsert a FactV2 and return the model."""
        self.ltm.repo.upsert_fact_v2 = AsyncMock(return_value=99)

        result = self._run(self.manager.promote_fact(
            observation_ids=[1, 2],
            category="preference",
            key="饮品",
            value="咖啡",
            confidence=0.8,
            importance=0.7,
        ))

        self.assertIsInstance(result, FactV2)
        self.assertEqual(result.id, 99)
        self.assertEqual(result.fact_key, "饮品")
        self.assertEqual(result.source_observation_ids, [1, 2])
        self.ltm.repo.upsert_fact_v2.assert_awaited_once()

    def test_verify_fact_increments_count(self):
        """verify_fact should call repo.verify_fact_v2."""
        self.ltm.repo.verify_fact_v2 = AsyncMock()

        self._run(self.manager.verify_fact(10))

        self.ltm.repo.verify_fact_v2.assert_awaited_once_with(10)

    def test_contradict_fact_updates_status(self):
        """contradict_fact should mark the fact as contradicted."""
        self.ltm.repo.update_fact_v2_status = AsyncMock()

        self._run(self.manager.contradict_fact(10, "用户更正"))

        self.ltm.repo.update_fact_v2_status.assert_awaited_once_with(10, "contradicted")

    def test_decay_reduces_freshness(self):
        """decay should lower freshness of active facts."""
        fact = FactV2(
            id=1, category="preference", fact_key="饮品", fact_value="咖啡",
            freshness=1.0, confidence=0.8, last_verified_at=datetime.utcnow().isoformat(),
        )
        self.ltm.repo.get_active_facts_v2 = AsyncMock(return_value=[fact])
        self.ltm.repo.decay_fact_v2 = AsyncMock()

        self._run(self.manager.decay())

        self.ltm.repo.decay_fact_v2.assert_awaited_once()
        args = self.ltm.repo.decay_fact_v2.call_args.args
        self.assertEqual(args[0], 1)
        self.assertLess(args[1], 1.0)  # decay factor < 1

    def test_garbage_collect_runs_decay_merge_archive(self):
        """garbage_collect should call decay, merge and archive."""
        self.ltm.repo.get_active_facts_v2 = AsyncMock(return_value=[])
        self.ltm.repo.decay_fact_v2 = AsyncMock()
        # Layer 1 二期（2026-07-20）：GC 纳入 expires_at 过期的 insight
        self.ltm.repo.expire_due_insights = AsyncMock(return_value=0)
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        self.ltm.repo.db.cursor.return_value = _AsyncIter(cursor)

        self._run(self.manager.garbage_collect())

        self.ltm.repo.get_active_facts_v2.assert_awaited_once()
        self.ltm.repo.expire_due_insights.assert_awaited_once()

    def test_create_insight_stores_and_returns_model(self):
        """Layer 1 二期：create_insight 落 insights_v2 并返回 InsightV2。"""
        from models.memory import InsightV2
        self.ltm.repo.insert_insight = AsyncMock(return_value=7)

        result = self._run(self.manager.create_insight(
            hypothesis="用户可能偏好独处",
            evidence_fact_ids=[3, 7],
            insight_type="pattern",
            confidence=0.6,
            needs_more_evidence=True,
        ))

        self.assertIsInstance(result, InsightV2)
        self.assertEqual(result.id, 7)
        self.assertEqual(result.hypothesis, "用户可能偏好独处")
        self.assertEqual(result.evidence_fact_ids, [3, 7])
        self.ltm.repo.insert_insight.assert_awaited_once()
        kwargs = self.ltm.repo.insert_insight.call_args.kwargs
        self.assertEqual(kwargs["hypothesis"], "用户可能偏好独处")
        self.assertEqual(kwargs["evidence_fact_ids"], [3, 7])
        self.assertEqual(kwargs["confidence"], 0.6)

    def test_verify_and_expire_insight_delegate(self):
        """verify_insight / expire_insight 委托 repo 对应方法。"""
        self.ltm.repo.verify_insight = AsyncMock()
        self.ltm.repo.expire_insight = AsyncMock()

        self._run(self.manager.verify_insight(11))
        self._run(self.manager.expire_insight(12))

        self.ltm.repo.verify_insight.assert_awaited_once_with(11)
        self.ltm.repo.expire_insight.assert_awaited_once_with(12)

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)


class TestContradictionPropagation(unittest.TestCase):
    """矛盾向上传播（memory-agent-verification.md 3.7）：Fact 被推翻时，
    引用它的 Insight 连带标记可疑。"""

    def setUp(self):
        self.ltm = MagicMock()
        self.ltm.repo = MagicMock()
        self.ltm.repo.session_id = "test-session"
        self.ltm.repo.update_fact_v2_status = AsyncMock()
        self.ltm.repo.mark_insight_suspect = AsyncMock()
        self.manager = MemoryLifecycleManager(self.ltm)

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_citing_insights_marked_suspect(self):
        from models.memory import InsightV2
        citing = InsightV2(id=7, hypothesis="用户可能只吃意式",
                           evidence_fact_ids=[3, 9], confidence=0.7)
        unrelated = InsightV2(id=8, hypothesis="用户可能早睡",
                              evidence_fact_ids=[42], confidence=0.6)
        self.ltm.repo.get_active_insights = AsyncMock(
            return_value=[citing, unrelated])

        self._run(self.manager.contradict_fact(3, "user correction"))

        self.ltm.repo.update_fact_v2_status.assert_awaited_once_with(
            3, "contradicted")
        # 只有引用 fact 3 的 insight 7 被标记
        self.ltm.repo.mark_insight_suspect.assert_awaited_once_with(7)

    def test_no_citing_insights_noop(self):
        self.ltm.repo.get_active_insights = AsyncMock(return_value=[])
        self._run(self.manager.contradict_fact(3))
        self.ltm.repo.mark_insight_suspect.assert_not_called()

    def test_propagation_failure_does_not_break_contradict(self):
        self.ltm.repo.get_active_insights = AsyncMock(
            side_effect=RuntimeError("db down"))
        # 不抛异常——标记 fact contradicted 的主流程必须完成
        self._run(self.manager.contradict_fact(3))
        self.ltm.repo.update_fact_v2_status.assert_awaited_once_with(
            3, "contradicted")


class TestMergeDuplicates(unittest.TestCase):
    """A5（2026-07-21）：语义近重复合并（并查集 + 保留最强 + 计数并入）。"""

    def setUp(self):
        self.ltm = MagicMock()
        self.ltm.repo = MagicMock()
        self.ltm.repo.session_id = "test-session"
        self.ltm.repo.merge_facts_v2 = AsyncMock()

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def _fact(self, fid, key, value, cat="preference", vc=1, conf=0.8):
        return FactV2(id=fid, category=cat, fact_key=key, fact_value=value,
                      confidence=conf, status="active", verification_count=vc)

    def _manager_with_vecs(self, vec_map):
        """vec_map: {text: vector}，按 'key value' 文本取向量。"""
        import numpy as np

        def _unit(v):
            a = np.array(v, dtype=np.float32)
            return a / np.linalg.norm(a)
        embed = MagicMock()
        embed.encode.side_effect = lambda texts: np.stack(
            [_unit(vec_map[t]) for t in texts])
        embed.health_check.return_value = True
        return MemoryLifecycleManager(self.ltm, embedding_engine=embed)

    def test_near_dup_merged_into_strongest(self):
        f1 = self._fact(1, "最爱食物", "披萨", vc=3, conf=0.9)
        f2 = self._fact(2, "喜欢的食物", "披萨", vc=1, conf=0.8)
        self.ltm.repo.get_active_facts_v2 = AsyncMock(return_value=[f1, f2])
        same = [1, 0, 0, 0]
        mgr = self._manager_with_vecs({
            "最爱食物 披萨": same, "喜欢的食物 披萨": same,
        })
        self._run(mgr.merge_duplicates())
        # f1 更强（vc=3）→ keeper；f2 被吸收，计数 +1
        self.ltm.repo.merge_facts_v2.assert_awaited_once_with(1, [2], 1)

    def test_distinct_facts_not_merged(self):
        f1 = self._fact(1, "最爱食物", "披萨")
        f2 = self._fact(2, "最爱颜色", "蓝色")
        self.ltm.repo.get_active_facts_v2 = AsyncMock(return_value=[f1, f2])
        mgr = self._manager_with_vecs({
            "最爱食物 披萨": [1, 0, 0, 0], "最爱颜色 蓝色": [0, 1, 0, 0],
        })
        self._run(mgr.merge_duplicates())
        self.ltm.repo.merge_facts_v2.assert_not_called()

    def test_no_embed_skip(self):
        mgr = MemoryLifecycleManager(self.ltm)  # 无 embedding_engine
        self.ltm.repo.get_active_facts_v2 = AsyncMock(
            return_value=[self._fact(1, "a", "b")])
        self._run(mgr.merge_duplicates())
        self.ltm.repo.get_active_facts_v2.assert_not_called()
        self.ltm.repo.merge_facts_v2.assert_not_called()

    def test_cluster_of_three_single_keeper(self):
        f1 = self._fact(1, "a", "披萨", vc=1)
        f2 = self._fact(2, "b", "披萨", vc=5, conf=0.9)
        f3 = self._fact(3, "c", "披萨", vc=2)
        self.ltm.repo.get_active_facts_v2 = AsyncMock(
            return_value=[f1, f2, f3])
        same = [1, 0, 0, 0]
        mgr = self._manager_with_vecs({
            "a 披萨": same, "b 披萨": same, "c 披萨": same,
        })
        self._run(mgr.merge_duplicates())
        # f2 vc=5 最强 → keeper；f1/f3 被吸收，计数 1+2=3
        self.ltm.repo.merge_facts_v2.assert_awaited_once_with(2, [1, 3], 3)


if __name__ == "__main__":
    unittest.main()
