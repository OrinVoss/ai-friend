"""Tests for memory/memory_agent.py — deterministic memory reasoning (P0+P1)."""
import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from memory.embeddings import EmbeddingEngine
from memory.memory_agent import (MemoryAgent, MemoryEvidence,
                                 check_freshness, check_timeline,
                                 parse_time_ranges, INTENT_ANCHORS)
from models.memory import EMBEDDING_VERSION, FactV2


def _unit(vec):
    v = np.array(vec, dtype=np.float32)
    return v / np.linalg.norm(v)


def _fact(fid, key="最爱食物", value="披萨", confidence=0.9, status="active",
          verification_count=3, updated_at="2026-07-15 10:00:00", qvec=None):
    return FactV2(
        id=fid, category="preference", fact_key=key, fact_value=value,
        confidence=confidence, status=status,
        verification_count=verification_count,
        created_at=updated_at, updated_at=updated_at,
        embedding=EmbeddingEngine.vec_to_bytes(qvec) if qvec is not None else None,
        embedding_version=EMBEDDING_VERSION if qvec is not None else 0,
    )


def _agent(facts=None, observations=None, experiences=None, relationship=None,
           qvec=None):
    """MemoryAgent over mocked ltm/lifecycle/embed. qvec = the vector every
    encode/encode_single call returns for the QUERY."""
    ltm = MagicMock()
    ltm.repo.get_active_facts_v2 = AsyncMock(return_value=facts or [])
    ltm.repo.get_recent_observations = AsyncMock(return_value=observations or [])
    ltm.repo.get_recent_experiences = AsyncMock(return_value=experiences or [])
    ltm.repo.get_all_relationships = AsyncMock(return_value=relationship or {})
    ltm.repo.get_fact_v2_by_id = AsyncMock(return_value=None)
    ltm.repo.search_facts_v2 = AsyncMock(return_value=[])
    ltm.repo.decay_fact_v2 = AsyncMock()

    lifecycle = MagicMock()
    lifecycle.observe = AsyncMock(return_value=MagicMock(id=99))
    lifecycle.contradict_fact = AsyncMock()
    lifecycle.promote_fact = AsyncMock()

    embed = MagicMock()
    q = qvec if qvec is not None else _unit([1, 0, 0, 0])
    embed.encode_single.return_value = q
    embed.encode.side_effect = lambda texts: np.stack([q] * len(texts))
    embed.health_check.return_value = True

    agent = MemoryAgent(ltm, lifecycle, MagicMock(), embedding_engine=embed)
    return agent, ltm, lifecycle, embed


class TestParseTimeRanges(unittest.TestCase):
    def test_yesterday(self):
        r = parse_time_ranges("昨天聊了什么", today=datetime(2026, 7, 16))
        self.assertEqual(r, [("2026-07-15", "2026-07-15")])

    def test_last_week_natural(self):
        # 2026-07-16 is a Thursday
        r = parse_time_ranges("上周吃了啥", today=datetime(2026, 7, 16))
        self.assertEqual(r, [("2026-07-06", "2026-07-12")])

    def test_last_month_natural(self):
        r = parse_time_ranges("上个月怎么样", today=datetime(2026, 7, 16))
        self.assertEqual(r, [("2026-06-01", "2026-06-30")])

    def test_year_month(self):
        r = parse_time_ranges("2026年7月我们去哪了", today=datetime(2026, 7, 16))
        self.assertEqual(r, [("2026-07-01", "2026-07-31")])

    def test_month_day(self):
        r = parse_time_ranges("7月15日发生了什么", today=datetime(2026, 7, 16))
        self.assertIn(("2026-07-15", "2026-07-15"), r)

    def test_no_time_words(self):
        self.assertEqual(parse_time_ranges("我最喜欢吃什么"), [])


class TestTimelineFreshness(unittest.TestCase):
    def test_stable_category_long_span_supported(self):
        ev = [
            MemoryEvidence("fact", 1, "a", 0.9, "2025-07-16 10:00:00"),
            MemoryEvidence("fact", 2, "a", 0.9, "2026-07-16 10:00:00"),
        ]
        self.assertGreaterEqual(check_timeline(ev, category="preference"), 0.8)

    def test_event_long_span_penalized(self):
        ev = [
            MemoryEvidence("fact", 1, "a", 0.9, "2025-07-16 10:00:00"),
            MemoryEvidence("fact", 2, "a", 0.9, "2026-07-16 10:00:00"),
        ]
        self.assertEqual(check_timeline(ev, category="event"), 0.4)

    def test_freshness_today(self):
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ev = [MemoryEvidence("fact", 1, "a", 0.9, today)]
        self.assertEqual(check_freshness(ev), 1.0)

    def test_freshness_ancient(self):
        ev = [MemoryEvidence("fact", 1, "a", 0.9, "2020-01-01 00:00:00")]
        self.assertEqual(check_freshness(ev), 0.1)


