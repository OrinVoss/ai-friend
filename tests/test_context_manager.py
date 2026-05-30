"""Tests for core/context_manager.py"""
import unittest
from unittest.mock import MagicMock

from core.context_manager import ContextManager, estimate_tokens, COMPRESS_THRESHOLD


class TestEstimateTokens(unittest.TestCase):
    def test_english(self):
        result = estimate_tokens("hello world")
        self.assertGreater(result, 0)

    def test_chinese(self):
        result = estimate_tokens("你好世界")
        self.assertGreater(result, 0)

    def test_empty(self):
        result = estimate_tokens("")
        self.assertGreaterEqual(result, 0)

    def test_mixed(self):
        result = estimate_tokens("hello 你好 123")
        self.assertGreater(result, 0)


class TestContextManager(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.generate.return_value = "compressed summary text"
        self.short_term = MagicMock()

    def test_init_defaults(self):
        cm = ContextManager(self.provider, self.short_term)
        self.assertEqual(cm.compressed_summary, "")
        self.assertEqual(cm.estimated_tokens, 0)

    def test_reset_estimate(self):
        cm = ContextManager(self.provider, self.short_term)
        cm.reset_estimate(100)
        self.assertEqual(cm.estimated_tokens, 100)

    def test_add_estimate(self):
        cm = ContextManager(self.provider, self.short_term)
        cm.add_estimate(50)
        cm.add_estimate(30)
        self.assertEqual(cm.estimated_tokens, 80)

    def test_compress_updates_summary(self):
        cm = ContextManager(self.provider, self.short_term)
        cm.compress([{"role": "user", "content": "test message"}])
        self.assertNotEqual(cm.compressed_summary, "")
        self.short_term.clear.assert_called_once()

    def test_compress_recursion_guard(self):
        cm = ContextManager(self.provider, self.short_term)
        cm._compressing = True
        cm.compress([{"role": "user", "content": "test"}])
        self.provider.generate.assert_not_called()

    def test_compress_empty_messages(self):
        cm = ContextManager(self.provider, self.short_term)
        cm.compress([{"role": "system", "content": "system only"}])
        # System-only messages should not trigger LLM call
        # because _do_compress filters them out

    def test_compress_failure_handling(self):
        self.provider.generate.side_effect = RuntimeError("API error")
        cm = ContextManager(self.provider, self.short_term)
        cm.compress([{"role": "user", "content": "test"}])
        # Should not crash and not crash
        self.assertEqual(cm.compressed_summary, "")

    def test_compress_threshold(self):
        self.assertGreater(COMPRESS_THRESHOLD, 0)


if __name__ == "__main__":
    unittest.main()
