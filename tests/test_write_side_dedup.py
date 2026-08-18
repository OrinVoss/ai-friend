"""写入侧近重复去重（2026-08-18 监控发现：逐字/近逐字重复体验、挂念并存）。

覆盖：utils.shingle_similarity 覆盖率语义；InnerDriveState 挂念近重复跳过；
LongTermMemory.store_experience 近重复跳过（consolidation 与梦境共用此路径）。
"""
import unittest
from unittest.mock import AsyncMock, MagicMock

from utils import shingle_similarity

# 监控里的真实近重复对（挂念清单）
CARE_A = "用户科目三第三次挂科，情绪低落，需要持续陪伴和关心"
CARE_B = "用户科目三挂了三次，情绪低落，需要持续陪伴和关心"


class TestShingleSimilarity(unittest.TestCase):
    def test_exact(self):
        self.assertAlmostEqual(shingle_similarity("我喜欢喝咖啡", "我喜欢喝咖啡"), 1.0)

    def test_monitor_pair_is_near_dup(self):
        self.assertGreaterEqual(shingle_similarity(CARE_A, CARE_B), 0.7)

    def test_distinct(self):
        self.assertLess(shingle_similarity("喜欢摄影构图", "明天要开会"), 0.5)

    def test_empty(self):
        self.assertEqual(shingle_similarity("", "x"), 0.0)
        self.assertEqual(shingle_similarity("", ""), 1.0)


class TestCareNearDup(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()

    def _state(self, sid="dedup"):
        from core.inner_drive_state import InnerDriveState
        return InnerDriveState(sid, state_dir=self.dir)

    def test_near_dup_skipped(self):
        s = self._state()
        s.apply_updates(add=[CARE_A])
        s.apply_updates(add=[CARE_B])
        self.assertEqual(len(s.entries()), 1)

    def test_distinct_kept(self):
        s = self._state("dedup2")
        s.apply_updates(add=["关心用户考试", "用户喜欢摄影"])
        self.assertEqual(len(s.entries()), 2)


class TestExperienceDedup(unittest.TestCase):
    def _ltm(self, recent):
        from memory.long_term import LongTermMemory
        repo = MagicMock()
        repo.get_recent_experiences = AsyncMock(return_value=recent)
        repo.insert_experience = AsyncMock(return_value=42)
        return LongTermMemory(repo), repo

    def test_verbatim_dup_skipped(self):
        existing = MagicMock(summary="用户在情绪低落时以“随便”回应吃饭提议")
        ltm, repo = self._ltm([existing])
        rid = ltm.store_experience("用户在情绪低落时以“随便”回应吃饭提议",
                                   "温暖", 0.6, ["测试"], 1, 2, 0.5)
        self.assertEqual(rid, 0)
        repo.insert_experience.assert_not_called()

    def test_new_experience_stored(self):
        existing = MagicMock(summary="用户喜欢摄影构图")
        ltm, repo = self._ltm([existing])
        rid = ltm.store_experience("用户科目三挂了三次，AI 陪伴安慰",
                                   "委屈", 0.8, ["考试"], 1, 2, 0.6)
        self.assertEqual(rid, 42)
        repo.insert_experience.assert_called_once()


if __name__ == "__main__":
    unittest.main()
