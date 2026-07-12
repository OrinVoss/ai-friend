"""Tests for memory/fact_checker.py (#6)."""
import unittest
from unittest.mock import MagicMock

from models.memory import UserFact
from memory.fact_checker import (
    FactChecker,
    SIMILARITY_THRESHOLD,
    CONTRADICTION_DECAY,
    CONTRADICTION_DECAY_MILD,
    MIN_CONFIDENCE_FILTER,
    MIN_NEW_FACT_CONFIDENCE,
    CONFIDENCE_RATIO_MILD,
    KEYWORD_OVERLAP_THRESHOLD,
)


class TestFactCheckerInit(unittest.TestCase):
    def test_init_no_embedding(self):
        fc = FactChecker()
        self.assertIsNone(fc._embed)

    def test_init_with_embedding(self):
        mock_embed = MagicMock()
        fc = FactChecker(embedding_engine=mock_embed)
        self.assertEqual(fc._embed, mock_embed)


class TestDetectContradiction(unittest.TestCase):
    def setUp(self):
        self.fc = FactChecker()
        self.existing = [
            UserFact(id=1, category="preference", fact_key="最喜欢的食物",
                     fact_value="意大利面", confidence=0.9),
            UserFact(id=2, category="identity", fact_key="职业",
                     fact_value="程序员", confidence=1.0),
        ]

    def test_empty_existing_returns_none(self):
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="test", fact_value="x"),
            [],
        )
        self.assertIsNone(result)

    def test_same_fact_no_contradiction(self):
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的食物",
                     fact_value="意大利面", confidence=0.8),
            self.existing,
        )
        self.assertIsNone(result)

    def test_same_key_different_value_is_contradiction(self):
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的食物",
                     fact_value="寿司", confidence=0.8),
            self.existing,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 1)
        self.assertEqual(result.fact_value, "意大利面")

    def test_different_category_different_key_no_contradiction(self):
        result = self.fc.detect_contradiction(
            UserFact(category="routine", fact_key="每天起床时间",
                     fact_value="8点", confidence=0.7),
            self.existing,
        )
        self.assertIsNone(result)

    def test_embedding_contradiction(self):
        """When embedding is available, semantic similarity should detect contradictions."""
        mock_embed = MagicMock()
        mock_embed.health_check.return_value = True
        # Return vectors: high similarity for related facts with different values
        mock_embed.encode.side_effect = [
            [[0.8, 0.6, 0.1]],  # new fact embedding
            [[0.79, 0.61, 0.09]],  # existing fact embedding (high similarity)
        ]
        fc = FactChecker(embedding_engine=mock_embed)

        existing = [
            UserFact(id=3, category="preference", fact_key="喜欢音乐类型",
                     fact_value="古典音乐", confidence=0.8),
        ]
        result = fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的音乐",
                     fact_value="摇滚音乐", confidence=0.7),
            existing,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 3)

    def test_embedding_similar_but_same_value_no_contradiction(self):
        """Same value with different key is not a contradiction."""
        mock_embed = MagicMock()
        mock_embed.health_check.return_value = True
        mock_embed.encode.side_effect = [
            [[0.8, 0.6, 0.1]],
            [[0.79, 0.61, 0.09]],
        ]
        fc = FactChecker(embedding_engine=mock_embed)

        existing = [
            UserFact(id=4, category="preference", fact_key="喜欢音乐类型",
                     fact_value="摇滚", confidence=0.8),
        ]
        result = fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的音乐",
                     fact_value="摇滚", confidence=0.7),
            existing,
        )
        self.assertIsNone(result)

    def test_embedding_low_similarity_no_contradiction(self):
        """Low similarity should not flag as contradiction."""
        mock_embed = MagicMock()
        mock_embed.health_check.return_value = True
        mock_embed.encode.side_effect = [
            [[0.8, 0.6, 0.1]],  # unrelated vectors
            [[-0.7, -0.5, -0.3]],
        ]
        fc = FactChecker(embedding_engine=mock_embed)

        existing = [
            UserFact(id=5, category="routine", fact_key="每天喝水",
                     fact_value="8杯", confidence=0.7),
        ]
        result = fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的音乐",
                     fact_value="摇滚", confidence=0.7),
            existing,
        )
        self.assertIsNone(result)


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.fc = FactChecker()
        self.repo = MagicMock()

    def test_resolve_high_confidence_decay(self):
        """High confidence fact gets decayed, not deactivated."""
        old = UserFact(id=10, fact_key="爱好", fact_value="游泳", confidence=0.8)
        new = UserFact(fact_key="爱好", fact_value="跑步", confidence=0.7)

        deactivated = self.fc.resolve(new, old, self.repo)
        self.assertFalse(deactivated)
        self.repo.update_fact_confidence.assert_called_once()
        # 0.8 * 0.4 = 0.32, still above 0.2 threshold
        expected_conf = 0.8 * CONTRADICTION_DECAY  # 0.32
        self.repo.update_fact_confidence.assert_called_with(10, expected_conf)
        self.repo.deactivate_fact.assert_not_called()

    def test_resolve_low_confidence_deactivate(self):
        """Low confidence fact gets deactivated."""
        old = UserFact(id=11, fact_key="住所", fact_value="北京", confidence=0.3)
        new = UserFact(fact_key="住所", fact_value="上海", confidence=0.7)

        deactivated = self.fc.resolve(new, old, self.repo)
        self.assertTrue(deactivated)
        self.repo.deactivate_fact.assert_called_once_with(11)
        self.repo.update_fact_confidence.assert_not_called()


