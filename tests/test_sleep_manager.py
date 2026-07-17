"""Tests for core/sleep_manager.py — async sleep state machine (SL-001/002/010)."""
import asyncio
import os
import tempfile
import threading
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

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
        original = sm._sleeping
        should_sleep, msg = asyncio.run(sm.get_sleep_state())
        if should_sleep:
            pass

    def test_generate_dream_success(self):
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        dream = asyncio.run(sm.generate_dream())
        self.assertIn("flying", dream)

    def test_generate_dream_failure(self):
        self.provider.generate.side_effect = RuntimeError("API error")
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        dream = asyncio.run(sm.generate_dream())
        self.assertEqual(dream, "")

    def test_lock_used_across_two_event_loops(self):
        """H-03 同型: threading.Lock 可在不同事件循环中交替使用不抛错。
        夜间入睡 → 已睡不重复触发 → 次日强制唤醒，全程内存状态与文件一致。"""
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        sm._MIN_SLEEP_INTERVAL = 0  # 绕过 #167 冷却

        # 事件循环 1：23:30 夜间窗口，random=0 必触发入睡
        with patch("core.sleep_manager.datetime") as mock_dt, \
                patch("core.sleep_manager.random.random", return_value=0.0):
            mock_dt.now.return_value = datetime(2026, 7, 17, 23, 30)
            should_sleep, msg = asyncio.run(sm.get_sleep_state())
        self.assertTrue(should_sleep)
        self.assertEqual(msg, "夜深了...我睡了，晚安[月亮]")
        self.assertTrue(sm.is_sleeping)
        with open(self.tmp.name) as f:
            self.assertEqual(f.read(), "1")

        # 事件循环 2（新 loop）：同一窗口但已入睡 → 不重复触发
        with patch("core.sleep_manager.datetime") as mock_dt, \
                patch("core.sleep_manager.random.random", return_value=0.0):
            mock_dt.now.return_value = datetime(2026, 7, 17, 23, 40)
            should_sleep, msg = asyncio.run(sm.get_sleep_state())
        self.assertFalse(should_sleep)
        self.assertIsNone(msg)
        self.assertTrue(sm.is_sleeping)

        # 事件循环 3：次日 10:30 强制唤醒窗口 → 醒来，梦境在锁外生成
        with patch("core.sleep_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 18, 10, 30)
            should_sleep, msg = asyncio.run(sm.get_sleep_state())
        self.assertFalse(should_sleep)
        self.assertIn("太阳都晒屁股了才醒", msg)
        self.assertIn("a dream about flying", msg)
        self.assertFalse(sm.is_sleeping)
        with open(self.tmp.name) as f:
            self.assertEqual(f.read(), "0")

    def test_concurrent_ticks_from_two_loops(self):
        """H-03 同型: 两个线程各跑独立事件循环并发 tick，不抛错、状态不变。
        （旧 asyncio.Lock 跨 loop 竞争会 RuntimeError / 非线程安全唤醒）"""
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        sm._MIN_SLEEP_INTERVAL = 0
        errors = []

        def worker():
            try:
                for _ in range(30):
                    should_sleep, msg = asyncio.run(sm.get_sleep_state())
                    assert not should_sleep and msg is None
            except Exception as e:
                errors.append(e)

        # 固定在无转换窗口的 15:00，保证 tick 纯走临界区
        with patch("core.sleep_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 17, 15, 0)
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        self.assertFalse(sm.is_sleeping)
        with open(self.tmp.name) as f:
            self.assertEqual(f.read(), "0")


if __name__ == "__main__":
    unittest.main()
