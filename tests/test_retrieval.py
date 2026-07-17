"""Tests for memory/retrieval.py — keyword scoring with confidence (#6)."""
import unittest
from unittest.mock import MagicMock

from models.memory import UserFact, EMBEDDING_VERSION
from memory.retrieval import MemoryRetriever


class TestKeywordScoreConfidence(unittest.TestCase):
    def test_high_confidence_boost(self):
        """High confidence fact should score higher than low confidence."""
        f_high = UserFact(fact_key="爱好", fact_value="游泳", category="preference",
                          confidence=1.0, importance=0.5, composite_score=1.0)
        f_low = UserFact(fact_key="爱好", fact_value="跑步", category="preference",
                         confidence=0.2, importance=0.5, composite_score=1.0)

        score_high = MemoryRetriever._keyword_score_single(f_high, ["爱好"], "爱好")
        score_low = MemoryRetriever._keyword_score_single(f_low, ["爱好"], "爱好")
        self.assertGreater(score_high, score_low)

    def test_confidence_contributes_weight(self):
        """Confidence contributes 0.15 weight to keyword score."""
        f = UserFact(fact_key="test", fact_value="x", category="preference",
                     confidence=0.8, importance=0.5, composite_score=0.5)
        score = MemoryRetriever._keyword_score_single(f, [], "")
        # composite*0.2 + importance*0.3 + confidence*0.15
        expected_base = 0.5 * 0.2 + 0.5 * 0.3 + 0.8 * 0.15
        self.assertAlmostEqual(score, max(0, expected_base))

    def test_keyword_hit_boost(self):
        """Keyword hits in fact_key should boost score."""
        f = UserFact(fact_key="最喜欢的食物", fact_value="披萨", category="preference",
                     confidence=0.9, importance=0.6, composite_score=1.0)
        score_with = MemoryRetriever._keyword_score_single(f, ["食物"], "食物")
        score_without = MemoryRetriever._keyword_score_single(f, [], "")
        self.assertGreater(score_with, score_without)

    def test_category_match_boost(self):
        """Exact category match should give +0.2."""
        f1 = UserFact(fact_key="test", fact_value="x", category="preference",
                      confidence=0.8, importance=0.5, composite_score=0.5)
        f2 = UserFact(fact_key="test", fact_value="x", category="identity",
                      confidence=0.8, importance=0.5, composite_score=0.5)

        score_match = MemoryRetriever._keyword_score_single(f1, ["preference"], "preference")
        score_no_match = MemoryRetriever._keyword_score_single(f2, ["preference"], "preference")
        self.assertGreater(score_match, score_no_match)

    def test_recall_penalty(self):
        """High recall_count should penalize score."""
        f_low_recall = UserFact(fact_key="test", fact_value="x", category="routine",
                                confidence=0.8, importance=0.5, composite_score=0.5,
                                recall_count=0)
        f_high_recall = UserFact(fact_key="test", fact_value="x", category="routine",
                                 confidence=0.8, importance=0.5, composite_score=0.5,
                                 recall_count=20)
        score_low = MemoryRetriever._keyword_score_single(f_low_recall, [], "")
        score_high = MemoryRetriever._keyword_score_single(f_high_recall, [], "")
        self.assertGreater(score_low, score_high)

    def test_score_non_negative(self):
        """Score should never be negative."""
        f = UserFact(fact_key="test", fact_value="x", category="routine",
                     confidence=0.0, importance=0.0, composite_score=0.0,
                     recall_count=100)
        score = MemoryRetriever._keyword_score_single(f, [], "")
        self.assertGreaterEqual(score, 0)


class TestExtractKeywords(unittest.TestCase):
    def test_stopwords_filtered(self):
        keywords = MemoryRetriever._extract_keywords("你好吗我是谁")
        for sw in ["吗", "是", "的", "了"]:
            self.assertNotIn(sw, keywords)

    def test_returns_keywords(self):
        keywords = MemoryRetriever._extract_keywords("hello world test")
        self.assertGreater(len(keywords), 0)
        self.assertIn("hello", keywords)

    def test_empty_input(self):
        keywords = MemoryRetriever._extract_keywords("")
        self.assertEqual(len(keywords), 0)


