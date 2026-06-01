"""Tests for memory/retrieval.py — keyword scoring with confidence (#6)."""
import unittest

from models.memory import UserFact
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


if __name__ == "__main__":
    unittest.main()