class TestCosineSim(unittest.TestCase):
    def test_identical(self):
        sim = FactChecker._cosine_sim([1, 2, 3], [1, 2, 3])
        self.assertAlmostEqual(sim, 1.0)

    def test_orthogonal(self):
        sim = FactChecker._cosine_sim([1, 0, 0], [0, 1, 0])
        self.assertAlmostEqual(sim, 0.0)

    def test_opposite(self):
        sim = FactChecker._cosine_sim([1, 0], [-1, 0])
        self.assertAlmostEqual(sim, -1.0)

    def test_zero_vector(self):
        sim = FactChecker._cosine_sim([0, 0], [1, 1])
        self.assertEqual(sim, 0.0)


class TestConstants(unittest.TestCase):
    def test_thresholds(self):
        self.assertGreater(SIMILARITY_THRESHOLD, 0.5)
        self.assertLess(SIMILARITY_THRESHOLD, 0.9)
        self.assertLess(CONTRADICTION_DECAY, 0.5)
        self.assertGreater(CONTRADICTION_DECAY, 0.0)
        self.assertLess(MIN_CONFIDENCE_FILTER, 0.5)
        self.assertGreaterEqual(MIN_NEW_FACT_CONFIDENCE, 0.0)
        self.assertLess(MIN_NEW_FACT_CONFIDENCE, 1.0)
        self.assertGreater(CONFIDENCE_RATIO_MILD, 0.0)
        self.assertLess(CONFIDENCE_RATIO_MILD, 1.0)
        self.assertGreaterEqual(KEYWORD_OVERLAP_THRESHOLD, 0.3)
        self.assertLess(KEYWORD_OVERLAP_THRESHOLD, 1.0)


