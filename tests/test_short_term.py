"""Tests for memory/short_term.py — ConversationBuffer.format_for_prompt."""
import unittest

from memory.short_term import ConversationBuffer


class TestFormatForPrompt(unittest.TestCase):
    def test_sleep_turns_excluded(self):
        buf = ConversationBuffer(maxlen=20)
        buf.add_turn("user", "你好")
        buf.add_turn("assistant", "我去午睡一会儿...困了", metadata={"sleep": True})
        buf.add_turn("assistant", "zzzz...（小声梦话）", metadata={"sleep": True})
        buf.add_turn("user", "醒了吗")
        out = buf.format_for_prompt()
        self.assertIn("你好", out)
        self.assertIn("醒了吗", out)
        self.assertNotIn("午睡", out)
        self.assertNotIn("zzzz", out)

    def test_sleep_turns_still_in_buffer(self):
        # 过滤只影响 prompt，缓冲内容（consolidation 等消费方）不受影响
        buf = ConversationBuffer(maxlen=20)
        buf.add_turn("assistant", "晚安", metadata={"sleep": True})
        self.assertEqual(len(buf.get_all()), 1)

    def test_consecutive_duplicates_merged(self):
        buf = ConversationBuffer(maxlen=20)
        for _ in range(4):
            buf.add_turn("user", "你好")
        buf.add_turn("assistant", "在呢")
        out = buf.format_for_prompt()
        self.assertEqual(out.count("用户: 你好"), 1)
        self.assertIn("在呢", out)

    def test_non_consecutive_duplicates_kept(self):
        buf = ConversationBuffer(maxlen=20)
        buf.add_turn("user", "你好")
        buf.add_turn("assistant", "在呢")
        buf.add_turn("user", "你好")
        out = buf.format_for_prompt()
        self.assertEqual(out.count("用户: 你好"), 2)

    def test_assistant_label_preserved(self):
        buf = ConversationBuffer(maxlen=20)
        buf.add_turn("assistant", "要不我给您念段《国际歌》当BGM？")
        buf.add_turn("user", "本地有这个歌吗")
        out = buf.format_for_prompt()
        self.assertIn("国际歌", out)
        self.assertTrue(out.rstrip().endswith("本地有这个歌吗"))


if __name__ == "__main__":
    unittest.main()
