"""Tests for memory/retrieval_pipeline.py"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from memory.embeddings import EmbeddingEngine
from memory.retrieval_pipeline import (QueryClues, MemoryEvidence,
                                       retrieve_bundle, cross_verify,
                                       parse_time_ranges, ContextBuilder)
from models.memory import EMBEDDING_VERSION, FactV2


def _unit(vec):
    v = np.array(vec, dtype=np.float32)
    return v / np.linalg.norm(v)


def _repo(facts=None, observations=None, experiences=None,
          relationship=None, insights=None):
    repo = MagicMock()
    repo.get_active_facts_v2 = AsyncMock(return_value=facts or [])
    repo.get_recent_observations = AsyncMock(return_value=observations or [])
    repo.get_recent_experiences = AsyncMock(return_value=experiences or [])
    repo.get_all_relationships = AsyncMock(return_value=relationship or {})
    repo.get_active_insights = AsyncMock(return_value=insights or [])
    return repo


class TestParseTimeRanges(unittest.TestCase):
    def test_yesterday(self):
        from datetime import datetime
        r = parse_time_ranges("昨天聊了什么", today=datetime(2026, 7, 16))
        self.assertEqual(r, [("2026-07-15", "2026-07-15")])


class TestRetrieveBundle(unittest.TestCase):
    def test_serial_order_and_pools(self):
        """五源串行查询，相关性下限过滤低相似证据。"""
        qvec = _unit([1, 0, 0, 0])
        blob = EmbeddingEngine.vec_to_bytes(qvec)
        good = FactV2(id=1, category="preference", fact_key="最爱食物",
                      fact_value="披萨", confidence=0.9, status="active",
                      embedding=blob, embedding_version=EMBEDDING_VERSION,
                      updated_at="2026-07-19 10:00:00")
        repo = _repo(facts=[good])
        clues = QueryClues(raw_query="披萨", query_embedding=blob)
        evidences, top_sim = asyncio.run(
            retrieve_bundle(repo, clues, max_evidence=10, relevance_floor=0.35))
        self.assertEqual(len(evidences), 1)
        self.assertAlmostEqual(top_sim, 1.0, places=3)
        self.assertEqual(evidences[0].source_type, "fact")

    def test_recall_intent_exempts_floor(self):
        """intent 为 recall 时跳过相关性下限，保留无向量证据。"""
        no_embed = FactV2(id=1, category="preference", fact_key="最爱食物",
                          fact_value="披萨", confidence=0.9, status="active",
                          embedding=None, embedding_version=0,
                          updated_at="2026-07-19 10:00:00")
        repo = _repo(facts=[no_embed])
        clues = QueryClues(raw_query="我们上次聊了什么", intent="recall")
        evidences, top_sim = asyncio.run(
            retrieve_bundle(repo, clues, max_evidence=10, relevance_floor=0.35))
        self.assertEqual(len(evidences), 1)
        self.assertIsNone(top_sim)

    def test_time_filter(self):
        """时间范围过滤证据。"""
        from datetime import datetime, timedelta
        qvec = _unit([1, 0, 0, 0])
        blob = EmbeddingEngine.vec_to_bytes(qvec)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 08:00:00")
        old = FactV2(id=1, category="event", fact_key="事", fact_value="老黄历",
                     confidence=0.9, status="active", embedding=blob,
                     embedding_version=EMBEDDING_VERSION,
                     updated_at="2020-01-01 00:00:00")
        recent = FactV2(id=2, category="event", fact_key="事", fact_value="昨天的事",
                        confidence=0.9, status="active", embedding=blob,
                        embedding_version=EMBEDDING_VERSION,
                        updated_at=yesterday)
        repo = _repo(facts=[old, recent])
        clues = QueryClues(raw_query="昨天发生了啥", query_embedding=blob,
                           time_ranges=[(yesterday[:10], yesterday[:10])])
        evidences, _ = asyncio.run(
            retrieve_bundle(repo, clues, max_evidence=10, relevance_floor=0.35))
        contents = " ".join(e.content for e in evidences)
        self.assertIn("昨天的事", contents)
        self.assertNotIn("老黄历", contents)


class TestCrossVerify(unittest.TestCase):
    def test_contradiction_detected(self):
        """同 category|key 不同值 → 双方标记 is_contradicted。"""
        e1 = MemoryEvidence(source_type="fact", source_id=1,
                            content="preference|最爱食物: 披萨",
                            confidence=0.9, timestamp="2026-07-20 10:00:00")
        e2 = MemoryEvidence(source_type="fact", source_id=2,
                            content="preference|最爱食物: 寿司",
                            confidence=0.8, timestamp="2026-07-20 10:00:00")
        evidences, contradictions, consistency = asyncio.run(
            cross_verify([e1, e2]))
        self.assertEqual(len(contradictions), 1)
        self.assertTrue(e1.is_contradicted)
        self.assertTrue(e2.is_contradicted)
        self.assertEqual(consistency, 0.5)  # no embed provided → neutral

    def test_no_contradiction_same_key(self):
        """同 category|key 同值不视为矛盾。"""
        e1 = MemoryEvidence(source_type="fact", source_id=1,
                            content="preference|最爱食物: 披萨",
                            confidence=0.9, timestamp="2026-07-20 10:00:00")
        e2 = MemoryEvidence(source_type="fact", source_id=2,
                            content="preference|最爱食物: 披萨",
                            confidence=0.8, timestamp="2026-07-20 10:00:00")
        _, contradictions, _ = asyncio.run(cross_verify([e1, e2]))
        self.assertEqual(len(contradictions), 0)
        self.assertFalse(e1.is_contradicted)

    def test_consistency_with_embed(self):
        """有 embed 时计算批量一致性。"""
        embed = MagicMock()
        q = _unit([1, 0, 0, 0])
        embed.encode.return_value = np.stack([q, q])
        e1 = MemoryEvidence(source_type="fact", source_id=1,
                            content="a", confidence=0.9,
                            timestamp="2026-07-20 10:00:00")
        e2 = MemoryEvidence(source_type="fact", source_id=2,
                            content="a", confidence=0.9,
                            timestamp="2026-07-20 10:00:00")
        _, _, consistency = asyncio.run(cross_verify([e1, e2], embed=embed))
        self.assertAlmostEqual(consistency, 1.0, places=3)


class TestContextBuilder(unittest.TestCase):
    def _ma(self, evidences, answer="答案文本", confidence=0.8,
            contradictions=None, needs_more_evidence=False):
        m = MagicMock()
        m.answer, m.confidence = answer, confidence
        m.evidences = evidences
        m.contradictions = contradictions or []
        m.needs_more_evidence = needs_more_evidence
        return m

    def _ev(self, source_type, content, is_contradicted=False):
        return MemoryEvidence(source_type=source_type, source_id=1,
                              content=content, confidence=0.8,
                              timestamp="2026-07-20 10:00:00",
                              is_contradicted=is_contradicted)

    def test_agent1_full_golden(self):
        ma = self._ma([], answer="事实文本", confidence=0.82,
                      contradictions=["A vs B"], needs_more_evidence=False)
        out = ContextBuilder().build("agent1", ma)
        self.assertEqual(out, "=== 记忆检索（置信度 82%）===\n事实文本\n"
                              "⚠️ 矛盾记忆：A vs B（如需引用请先向用户确认）")

    def test_agent1_needs_more_evidence(self):
        ma = self._ma([], answer="事实文本", confidence=0.82,
                      contradictions=[], needs_more_evidence=True)
        out = ContextBuilder().build("agent1", ma)
        self.assertIn("证据不足", out)

    def test_agent1_low_confidence_caveat(self):
        ma = self._ma([], answer="事实文本", confidence=0.3,
                      contradictions=[], needs_more_evidence=False)
        out = ContextBuilder().build("agent1", ma)
        self.assertIn("证据不足", out)

    def test_agent3_light_filters(self):
        evs = [
            self._ev("fact", "preference|最爱食物: 披萨"),
            self._ev("fact", "event|坏事实: x", is_contradicted=True),
            self._ev("insight", "洞察[pattern]：假设"),
            self._ev("experience", "[开心] 聊歌单"),
            self._ev("relationship", "关系指标：trust=1.00，familiarity=0.80"),
        ]
        out = ContextBuilder().build("agent3", self._ma(evs))
        self.assertIn("最爱食物: 披萨", out)
        self.assertIn("[开心] 聊歌单", out)
        self.assertIn("trust=1.00", out)
        self.assertNotIn("坏事实", out)      # 矛盾剔除
        self.assertNotIn("洞察", out)        # insight 不进轻量
        self.assertNotIn("置信度", out)      # 无标注

    def test_agent3_caps_and_empty(self):
        """4 条 fact 只取 3；空过滤结果返回 ""。"""
        evs = [
            self._ev("fact", f"preference|事实{i}: v")
            for i in range(4)
        ]
        out = ContextBuilder().build("agent3", self._ma(evs))
        self.assertEqual(out.count("preference|"), 3)

        empty = [self._ev("insight", "洞察")]
        self.assertEqual(ContextBuilder().build("agent3", self._ma(empty)), "")

    def test_agent2_empty(self):
        self.assertEqual(ContextBuilder().build("agent2", self._ma([])), "")

    def test_none_answer(self):
        self.assertEqual(ContextBuilder().build("agent1", None), "")

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            ContextBuilder().build("agent9", self._ma([]))


if __name__ == "__main__":
    unittest.main()
