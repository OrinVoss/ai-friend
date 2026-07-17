"""Tests for core/proactivity.py — M-11 state persistence + #177 topic dedup."""
import os
import tempfile
import unittest

from core.proactivity import ProactivityManager
from tests.mocks import mock_ltm, mock_personality, mock_short_term


def _make_manager(state_dir=None, session_id="default"):
    return ProactivityManager(
        personality=mock_personality(),
        ltm=mock_ltm(),
        short_term=mock_short_term(),
        state_dir=state_dir,
        session_id=session_id,
    )


class TestProactivityPersistence(unittest.TestCase):
    """M-11: 限速/话题状态按 session 持久化，Web session 重建后不再清零。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_chat_rate_limit_restored_after_rebuild(self):
        """写入限速状态 → 新建 manager → 限速状态恢复。"""
        m1 = _make_manager(self._tmpdir)
        self.assertTrue(m1.check_rate_limit("chat"))
        m1.record_rate_limit("chat")
        self.assertFalse(m1.check_rate_limit("chat"))
        # 模拟 Web session 重建：新建 manager 后限速仍在
        m2 = _make_manager(self._tmpdir)
        self.assertFalse(m2.check_rate_limit("chat"))

    def test_explore_rate_limit_restored_after_rebuild(self):
        m1 = _make_manager(self._tmpdir)
        m1.record_rate_limit("explore")
        m2 = _make_manager(self._tmpdir)
        self.assertFalse(m2.check_rate_limit("explore"))
        # chat 与 explore 互不影响
        self.assertTrue(m2.check_rate_limit("chat"))

    def test_state_file_namespaced_by_session_id(self):
        m1 = _make_manager(self._tmpdir, session_id="小星")
        m1.record_rate_limit("chat")
        self.assertTrue(
            os.path.exists(os.path.join(self._tmpdir, ".proactivity_state.小星.json")))
        # 不同 session 的状态互不影响
        m2 = _make_manager(self._tmpdir, session_id="小明")
        self.assertTrue(m2.check_rate_limit("chat"))

    def test_corrupted_state_file_falls_back_silently(self):
        """状态文件损坏 → 静默降级为默认值，不抛异常。"""
        path = os.path.join(self._tmpdir, ".proactivity_state.default.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{这不是合法 json")
        m = _make_manager(self._tmpdir)
        self.assertTrue(m.check_rate_limit("chat"))
        self.assertTrue(m.check_rate_limit("explore"))
        self.assertEqual(m.get_recent_topics(), [])

    def test_wrong_shape_state_file_falls_back_silently(self):
        """JSON 合法但不是预期的 dict 结构 → 同样静默降级。"""
        path = os.path.join(self._tmpdir, ".proactivity_state.default.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")
        m = _make_manager(self._tmpdir)
        self.assertTrue(m.check_rate_limit("chat"))
        self.assertEqual(m.get_recent_topics(), [])

    def test_missing_state_file_uses_defaults(self):
        m = _make_manager(self._tmpdir)
        self.assertTrue(m.check_rate_limit("chat"))

    def test_save_failure_does_not_raise(self):
        """落盘失败（目录不存在）不炸主流程。"""
        m = _make_manager(os.path.join(self._tmpdir, "不存在的目录"))
        m.record_rate_limit("chat")  # 不应抛异常
        self.assertFalse(m.check_rate_limit("chat"))  # 内存状态仍生效


class TestRecordTopic(unittest.TestCase):
    """#177: record_topic 去重队列行为。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_record_topic_appends_and_dedups(self):
        m = _make_manager(self._tmpdir)
        m.record_topic("天气")
        m.record_topic("音乐")
        m.record_topic("天气")  # 重复：移到最新位置，不产生重复项
        self.assertEqual(m.get_recent_topics(), ["音乐", "天气"])

    def test_record_topic_maxlen_evicts_oldest(self):
        m = _make_manager(self._tmpdir)
        for t in ["t1", "t2", "t3", "t4", "t5", "t6"]:
            m.record_topic(t)
        # maxlen=5：最老的 t1 被淘汰
        self.assertEqual(m.get_recent_topics(), ["t2", "t3", "t4", "t5", "t6"])

    def test_record_topic_ignores_empty(self):
        m = _make_manager(self._tmpdir)
        m.record_topic("")
        m.record_topic(None)
        m.record_topic("   ")
        self.assertEqual(m.get_recent_topics(), [])

    def test_record_topic_persisted(self):
        m1 = _make_manager(self._tmpdir)
        m1.record_topic("旅行")
        m2 = _make_manager(self._tmpdir)
        self.assertEqual(m2.get_recent_topics(), ["旅行"])

    def test_pick_proactive_topic_persisted(self):
        """fallback 路径选中的话题也随状态落盘。"""
        m1 = _make_manager(self._tmpdir)
        chosen = m1.pick_proactive_topic()
        m2 = _make_manager(self._tmpdir)
        self.assertIn(chosen, m2.get_recent_topics())


if __name__ == "__main__":
    unittest.main()