class TestResolveQualityAwareness(unittest.TestCase):
    """FC-003: new-fact quality validation in resolve()."""

    def setUp(self):
        self.fc = FactChecker()
        self.repo = MagicMock()

    def test_low_confidence_new_fact_is_ignored(self):
        """New fact below MIN_NEW_FACT_CONFIDENCE should not affect old fact."""
        old = UserFact(id=20, fact_key="爱好", fact_value="游泳", confidence=0.8)
        new = UserFact(fact_key="爱好", fact_value="跑步", confidence=MIN_NEW_FACT_CONFIDENCE - 0.05)

        deactivated = self.fc.resolve(new, old, self.repo)
        self.assertFalse(deactivated)
        self.repo.update_fact_confidence.assert_not_called()
        self.repo.deactivate_fact.assert_not_called()

    def test_mild_decay_when_new_confidence_much_lower(self):
        """If new confidence < 50% of old confidence, apply mild decay."""
        old = UserFact(id=21, fact_key="住所", fact_value="北京", confidence=0.9)
        new = UserFact(fact_key="住所", fact_value="上海", confidence=0.3)
        # ratio = 0.3 / 0.9 = 0.33 < 0.5 -> mild decay

        deactivated = self.fc.resolve(new, old, self.repo)
        self.assertFalse(deactivated)
        self.repo.update_fact_confidence.assert_called_once()
        expected_conf = 0.9 * CONTRADICTION_DECAY_MILD  # still above 0.2
        self.repo.update_fact_confidence.assert_called_with(21, expected_conf)
        self.repo.deactivate_fact.assert_not_called()

    def test_full_decay_when_new_confidence_ratio_high(self):
        """If new confidence >= 50% of old confidence, apply full decay."""
        old = UserFact(id=22, fact_key="工作", fact_value="医生", confidence=0.8)
        new = UserFact(fact_key="工作", fact_value="律师", confidence=0.5)
        # ratio = 0.5 / 0.8 = 0.625 >= 0.5 -> full decay

        deactivated = self.fc.resolve(new, old, self.repo)
        self.assertFalse(deactivated)
        expected_conf = 0.8 * CONTRADICTION_DECAY  # 0.32, above 0.2
        self.repo.update_fact_confidence.assert_called_with(22, expected_conf)


class TestKeywordFallback(unittest.TestCase):
    """FC-005: keyword-overlap semantic fallback without embedding."""

    def setUp(self):
        self.fc = FactChecker()  # no embedding engine

    def test_keyword_contradiction_detected(self):
        """Long similar keys with different values trigger keyword fallback."""
        existing = [
            UserFact(id=30, category="preference", fact_key="the favorite food of the user",
                     fact_value="pizza", confidence=0.8),
        ]
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="the favourite food of the user",
                     fact_value="sushi", confidence=0.7),
            existing,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 30)

    def test_keyword_same_value_not_contradiction(self):
        existing = [
            UserFact(id=31, category="preference", fact_key="the favorite food of the user",
                     fact_value="pizza", confidence=0.8),
        ]
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="the favourite food of the user",
                     fact_value="pizza", confidence=0.7),
            existing,
        )
        self.assertIsNone(result)

    def test_keyword_low_overlap_not_contradiction(self):
        existing = [
            UserFact(id=32, category="routine", fact_key="每天起床时间",
                     fact_value="8点", confidence=0.7),
        ]
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的音乐",
                     fact_value="摇滚", confidence=0.7),
            existing,
        )
        self.assertIsNone(result)

    def test_direct_contradiction_takes_precedence_over_keyword(self):
        existing = [
            UserFact(id=33, category="preference", fact_key="最喜欢的食物",
                     fact_value="意大利面", confidence=0.8),
        ]
        result = self.fc.detect_contradiction(
            UserFact(category="preference", fact_key="最喜欢的食物",
                     fact_value="寿司", confidence=0.7),
            existing,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 33)


class TestCosineSimBatch(unittest.TestCase):
    """FC-004: vectorised batch cosine similarity."""

    def test_batch_multiple_vectors(self):
        fc = FactChecker()
        new_vec = [1, 0, 0]
        old_vecs = [
            [1, 0, 0],   # identical
            [0, 1, 0],   # orthogonal
            [-1, 0, 0],  # opposite
        ]
        sims = fc._cosine_sim_batch(new_vec, old_vecs)
        self.assertAlmostEqual(float(sims[0]), 1.0, places=5)
        self.assertAlmostEqual(float(sims[1]), 0.0, places=5)
        self.assertAlmostEqual(float(sims[2]), -1.0, places=5)

    def test_batch_single_vector_matches_pairwise(self):
        fc = FactChecker()
        new_vec = [0.8, 0.6, 0.1]
        old_vecs = [[0.79, 0.61, 0.09]]
        batch_sim = float(fc._cosine_sim_batch(new_vec, old_vecs)[0])
        pairwise_sim = fc._cosine_sim(new_vec, old_vecs[0])
        self.assertAlmostEqual(batch_sim, pairwise_sim, places=5)

    def test_batch_zero_vector(self):
        fc = FactChecker()
        sims = fc._cosine_sim_batch([0, 0, 0], [[1, 1, 1]])
        self.assertEqual(float(sims[0]), 0.0)


if __name__ == "__main__":
    unittest.main()
