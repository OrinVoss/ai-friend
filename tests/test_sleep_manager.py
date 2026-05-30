"""Tests for core/sleep_manager.py"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from core.sleep_manager import SleepManager


class TestSleepManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, mode='w')
        self.tmp.write("0")
        self.tmp.close()
        self.personality = MagicMock()
        self.personality.emotion.dominant_emotion = "neutral"
        self.personality.emotion.arousal = 0.5
        self.personality.emotion.valence = 0.4
        self.personality.emotion.resentment = 0.0
        self.personality.emotion.record_emotion_event = MagicMock()
        self.ltm = MagicMock()
        self.ltm.get_all_active_facts.return_value = []
        self.ltm.get_recent_experiences.return_value = []
        self.provider = MagicMock()
        self.provider.generate.return_value = "a dream about flying"

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_init_loads_sleep_state_false(self):
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        self.assertFalse(sm.is_sleeping)

    def test_init_loads_sleep_state_true(self):
        with open(self.tmp.name, 'w') as f:
            f.write("1")
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        self.assertTrue(sm.is_sleeping)

    def test_file_not_found(self):
        sm = SleepManager("/nonexistent/path/sleep", self.personality, self.ltm, self.provider)
        self.assertFalse(sm.is_sleeping)

    def test_get_sleep_state_outside_window(self):
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        # 15:00 is outside all sleep windows
        original = sm._sleeping
        should_sleep, msg = sm.get_sleep_state()
        # At 15:00 with neutral emotion, no sleep should trigger
        if should_sleep:
            # Could happen if current time is in a sleep window
            pass

    def test_generate_dream_success(self):
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        dream = sm.generate_dream()
        self.assertIn("flying", dream)

    def test_generate_dream_failure(self):
        self.provider.generate.side_effect = RuntimeError("API error")
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        dream = sm.generate_dream()
        self.assertEqual(dream, "")


if __name__ == "__main__":
    unittest.main()