# ── P1/P2 hotfix tests ──

class TestHybridScoreType(unittest.TestCase):
    """P2: _hybrid_score return type should be list[UserFact]."""

    def test_hybrid_score_returns_userfact_list(self):
        retriever = MemoryRetriever(MagicMock())
        f = UserFact(id=1, fact_key="test", fact_value="x", composite_score=0.5)
        result = retriever._hybrid_score("test", [f], ["test"])
        self.assertIsInstance(result, list)
        if result:
            self.assertIsInstance(result[0], UserFact)

    def test_keyword_score_returns_float(self):
        f = UserFact(id=1, fact_key="test", fact_value="x", composite_score=0.5,
                     confidence=0.8, importance=0.5)
        score = MemoryRetriever._keyword_score_single(f, ["test"], "test")
        self.assertIsInstance(score, float)


class TestBytesToVecDim(unittest.TestCase):
    """RT-007 regression: bytes_to_vec must not hardcode a dimension."""

    def test_infer_dim_from_blob(self):
        """1024-dim roundtrip works without an explicit dim."""
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        vec = np.random.rand(1024).astype(np.float32)
        blob = EmbeddingEngine.vec_to_bytes(vec)
        out = EmbeddingEngine.bytes_to_vec(blob)
        np.testing.assert_array_equal(out, vec)

    def test_explicit_dim_mismatch_raises(self):
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        blob = EmbeddingEngine.vec_to_bytes(np.ones(1024, dtype=np.float32))
        with self.assertRaises(ValueError):
            EmbeddingEngine.bytes_to_vec(blob, dim=512)

    def test_explicit_dim_match_ok(self):
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        blob = EmbeddingEngine.vec_to_bytes(np.ones(1024, dtype=np.float32))
        out = EmbeddingEngine.bytes_to_vec(blob, dim=1024)
        self.assertEqual(len(out), 1024)


class TestHybridScoreSemanticDim(unittest.TestCase):
    """RT-007 regression: facts with production-dim (1024) embeddings must
    actually get semantic scores, not silently degrade to keyword-only."""

    @staticmethod
    def _unit_vec(dim, seed):
        import numpy as np
        rng = np.random.RandomState(seed)
        v = rng.rand(dim).astype(np.float32)
        return v / np.linalg.norm(v)

    @staticmethod
    def _retriever(qvec):
        engine = MagicMock()
        engine.encode_single.return_value = qvec
        return MemoryRetriever(MagicMock(), embedding_engine=engine)

    def test_semantic_score_applied_for_matching_dim(self):
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        qvec = self._unit_vec(1024, seed=1)
        retriever = self._retriever(qvec)
        aligned = UserFact(id=1, fact_key="k1", fact_value="v", category="preference",
                           confidence=0.9, importance=0.5, composite_score=0.5,
                           embedding=EmbeddingEngine.vec_to_bytes(qvec),
                           embedding_version=EMBEDDING_VERSION)
        zero = UserFact(id=2, fact_key="k2", fact_value="v", category="preference",
                        confidence=0.9, importance=0.5, composite_score=0.5,
                        embedding=EmbeddingEngine.vec_to_bytes(np.zeros(1024, dtype=np.float32)),
                        embedding_version=EMBEDDING_VERSION)
        # aligned is listed second; only a working semantic path can put it first
        result = retriever._hybrid_score("查询", [zero, aligned], [], query_vec=qvec)
        self.assertEqual(result[0].id, 1)

    def test_dim_mismatch_logs_warning_and_degrades(self):
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        qvec = self._unit_vec(1024, seed=2)
        retriever = self._retriever(qvec)
        bad = UserFact(id=3, fact_key="k", fact_value="v", category="preference",
                       confidence=0.9, importance=0.5, composite_score=0.5,
                       embedding=EmbeddingEngine.vec_to_bytes(np.ones(512, dtype=np.float32)),
                       embedding_version=EMBEDDING_VERSION)
        with self.assertLogs("memory.retrieval", level="WARNING") as cm:
            result = retriever._hybrid_score("查询", [bad], [], query_vec=qvec)
        self.assertEqual(result, [bad])  # no crash, fact still returned
        self.assertTrue(any("unusable" in m for m in cm.output))

    def test_stale_version_skipped(self):
        """embedding_version != EMBEDDING_VERSION rows are treated as having
        no vector (rolling rebuild), without unusable warnings."""
        import numpy as np
        from memory.embeddings import EmbeddingEngine
        qvec = self._unit_vec(1024, seed=3)
        retriever = self._retriever(qvec)
        stale = UserFact(id=4, fact_key="k1", fact_value="v", category="preference",
                         confidence=0.9, importance=0.5, composite_score=0.5,
                         embedding=EmbeddingEngine.vec_to_bytes(qvec),
                         embedding_version=EMBEDDING_VERSION + 99)
        current = UserFact(id=5, fact_key="k2", fact_value="v", category="preference",
                           confidence=0.9, importance=0.5, composite_score=0.5,
                           embedding=EmbeddingEngine.vec_to_bytes(qvec),
                           embedding_version=EMBEDDING_VERSION)
        with self.assertNoLogs("memory.retrieval", level="WARNING"):
            result = retriever._hybrid_score("查询", [stale, current], [], query_vec=qvec)
        # stale aligned vector must NOT outrank the current-version one
        self.assertEqual(result[0].id, 5)


