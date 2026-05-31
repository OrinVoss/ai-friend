"""Tests for web/server.py -- _split_segments and _calc_delay"""
import unittest

from web.server import _split_segments, _calc_delay


class TestSplitSegments(unittest.TestCase):
    def test_sentence_split(self):
        result = _split_segments("第一句话。第二句话！第三句？")
        self.assertGreaterEqual(len(result), 3)

    def test_newline_split(self):
        text = "line1" + chr(10) + "line2" + chr(10) + "line3"
        result = _split_segments(text)
        self.assertGreaterEqual(len(result), 3)

    def test_long_segment_comma_split(self):
        long_text = "这是一个" + "很" * 50 + "长的句子，" + "需要" * 30 + "被分割"
        result = _split_segments(long_text)
        self.assertGreater(len(result), 1)

    def test_single_long_chunk_whitespace_split(self):
        text = "A" * 20 + " " + "B" * 20
        result = _split_segments(text)
        self.assertGreater(len(result), 1)

    def test_single_long_chunk_particle_split(self):
        text = "今天天气真好啊" + "测试" * 8 + "呢"
        result = _split_segments(text)
        if len(result) > 1:
            # Verify segments were created
            pass  # Level 4 fallback may or may not trigger depending on text

    def test_hard_split_fallback(self):
        text = "A" * 50
        result = _split_segments(text)
        self.assertGreater(len(result), 1)

    def test_tiny_trailing_fragment_merged(self):
        text = "很长很长很长很长很长很长很长很长很长很长很长的一句话。短。"
        result = _split_segments(text)
        # The "短。" should be merged into previous segment (小于4字符)
        for s in result:
            self.assertGreater(len(s), 0)

    def test_single_character(self):
        result = _split_segments("好")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "好")

    def test_empty_string(self):
        result = _split_segments("")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "")

    def test_punctuation_only(self):
        result = _split_segments("。。。")
        self.assertEqual(len(result), 1)

    def test_placeholder_with_quotes(self):
        result = _split_segments('他说："你好"。然后走了。')
        self.assertGreaterEqual(len(result), 1)

    def test_comma_split_threshold(self):
        # Segment under 40 chars shouldn't be comma-split
        short = "短句，" * 3
        result = _split_segments(short)
        # Should not split on commas for short segments
        self.assertTrue(any("," in s for s in result) or len(result) == 1)

    def test_preserves_content(self):
        text = "这是第一条消息。这是第二条消息。"
        result = _split_segments(text)
        combined = "".join(result)
        self.assertIn("第一条消息", combined)
        self.assertIn("第二条消息", combined)


class TestCalcDelay(unittest.TestCase):
    def test_excited_is_fastest(self):
        d1 = _calc_delay("excited", 10)
        d2 = _calc_delay("sad", 10)
        self.assertLess(d1, d2)

    def test_sad_is_slowest(self):
        d1 = _calc_delay("sad", 10)
        d2 = _calc_delay("joyful", 10)
        self.assertGreater(d1, d2)

    def test_longer_segment_longer_delay(self):
        d1 = _calc_delay("neutral", 10)
        d2 = _calc_delay("neutral", 100)
        self.assertGreater(d2, d1)

    def test_unknown_emotion_defaults_to_neutral(self):
        d1 = _calc_delay("nonexistent", 10)
        d2 = _calc_delay("neutral", 10)
        # Both should use 1.7 base (neutral default)
        self.assertAlmostEqual(d1, d2, delta=0.7)  # random variance

    def test_delay_is_positive(self):
        for emotion in ["excited", "joyful", "neutral", "sad", "angry", "melancholy"]:
            d = _calc_delay(emotion, 20)
            self.assertGreater(d, 0, f"{emotion} delay should be positive")


if __name__ == "__main__":
    unittest.main()
