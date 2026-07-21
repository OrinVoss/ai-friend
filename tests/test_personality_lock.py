"""#291: Personality.save() 与情绪突变的并发安全测试。"""
import json
import logging
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from core.personality import Personality
from models.personality import PersonalityConfig


class TestPersonalitySaveLock(unittest.TestCase):
    """多线程同时对同一 Personality 执行 save() 与情绪突变。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self._tmpdir, "role.json")
        self.p = Personality(PersonalityConfig())

    def test_concurrent_save_and_mutation(self):
        errors = []

        def mutator():
            try:
                for i in range(200):
                    self.p.apply_emotional_shift(
                        0.9 if i % 2 == 0 else -0.9, topic_energy=0.9)
                    self.p.record_emotion_event(trigger=f"事件{i}", context="并发测试")
                    self.p.set_consecutive_negative(i % 5)
                    self.p.decay_emotion()
            except Exception as e:
                errors.append(e)

        def saver():
            try:
                for _ in range(100):
                    self.p.save(self.path)
            except Exception as e:
                errors.append(e)

        # save() 会把异常吞进 logger.warning——挂上探针，确保没有 RuntimeError
        # （asdict 深拷贝 deque/list 时另一线程正在突变）被悄悄吞掉。
        personality_logger = logging.getLogger("core.personality")
        with patch.object(personality_logger, "warning") as mock_warning:
            threads = (
                [threading.Thread(target=mutator) for _ in range(3)]
                + [threading.Thread(target=saver) for _ in range(3)]
            )
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        mock_warning.assert_not_called()

        # 写出的 JSON 必须可解析且 emotional_state 结构完整（非撕裂快照）
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("personality", data)
        self.assertIn("emotional_state", data)
        es = data["emotional_state"]
        for key in ("valence", "arousal", "emotion_events", "history",
                    "consecutive_negative", "dominant_emotion"):
            self.assertIn(key, es)
        self.assertIsInstance(es["emotion_events"], list)
        self.assertIsInstance(es["history"], list)

    def test_save_to_dict_reentrant(self):
        """save() 内部会调用 to_dict()，RLock 必须允许同线程重入。"""
        self.p.apply_emotional_shift(0.5, topic_energy=0.5)
        self.p.save(self.path)
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("emotional_state", data)


if __name__ == "__main__":
    unittest.main()
