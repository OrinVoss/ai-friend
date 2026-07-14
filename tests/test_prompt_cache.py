"""Tests for core/prompt_cache.py"""
import os
import tempfile
import time
import unittest

from core.prompt_cache import PromptCache


class TestPromptCache(unittest.TestCase):
    def test_static_block_no_ttl(self):
        cache = PromptCache()
        calls = []

        def builder():
            calls.append(1)
            return "identity block"

        v1 = cache.get_or_build("sid", "v1", "identity", builder, ttl=None)
        v2 = cache.get_or_build("sid", "v1", "identity", builder, ttl=None)
        self.assertEqual(v1, "identity block")
        self.assertEqual(v2, "identity block")
        self.assertEqual(len(calls), 1)

    def test_slow_block_ttl_expires(self):
        cache = PromptCache()
        calls = []

        def builder():
            calls.append(1)
            return "memory block"

        v1 = cache.get_or_build("sid", "v1", "memory", builder, ttl=0.05)
        time.sleep(0.06)
        v2 = cache.get_or_build("sid", "v1", "memory", builder, ttl=0.05)
        self.assertEqual(v1, "memory block")
        self.assertEqual(v2, "memory block")
        self.assertEqual(len(calls), 2)

    def test_personality_change_invalidates_static_block(self):
        cache = PromptCache()
        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as f:
            f.write("{}")
            path = f.name
        try:
            v1 = cache.personality_version(path)
            calls = []

            def builder():
                calls.append(1)
                return "identity"

            cache.get_or_build("sid", v1, "identity", builder, ttl=None)
            # Modify the personality file to bump mtime.
            time.sleep(0.01)
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"name": "new"}')
            v2 = cache.personality_version(path)
            self.assertNotEqual(v1, v2)
            cache.get_or_build("sid", v2, "identity", builder, ttl=None)
            self.assertEqual(len(calls), 2)
        finally:
            os.unlink(path)

    def test_invalidate_by_session(self):
        cache = PromptCache()
        cache._store[("a", "v", "x")] = ("val", 0, None)
        cache._store[("b", "v", "x")] = ("val", 0, None)
        removed = cache.invalidate(session_id="a")
        self.assertEqual(removed, 1)
        self.assertIn(("b", "v", "x"), cache._store)

    def test_clear(self):
        cache = PromptCache()
        cache._store[("a", "v", "x")] = ("val", 0, None)
        cache.clear()
        self.assertEqual(len(cache._store), 0)


if __name__ == "__main__":
    unittest.main()