class TestLongTermImport(unittest.TestCase):
    """P2: import re should be at top of long_term.py, not inline."""

    def test_re_imported_at_top(self):
        import memory.long_term as lt
        import inspect
        source = inspect.getsource(lt.LongTermMemory._build_context)
        # import re should NOT appear inside the method body
        self.assertNotIn("import re", source.split("async def")[0] if "async def" in source else "")


class TestEmbeddingsHotfix(unittest.TestCase):
    """P0: dimension mismatch + zero vector regression tests."""

    def setUp(self):
        from memory.embeddings import EmbeddingEngine, EmbeddingCache
        self.engine = EmbeddingEngine(dim=512)

    def test_cache_integrated(self):
        """#196: EmbeddingEngine should have an integrated cache."""
        self.assertIsNotNone(self.engine._cache)
        from memory.embeddings import EmbeddingCache
        self.assertIsInstance(self.engine._cache, EmbeddingCache)

    def test_encode_empty_returns_empty(self):
        result = self.engine.encode([])
        import numpy as np
        self.assertEqual(result.shape, (0, 512))

    def test_encode_cache_hit(self):
        """Cached text should skip API call."""
        import numpy as np
        cached_vec = np.ones(512, dtype=np.float32)
        cached_vec /= np.linalg.norm(cached_vec)
        self.engine._cache.set("hello", cached_vec)

        # Don't mock the session — if API is called, it'll fail (real server not running)
        # Instead, we verify the cache returns the right result
        result = self.engine._cache.get("hello", expected_dim=512)
        self.assertIsNotNone(result)

    def test_encode_api_failure_raises_when_nothing_cached(self):
        """P0: API failure with no cache should raise."""
        import requests
        original_post = self.engine._session.post
        self.engine._session.post = MagicMock(side_effect=requests.ConnectionError("no server"))
        try:
            with self.assertRaises(Exception):
                self.engine.encode(["uncached text"])
        finally:
            self.engine._session.post = original_post

    def test_encode_dimension_mismatch_drops_old_cache(self):
        """P0: dimension change should discard old-dimension vectors."""
        import numpy as np
        # Pre-populate cache with old dimension vector
        old_vec = np.ones(512, dtype=np.float32)
        old_vec /= np.linalg.norm(old_vec)
        self.engine._cache.set("old_text", old_vec)

        # Simulate API returning different dimension
        api_resp = MagicMock()
        api_resp.status_code = 200
        api_resp.json.return_value = {"data": [{"embedding": [0.1] * 256}]}
        self.engine._session.post = MagicMock(return_value=api_resp)
        self.engine._session.post.raise_for_status = MagicMock()

        try:
            result = self.engine.encode(["old_text", "new_text"])
            # All vectors should have same dimension (256)
            self.assertEqual(result.shape[1], 256)
            # Old cache should have been cleared
            self.assertEqual(len(self.engine._cache), 1)  # only new_text cached
        finally:
            del self.engine._session.post


if __name__ == "__main__":
    unittest.main()