class TestAnswer(unittest.TestCase):
    def test_answer_with_matching_fact(self):
        qvec = _unit([1, 0, 0, 0])
        fact = _fact(1, qvec=qvec)
        agent, ltm, _, _ = _agent(facts=[fact], qvec=qvec)
        result = asyncio.run(agent.answer("我最喜欢吃什么"))

        self.assertIn("披萨", result.answer)
        self.assertGreater(result.confidence, 0.4)
        self.assertFalse(result.needs_more_evidence)
        self.assertEqual(result.evidences[0].source_type, "fact")

    def test_answer_no_evidence(self):
        agent, _, _, _ = _agent()
        result = asyncio.run(agent.answer("我最喜欢吃什么"))
        self.assertTrue(result.needs_more_evidence)
        self.assertEqual(result.confidence, 0.0)

    def test_answer_detects_contradiction(self):
        qvec = _unit([1, 0, 0, 0])
        f1 = _fact(1, value="披萨", qvec=qvec)
        f2 = _fact(2, value="寿司", qvec=qvec)
        agent, _, _, _ = _agent(facts=[f1, f2], qvec=qvec)
        result = asyncio.run(agent.answer("我最喜欢吃什么"))

        self.assertTrue(result.contradictions)
        self.assertTrue(any(e.is_contradicted for e in result.evidences))
        self.assertIn("需要用户确认", " ".join(result.suggestions))

    def test_time_post_filter(self):
        from datetime import timedelta
        qvec = _unit([1, 0, 0, 0])
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 08:00:00")
        old = _fact(1, value="老黄历", updated_at="2020-01-01 00:00:00", qvec=qvec)
        recent = _fact(2, value="昨天的事", updated_at=yesterday, qvec=qvec)
        agent, _, _, _ = _agent(facts=[old, recent], qvec=qvec)
        result = asyncio.run(agent.answer("昨天我喜欢吃什么"))

        contents = " ".join(e.content for e in result.evidences)
        self.assertIn("昨天的事", contents)
        self.assertNotIn("老黄历", contents)


class TestCorrectFact(unittest.TestCase):
    def test_correct_fact_flow(self):
        old = _fact(1, value="披萨", qvec=None)
        agent, ltm, lifecycle, _ = _agent()
        ltm.repo.get_fact_v2_by_id = AsyncMock(return_value=old)

        asyncio.run(agent.correct_fact(1, "寿司", source_turn=42))

        lifecycle.observe.assert_awaited_once()
        obs_kwargs = lifecycle.observe.call_args.kwargs
        self.assertIn("披萨 → 寿司", obs_kwargs["content"])
        self.assertEqual(obs_kwargs["created_by"], "user_correction")
        lifecycle.contradict_fact.assert_awaited_once_with(1, reason="user correction")
        promote_kwargs = lifecycle.promote_fact.call_args.kwargs
        self.assertEqual(promote_kwargs["observation_ids"], [99])
        self.assertEqual(promote_kwargs["value"], "寿司")
        self.assertEqual(promote_kwargs["confidence"], 1.0)


class TestVerifyFact(unittest.TestCase):
    def test_verify_fact_not_found(self):
        agent, _, _, _ = _agent()
        result = asyncio.run(agent.verify_fact(404))
        self.assertEqual(result.confidence, 0.0)

    def test_verify_fact_holds(self):
        qvec = _unit([1, 0, 0, 0])
        fact = _fact(1, qvec=qvec)
        agent, ltm, _, _ = _agent(facts=[fact], qvec=qvec)
        ltm.repo.get_fact_v2_by_id = AsyncMock(return_value=fact)
        result = asyncio.run(agent.verify_fact(1))

        self.assertIn("披萨", result.answer)
        self.assertGreaterEqual(result.confidence, 0.3)

    def test_batch_verify_decays_low_confidence(self):
        fact = _fact(1, qvec=None)
        agent, ltm, _, _ = _agent(facts=[fact])
        agent.verify_fact = AsyncMock(
            return_value=MagicMock(confidence=0.1))
        asyncio.run(agent.batch_verify_facts(limit=5))
        ltm.repo.decay_fact_v2.assert_awaited_once_with(1, 0.5)

    def test_batch_verify_keeps_high_confidence(self):
        fact = _fact(1, qvec=None)
        agent, ltm, _, _ = _agent(facts=[fact])
        agent.verify_fact = AsyncMock(
            return_value=MagicMock(confidence=0.9))
        asyncio.run(agent.batch_verify_facts(limit=5))
        ltm.repo.decay_fact_v2.assert_not_called()


class TestIntentAnchors(unittest.TestCase):
    def test_intent_recall(self):
        q = _unit([1, 0, 0, 0])
        anchor_vecs = {
            INTENT_ANCHORS["recall"][0]: q,
            INTENT_ANCHORS["recall"][1]: _unit([0.9, 0.1, 0, 0]),
            INTENT_ANCHORS["recall"][2]: _unit([0.9, 0, 0.1, 0]),
        }
        fallback = _unit([0, 1, 0, 0])

        agent, _, _, embed = _agent(qvec=q)
        embed.encode.side_effect = lambda texts: np.stack(
            [anchor_vecs.get(t, fallback) for t in texts])

        clues = asyncio.run(agent._extract_clues("我们上次聊了什么"))
        self.assertEqual(clues.intent, "recall")

    def test_intent_below_threshold_is_none(self):
        q = _unit([1, 0, 0, 0])
        orthogonal = _unit([0, 1, 0, 0])
        agent, _, _, embed = _agent(qvec=q)
        embed.encode.side_effect = lambda texts: np.stack(
            [orthogonal] * len(texts))

        clues = asyncio.run(agent._extract_clues("今天天气怎么样"))
        self.assertIsNone(clues.intent)


if __name__ == "__main__":
    unittest.main()
