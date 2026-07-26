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


class TestGeneralWakeFailsafe(unittest.TestCase):
    """SL-012: 睡到所有合法睡眠时段之外时强制唤醒兜底。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, mode='w')
        self.tmp.write("1")  # 已睡着
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
        self.provider.generate.return_value = "a dream"

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _run_at(self, hour, minute=0):
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, self.provider)
        with patch("core.sleep_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 20, hour, minute)
            return sm, asyncio.run(sm.get_sleep_state())

    def test_sleeping_at_1134_force_wakes(self):
        # 11:34 错过晨醒(7-10)与强制窗口(10-11)，旧逻辑睡到 13:10 才醒
        sm, (should_sleep, msg) = self._run_at(11, 34)
        self.assertFalse(sm.is_sleeping)
        self.assertFalse(should_sleep)
        self.assertIsNotNone(msg)  # 唤醒消息
        with open(self.tmp.name) as f:
            self.assertEqual(f.read().strip(), "0")

    def test_sleeping_at_1630_force_wakes(self):
        # 16:30 午睡合法时段也已过
        sm, (_, msg) = self._run_at(16, 30)
        self.assertFalse(sm.is_sleeping)
        self.assertIsNotNone(msg)

    def test_sleeping_at_0130_stays_asleep(self):
        # 凌晨 1:30 仍在夜间合法时段，不应被兜底唤醒
        sm, (should_sleep, msg) = self._run_at(1, 30)
        self.assertTrue(sm.is_sleeping)
        self.assertIsNone(msg)

    def test_sleeping_at_1330_stays_asleep(self):
        # 13:30 在午睡合法时段内（午醒窗口 13.16-16 自行处理），兜底不触发
        with patch("core.sleep_manager.random.random", return_value=1.0):
            sm, (should_sleep, msg) = self._run_at(13, 30)
        self.assertTrue(sm.is_sleeping)
        self.assertIsNone(msg)


class TestDreamGeneratedOutsideLock(unittest.TestCase):
    """SL-002 不变量：generate_dream 的 await 绝不发生在 _lock 持有期间。
    行为级验证：梦境生成（慢的 provider.generate）进行中，另一个线程必须
    能立即拿到 _lock——若 await 在锁内，锁会被占满整个生成时长。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, mode='w')
        self.tmp.write("1")  # 已睡着，走唤醒路径
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

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_lock_free_during_slow_dream(self):
        import time
        generate_started = threading.Event()

        def slow_generate(*args, **kwargs):
            generate_started.set()
            time.sleep(0.5)  # 模拟慢 LLM 调用
            return "a slow dream"

        provider = MagicMock()
        provider.generate.side_effect = slow_generate
        sm = SleepManager(self.tmp.name, self.personality, self.ltm, provider)
        sm._MIN_SLEEP_INTERVAL = 0  # 绕过 #167 冷却

        result = {}

        def run_tick():
            with patch("core.sleep_manager.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 7, 20, 10, 30)  # 强制唤醒窗
                result["out"] = asyncio.run(sm.get_sleep_state())

        t = threading.Thread(target=run_tick)
        t.start()
        self.assertTrue(generate_started.wait(timeout=5), "梦境生成未开始")

        # 梦境还在生成中（0.5s 慢调用），锁必须能立即拿到
        t0 = time.monotonic()
        acquired = sm._lock.acquire(timeout=2.0)
        elapsed = time.monotonic() - t0
        if acquired:
            sm._lock.release()
        t.join(timeout=10)

        self.assertTrue(acquired, "梦境生成期间 _lock 被持有（await 发生在锁内）")
        self.assertLess(elapsed, 0.3,
                        f"锁等待 {elapsed:.2f}s，接近梦境时长——await 疑似在锁内")
        # 功能仍正确：唤醒消息包含慢梦境
        self.assertIn("a slow dream", result["out"][1])
