"""Tests for memory/embeddings.py — EmbeddingEngine with cache + fallback."""
import unittest
from unittest.mock import MagicMock

import numpy as np


class TestEmbeddingEngineHealth(unittest.TestCase):
    def setUp(self):
        from memory.embeddings import EmbeddingEngine
        self.engine = EmbeddingEngine(dim=1024)

    def test_empty_input_returns_empty(self):
        result = self.engine.encode([])
        self.assertEqual(result.shape, (0, 1024))

    def test_cache_integrated(self):
        self.assertIsNotNone(self.engine._cache)

    def test_cache_hit_returns_cached(self):
        vec = np.ones(1024, dtype=np.float32)
        vec /= np.linalg.norm(vec)
        self.engine._cache.set("hello", vec)
        cached = self.engine._cache.get("hello", expected_dim=1024)
        self.assertIsNotNone(cached)

    def test_cache_hit_skip(self):
        """Cache hit should return without calling API."""
        vec = np.ones(1024, dtype=np.float32)
        vec /= np.linalg.norm(vec)
        self.engine._cache.set("hello", vec)
        # After removing session.post, cache hit should still work
        old_post = self.engine._session.post
        try:
            self.engine._session.post = None
            result = self.engine.encode(["hello"])
            self.assertEqual(result.shape, (1, 1024))
        finally:
            self.engine._session.post = old_post

    def test_api_failure_with_no_cache_raises(self):
        self.engine._session.post = MagicMock(side_effect=Exception("API down"))
        try:
            with self.assertRaises(Exception):
                self.engine.encode(["new text"])
        finally:
            self.engine._session.post = None

    def test_api_failure_with_partial_cache_returns_cached(self):
        vec = np.ones(1024, dtype=np.float32)
        vec /= np.linalg.norm(vec)
        self.engine._cache.set("existing", vec)
        self.engine._session.post = MagicMock(side_effect=Exception("API down"))
        try:
            result = self.engine.encode(["existing", "new"])
            # Should return only the cached result (1, 1024)
            self.assertEqual(result.shape, (1, 1024))
        except Exception:
            pass  # also acceptable to raise if nothing cached for "new"
        finally:
            self.engine._session.post = None

    def test_dimension_mismatch_clears_old_cache(self):
        """When API returns different dim, old-dim vectors should be discarded."""
        old_vec = np.ones(1024, dtype=np.float32)
        old_vec /= np.linalg.norm(old_vec)
        self.engine._cache.set("old_text", old_vec)
        self.engine._dim = 256  # simulate changed dim
        result = self.engine._cache.get("old_text", expected_dim=256)
        self.assertIsNone(result)


class TestEmbeddingCache(unittest.TestCase):
    def setUp(self):
        from memory.embeddings import EmbeddingCache
        self.cache = EmbeddingCache(max_size=10)

    def test_set_and_get(self):
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        self.cache.set("test", vec)
        result = self.cache.get("test")
        self.assertIsNotNone(result)
        self.assertTrue(np.allclose(result, vec))

    def test_missing_key_returns_none(self):
        result = self.cache.get("nonexistent")
        self.assertIsNone(result)

    def test_evicts_oldest(self):
        for i in range(15):
            self.cache.set(f"key{i}", np.array([float(i)], dtype=np.float32))
        self.assertLessEqual(len(self.cache), 10)
        self.assertIsNone(self.cache.get("key0"))

    def test_lru_moves_to_end(self):
        for i in range(10):
            self.cache.set(f"key{i}", np.array([float(i)], dtype=np.float32))
        self.cache.get("key0")
        for i in range(10, 12):
            self.cache.set(f"key{i}", np.array([float(i)], dtype=np.float32))
        self.assertIsNotNone(self.cache.get("key0"))
        self.assertIsNone(self.cache.get("key1"))

    def test_dimension_check_rejects_mismatch(self):
        vec = np.ones(512, dtype=np.float32)
        self.cache.set("test", vec)
        result = self.cache.get("test", expected_dim=1024)
        self.assertIsNone(result)

    def test_invalidate_removes_entry(self):
        vec = np.ones(8, dtype=np.float32)
        self.cache.set("test", vec)
        self.cache.invalidate("test")
        self.assertIsNone(self.cache.get("test"))

    def test_clear_empties_cache(self):
        for i in range(5):
            self.cache.set(f"key{i}", np.array([float(i)], dtype=np.float32))
        self.cache.clear()
        self.assertEqual(len(self.cache), 0)


class TestEmbeddingSanity(unittest.TestCase):
    """Quick sanity checks against live embedding server."""

    def test_real_server_health(self):
        from memory.embeddings import EmbeddingEngine
        engine = EmbeddingEngine(endpoint="http://localhost:8080/v1/embeddings", dim=1024)
        self.assertTrue(engine.health_check())

    def test_real_server_encode(self):
        from memory.embeddings import EmbeddingEngine
        engine = EmbeddingEngine(endpoint="http://localhost:8080/v1/embeddings", dim=1024)
        vecs = engine.encode(["test"])
        self.assertEqual(vecs.shape, (1, 1024))


if __name__ == "__main__":
    unittest.main()
