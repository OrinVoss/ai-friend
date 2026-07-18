"""Tests for memory/consolidation.py — FactChecker integration (#6)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

from models.memory import UserFact


class TestConsolidationFactChecker(unittest.TestCase):
    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.ltm = MagicMock()
        self.llm = MagicMock()
        self.consolidator = MemoryConsolidator(self.ltm, self.llm)

    def test_fact_checker_initialized(self):
        """MemoryConsolidator should initialize FactChecker on creation."""
        self.assertIsNotNone(self.consolidator._fact_checker)

    def test_extract_facts_runs_contradiction_check(self):
        """After storing facts, consolidation should check for contradictions."""
        self.llm.return_value = (
            "FACT|preference|最爱食物|披萨|0.9|0.6\n"
            "FACT|preference|最爱颜色|蓝色|0.8|0.5\n"
            "FACT|identity|名字|小明|1.0|0.9"
        )
        # Existing facts returned by get_similar_facts
        old_fact = UserFact(
            id=42, category="preference", fact_key="最爱食物",
            fact_value="寿司", confidence=0.7,
        )
        self.ltm.get_similar_facts.return_value = [old_fact]

        # Run extraction
        self.consolidator._extract_facts("用户说：我最爱吃披萨，最喜欢蓝色，名字是小明")

        # #161: 3 条事实经一次批量 upsert 落库，不再逐条 store_fact
        self.ltm.store_fact.assert_not_called()
        self.ltm.store_facts_bulk.assert_called_once()
        bulk_facts = self.ltm.store_facts_bulk.call_args.args[0]
        self.assertEqual(len(bulk_facts), 3)

        # Should have called get_similar_facts for each new fact
        self.assertEqual(self.ltm.get_similar_facts.call_count, 3)

        # #161: 逐条矛盾检测（顺序不变）先于末尾批量落库
        call_names = [c[0] for c in self.ltm.mock_calls]
        self.assertLess(max(i for i, n in enumerate(call_names) if n == "get_similar_facts"),
                        call_names.index("store_facts_bulk"))

    def test_extract_facts_low_confidence_skipped(self):
        """Facts with confidence <= 0.3 should not be stored."""
        self.llm.return_value = "FACT|event|test|value|0.2|0.5"

        self.consolidator._extract_facts("some text")

        self.ltm.store_fact.assert_not_called()
        self.ltm.store_facts_bulk.assert_not_called()

    def test_extract_facts_contradiction_resolved(self):
        """When contradiction detected, old fact should be deactivated."""
        self.llm.return_value = "FACT|identity|名字|小红|0.9|0.8"

        old_fact = UserFact(
            id=99, category="identity", fact_key="名字",
            fact_value="小明", confidence=0.4,  # 0.4 * 0.4 = 0.16 < 0.2 → deactivated
        )
        self.ltm.get_similar_facts.return_value = [old_fact]

        self.consolidator._extract_facts("用户说我叫小红")

        # #161: 新事实经一次批量 upsert 落库
        self.ltm.store_fact.assert_not_called()
        self.ltm.store_facts_bulk.assert_called_once()
        # The resolve should have called deactivate_fact on ltm (sync wrapper)
        self.ltm.deactivate_fact.assert_called_once_with(99)

    def test_extract_facts_no_contradiction(self):
        """When new fact matches old, no deactivation needed."""
        self.llm.return_value = "FACT|preference|最爱食物|披萨|0.9|0.6"

        old_fact = UserFact(
            id=50, category="preference", fact_key="最爱食物",
            fact_value="披萨", confidence=0.8,
        )
        self.ltm.get_similar_facts.return_value = [old_fact]

        self.consolidator._extract_facts("用户最爱吃披萨")

        # Same value → no contradiction → no deactivation
        self.ltm.repo.deactivate_fact.assert_not_called()
        self.ltm.repo.update_fact_confidence.assert_not_called()

    # ── P1: error handling clears buffer ──

    def test_consolidate_partial_failure_clears_buffer(self):
        """P1: on any error, pending_buffer and seen_ids should be cleared."""
        from models.conversation import Turn
        t = Turn(turn_id=1, role="user", content="hello")
        self.consolidator._pending_buffer = [t]
        self.consolidator._seen_ids = {(1, "user")}

        # Simulate fact extraction failure
        self.consolidator._extract_facts = MagicMock(side_effect=Exception("LLM error"))
        self.consolidator.consolidate(MagicMock(), MagicMock())

        self.assertEqual(len(self.consolidator._pending_buffer), 0)
        self.assertEqual(len(self.consolidator._seen_ids), 0)

    def test_consolidate_full_success_clears_buffer(self):
        """On full success, buffer should also be cleared."""
        from models.conversation import Turn
        t = Turn(turn_id=1, role="user", content="hello")
        self.consolidator._pending_buffer = [t]
        self.consolidator._seen_ids = {(1, "user")}
        self.consolidator._extract_facts = MagicMock()
        self.consolidator._summarize_experience = MagicMock()
        self.consolidator._generate_reflection_l1 = MagicMock()
        self.consolidator._update_relationship = MagicMock()
        self.consolidator._prune = MagicMock()
        self.consolidator._embed_new_items = MagicMock()

        self.consolidator.consolidate(MagicMock(), MagicMock())

        self.assertEqual(len(self.consolidator._pending_buffer), 0)
        self.assertEqual(len(self.consolidator._seen_ids), 0)


class TestConsolidationRelationship(unittest.TestCase):
    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.ltm = MagicMock()
        self.llm = MagicMock()
        self.consolidator = MemoryConsolidator(self.ltm, self.llm)

    def test_update_relationship_updates_all_dimensions(self):
        """_update_relationship should update familiarity and at least one other dimension."""
        from models.conversation import Turn
        turn = Turn(turn_id=1, role="user", content="你好呀")
        self.consolidator._pending_buffer = [turn]
        self.consolidator.analyze_sentiment = MagicMock(return_value=(0.5, True, 0.6))
        self.ltm.get_relationship.return_value = {
            "familiarity": 0.3, "trust": 0.3, "intimacy": 0.3, "playfulness": 0.3,
        }

        personality = MagicMock()
        personality.emotion.dominant_emotion = "joyful"
        self.consolidator._update_relationship(personality)

        calls = {c.args[0]: c.args[1] for c in self.ltm.update_relationship.call_args_list}
        # familiarity always increases
        self.assertAlmostEqual(calls.get("familiarity"), 0.32, places=6)
        # joy emotion should increase playfulness
        self.assertAlmostEqual(calls.get("playfulness"), 0.32, places=6)
        # personal_sharing=True should increase intimacy
        self.assertAlmostEqual(calls.get("intimacy"), 0.33, places=6)
        # positive sentiment should increase trust
        self.assertAlmostEqual(calls.get("trust"), 0.325, places=6)

    def test_update_relationship_negative_emotion_erodes_trust(self):
        """Negative dominant emotion should decrease trust."""
        from models.conversation import Turn
        turn = Turn(turn_id=1, role="user", content="讨厌")
        self.consolidator._pending_buffer = [turn]
        self.consolidator.analyze_sentiment = MagicMock(return_value=(-0.3, False, 0.5))
        self.ltm.get_relationship.return_value = {
            "familiarity": 0.5, "trust": 0.5, "intimacy": 0.5, "playfulness": 0.5,
        }

        personality = MagicMock()
        personality.emotion.dominant_emotion = "angry"
        self.consolidator._update_relationship(personality)

        self.ltm.update_relationship.assert_any_call("trust", 0.48)
        self.ltm.update_relationship.assert_any_call("playfulness", 0.48)


class TestMemoryLifecycleIntegration(unittest.TestCase):
    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.ltm = MagicMock()
        self.llm = MagicMock()

    def test_lifecycle_disabled_by_default(self):
        """By default use_observation_fact is False and lifecycle manager is None."""
        from memory.consolidation import MemoryConsolidator
        consolidator = MemoryConsolidator(self.ltm, self.llm)
        self.assertIsNone(consolidator._lifecycle)

    def test_lifecycle_enabled_when_config_switches_on(self):
        """When config.use_observation_fact=True, lifecycle manager is created."""
        from memory.consolidation import MemoryConsolidator
        config = MagicMock()
        config.use_observation_fact = True
        consolidator = MemoryConsolidator(self.ltm, self.llm, config=config)
        self.assertIsNotNone(consolidator._lifecycle)

    def test_extract_facts_dual_writes_to_lifecycle(self):
        """When observation_ids provided, extracted facts are also promoted to FactV2."""
        from memory.consolidation import MemoryConsolidator
        from unittest.mock import patch
        config = MagicMock()
        config.use_observation_fact = True
        consolidator = MemoryConsolidator(self.ltm, self.llm, config=config)
        consolidator._lifecycle = MagicMock()
        consolidator._lifecycle.promote_fact = AsyncMock(return_value=MagicMock())

        self.llm.return_value = "FACT|preference|饮品|咖啡|0.8|0.7|user_fact"
        self.ltm.get_similar_facts.return_value = []

        with patch("memory.consolidation.run_async", lambda coro: coro.send(None)):
            consolidator._extract_facts("用户说喜欢咖啡", observation_ids=[1])

        consolidator._lifecycle.promote_fact.assert_awaited_once()
        args = consolidator._lifecycle.promote_fact.call_args.kwargs
        self.assertEqual(args["category"], "preference")
        self.assertEqual(args["key"], "饮品")
        self.assertEqual(args["value"], "咖啡")
        self.assertEqual(args["observation_ids"], [1])


class TestReembedStaleVersions(unittest.TestCase):
    """_embed_new_items must pick up stale-version rows and re-stamp them
    with the current EMBEDDING_VERSION (rolling rebuild)."""

    def test_stale_row_reembedded(self):
        import asyncio
        import numpy as np
        from memory.consolidation import MemoryConsolidator
        from memory.embeddings import EmbeddingEngine
        from memory.long_term import LongTermMemory
        from models.memory import EMBEDDING_VERSION
        from storage.database import Database
        from storage.repository import Repository

        db = Database(":memory:")
        asyncio.run(db.open())
        repo = Repository(db)
        old_blob = EmbeddingEngine.vec_to_bytes(np.ones(8, dtype=np.float32))

        async def _insert():
            async with db.cursor() as c:
                await c.execute(
                    "INSERT INTO user_facts (category, fact_key, fact_value, confidence,"
                    " embedding, embedding_version, session_id) VALUES (?,?,?,?,?,?,?)",
                    ("preference", "颜色", "蓝", 0.9, old_blob,
                     EMBEDDING_VERSION + 99, "default"))
                await db.commit()
        asyncio.run(_insert())

        embed = MagicMock()
        embed.health_check.return_value = True
        embed.encode.return_value = np.array(
            [np.ones(8, dtype=np.float32) / 3.0], dtype=np.float32)
        ltm = LongTermMemory(repo)
        consolidator = MemoryConsolidator(ltm, MagicMock(), embedding_engine=embed)
        # Production calls this from sync context (no running loop); calling
        # it from inside a coroutine would bridge through the executor.
        consolidator._embed_new_items()

        facts = asyncio.run(repo.get_active_facts(limit=10))
        asyncio.run(db.close())

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].embedding_version, EMBEDDING_VERSION)
        embed.encode.assert_called_once()


class TestEmbedNewItemsCoverage(unittest.TestCase):
    """H-08/#285: _embed_new_items 覆盖 facts_v2 / observations，
    且只处理本 session 的行。"""

    def test_covers_facts_v2_and_observations_session_scoped(self):
        import asyncio
        import numpy as np
        from memory.consolidation import MemoryConsolidator
        from memory.long_term import LongTermMemory
        from models.memory import EMBEDDING_VERSION
        from storage.database import Database
        from storage.repository import Repository

        db = Database(":memory:")
        asyncio.run(db.open())
        repo = Repository(db)

        async def _insert():
            async with db.cursor() as c:
                # 本 session：facts_v2 / observations 各一行，待嵌入
                await c.execute(
                    "INSERT INTO facts_v2 (category, fact_key, fact_value, session_id)"
                    " VALUES ('preference', '饮品', '咖啡', 'default')")
                await c.execute(
                    "INSERT INTO observations (content, session_id)"
                    " VALUES ('用户喜欢咖啡', 'default')")
                # 其他 session：同类行，不应被触碰
                await c.execute(
                    "INSERT INTO facts_v2 (category, fact_key, fact_value, session_id)"
                    " VALUES ('preference', '饮品', '茶', 'sess_other')")
                await c.execute(
                    "INSERT INTO observations (content, session_id)"
                    " VALUES ('别的会话', 'sess_other')")
                await db.commit()
        asyncio.run(_insert())

        embed = MagicMock()
        embed.health_check.return_value = True
        embed.encode.side_effect = lambda texts: np.array(
            [np.ones(8, dtype=np.float32) / 3.0] * len(texts), dtype=np.float32)
        ltm = LongTermMemory(repo)
        consolidator = MemoryConsolidator(ltm, MagicMock(), embedding_engine=embed)
        # 与生产一致：从同步上下文调用
        consolidator._embed_new_items()

        async def _fetch():
            out = {}
            async with db.cursor() as c:
                for table in ("facts_v2", "observations"):
                    await c.execute(
                        f"SELECT session_id, embedding, embedding_version FROM {table}")
                    out[table] = await c.fetchall()
            return out
        rows = asyncio.run(_fetch())
        asyncio.run(db.close())

        for table in ("facts_v2", "observations"):
            mine = [r for r in rows[table] if r["session_id"] == "default"]
            theirs = [r for r in rows[table] if r["session_id"] == "sess_other"]
            self.assertEqual(len(mine), 1)
            self.assertIsNotNone(mine[0]["embedding"])
            self.assertEqual(mine[0]["embedding_version"], EMBEDDING_VERSION)
            # 其他 session 的行保持未嵌入
            self.assertEqual(len(theirs), 1)
            self.assertIsNone(theirs[0]["embedding"])
            self.assertEqual(theirs[0]["embedding_version"], 0)


class TestCareClueExtraction(unittest.TestCase):
    """内驱状态二期：consolidation 线索写入 + 对照解决（inner-drive-state.md §5）。"""

    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.ltm = MagicMock()
        self.llm = MagicMock()
        self.state = MagicMock()
        self.consolidator = MemoryConsolidator(
            self.ltm, self.llm, inner_drive_state=self.state)

    def test_clues_written_with_consolidation_source(self):
        self.llm.return_value = (
            '{"clues": [{"content": "用户明天面试，晚上问结果", '
            '"type": "plan", "expires_at": "2026-07-19"}]}'
        )
        self.consolidator._extract_care_clues("用户：我明天面试")
        self.state.apply_updates.assert_called_once()
        kwargs = self.state.apply_updates.call_args.kwargs
        self.assertEqual(kwargs["source"], "consolidation")
        self.assertEqual(kwargs["add"][0]["type"], "plan")

    def test_empty_clues_no_write(self):
        self.llm.return_value = '{"clues": []}'
        self.consolidator._extract_care_clues("用户：今天天气不错")
        self.state.apply_updates.assert_not_called()

    def test_invalid_json_silently_skipped(self):
        self.llm.return_value = "这不是 JSON"
        self.consolidator._extract_care_clues("用户：随便聊聊")
        self.state.apply_updates.assert_not_called()

    def test_clue_without_content_filtered(self):
        self.llm.return_value = (
            '{"clues": [{"type": "care"}, {"content": "有效线索"}]}'
        )
        self.consolidator._extract_care_clues("用户：说点事")
        kwargs = self.state.apply_updates.call_args.kwargs
        self.assertEqual(len(kwargs["add"]), 1)
        self.assertEqual(kwargs["add"][0]["content"], "有效线索")

    def test_no_state_noop(self):
        from memory.consolidation import MemoryConsolidator
        c = MemoryConsolidator(self.ltm, self.llm)
        self.assertIsNone(c._inner_drive_state)


if __name__ == "__main__":
    unittest.main()
