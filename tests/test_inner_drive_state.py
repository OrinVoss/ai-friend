"""Tests for core/inner_drive_state.py — 一期 minimal care list + 二期 typed
entries / lifecycle / surface rules / semantic surfacing."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from core.inner_drive_state import DriveEntry, InnerDriveState


def _unit(vec):
    v = np.array(vec, dtype=np.float32)
    return v / np.linalg.norm(v)


class _FakeEmbed:
    """Deterministic embed mock: maps exact text to fixed vectors."""
    def __init__(self, mapping):
        self.mapping = mapping

    def encode_single(self, text):
        return self.mapping[text]


class TestInnerDriveState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, max_entries=20, session="test"):
        return InnerDriveState(session, max_entries=max_entries,
                               state_dir=self.dir)

    def test_add_and_entries(self):
        s = self._state()
        s.apply_updates(add=["问问用户考试结果", "用户妹妹的高考"])
        self.assertEqual(s.entries(), ["问问用户考试结果", "用户妹妹的高考"])

    def test_add_dedup_and_blank(self):
        s = self._state()
        s.apply_updates(add=["挂念A", "挂念A", "  ", ""])
        self.assertEqual(s.entries(), ["挂念A"])

    def test_remove(self):
        s = self._state()
        s.apply_updates(add=["挂念A", "挂念B", "挂念C"])
        s.apply_updates(remove=["挂念B"])
        self.assertEqual(s.entries(), ["挂念A", "挂念C"])

    def test_fifo_eviction(self):
        s = self._state(max_entries=3)
        s.apply_updates(add=["一", "二", "三", "四", "五"])
        self.assertEqual(s.entries(), ["三", "四", "五"])

    def test_persistence_across_instances(self):
        self._state().apply_updates(add=["跨触发持久的挂念"])
        s2 = self._state()
        self.assertEqual(s2.entries(), ["跨触发持久的挂念"])

    def test_corrupt_file_degrades_to_empty(self):
        import pathlib
        path = pathlib.Path(self.dir) / ".inner_drive_state.test"
        path.write_text("{not valid json", encoding="utf-8")
        s = self._state()
        self.assertEqual(s.entries(), [])
        # and the state still works afterwards
        s.apply_updates(add=["恢复写入"])
        self.assertEqual(s.entries(), ["恢复写入"])

    def test_empty_updates_noop(self):
        s = self._state()
        s.apply_updates()
        s.apply_updates(add=None, remove=None)
        self.assertEqual(s.entries(), [])


class TestTypedEntries(unittest.TestCase):
    """二期：类型化条目 + v1 迁移。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, **kw):
        return InnerDriveState("t2", state_dir=self.dir, **kw)

    def test_add_typed_dict(self):
        s = self._state()
        future = (datetime.now() + timedelta(hours=3)).isoformat()
        s.apply_updates(add=[{"content": "用户明天面试，晚上问结果",
                              "type": "plan", "priority": 0.9,
                              "expires_at": future}])
        entries = s.active_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].type, "plan")
        self.assertEqual(entries[0].priority, 0.9)
        self.assertEqual(entries[0].expires_at, future)

    def test_invalid_type_defaults_care(self):
        s = self._state()
        s.apply_updates(add=[{"content": "某条挂念", "type": "weird"}])
        self.assertEqual(s.active_entries()[0].type, "care")

    def test_v1_migration(self):
        import pathlib
        path = pathlib.Path(self.dir) / ".inner_drive_state.t2"
        path.write_text(json.dumps({"care_list": [
            {"content": "旧挂念", "created_at": "2026-07-17T10:00:00"}]},
            ensure_ascii=False), encoding="utf-8")
        s = self._state()
        entries = s.active_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].content, "旧挂念")
        self.assertEqual(entries[0].type, "care")
        self.assertEqual(entries[0].status, "active")


class TestSurfaceRules(unittest.TestCase):
    """二期：浮现规则（pin / 情绪加权 / 衰减 / 过期 / 归档）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, **kw):
        return InnerDriveState("t3", state_dir=self.dir, **kw)

    def test_plan_near_expiry_pinned_top(self):
        s = self._state()
        s.apply_updates(add=[
            {"content": "高优先级挂念", "type": "care", "priority": 0.9},
            {"content": "用户 3 小时后面试", "type": "plan", "priority": 0.1,
             "expires_at": (datetime.now() + timedelta(hours=3)).isoformat()},
        ])
        picked = s.surface()
        self.assertEqual(picked[0].content, "用户 3 小时后面试")

    def test_emotion_weighting_low_valence_boosts_care(self):
        s = self._state()
        s.apply_updates(add=[
            {"content": "灵感：分享一首歌", "type": "idea", "priority": 0.5},
            {"content": "关心用户失眠", "type": "care", "priority": 0.5},
        ])
        sad = SimpleNamespace(valence=-0.5, arousal=0.4)
        picked = s.surface(emotion=sad)
        self.assertEqual(picked[0].content, "关心用户失眠")

    def test_surface_decays_priority(self):
        s = self._state()
        s.apply_updates(add=["反复想到的挂念"])
        s.surface()
        s.surface()
        e = s.active_entries()[0]
        self.assertAlmostEqual(e.priority, round(0.5 * 0.9 * 0.9, 4))
        self.assertEqual(e.surface_count, 2)

    def test_expired_plan_not_surfaced(self):
        s = self._state()
        s.apply_updates(add=[
            {"content": "昨天的约定", "type": "plan",
             "expires_at": (datetime.now() - timedelta(hours=1)).isoformat()},
        ])
        self.assertEqual(s.surface(), [])
        self.assertEqual(s.active_entries(), [])

    def test_low_priority_archived_as_decayed(self):
        s = self._state(decay_rate=0.1)
        s.apply_updates(add=["空谈挂念"])
        s.surface()  # 0.5 * 0.1 = 0.05 < 0.2 → decayed
        self.assertEqual(s.active_entries(), [])

    def test_eviction_clears_inactive_first(self):
        s = self._state(max_entries=2)
        s.apply_updates(add=["A", "B"])
        a_id = s.active_entries()[0].id
        s.resolve(a_id, "已完成")
        s.apply_updates(add=["C"])  # 超容量 → 先清 resolved 的 A
        s.apply_updates(add=["D"])  # 再超 → 清最低 priority 的活跃 B
        contents = [e.content for e in s._entries]
        self.assertNotIn("A", contents)
        self.assertNotIn("B", contents)
        self.assertEqual(sorted(contents), ["C", "D"])


class TestSemanticSurface(unittest.TestCase):
    """二期 4.2：surface_for_query 语义浮现 + consolidation 对照解决。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.e1 = _unit([1, 0, 0, 0])
        self.e2 = _unit([0, 1, 0, 0])

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, mapping, **kw):
        return InnerDriveState("t4", state_dir=self.dir,
                               embedding_engine=_FakeEmbed(mapping), **kw)

    def test_surface_for_query_hit(self):
        s = self._state({"问问妹妹高考成绩": self.e1, "我妹妹成绩出来了": self.e1})
        s.apply_updates(add=["问问妹妹高考成绩"])
        hits = s.surface_for_query("我妹妹成绩出来了")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].content, "问问妹妹高考成绩")

    def test_surface_for_query_miss(self):
        s = self._state({"问问妹妹高考成绩": self.e1, "完全无关的话题": self.e2})
        s.apply_updates(add=["问问妹妹高考成绩"])
        self.assertEqual(s.surface_for_query("完全无关的话题"), [])

    def test_surface_for_query_no_engine(self):
        s = InnerDriveState("t4b", state_dir=self.dir)
        s.apply_updates(add=["挂念"])
        self.assertEqual(s.surface_for_query("任意"), [])

    def test_response_surface_does_not_decay(self):
        s = self._state({"挂念A": self.e1, "相关消息": self.e1})
        s.apply_updates(add=["挂念A"])
        s.surface_for_query("相关消息")
        e = s.active_entries()[0]
        self.assertEqual(e.priority, 0.5)
        self.assertEqual(e.surface_count, 0)

    def test_resolve_matching_marks_resolved(self):
        s = self._state({"问问妹妹高考成绩": self.e1, "我妹妹成绩出来了": self.e1})
        s.apply_updates(add=["问问妹妹高考成绩"])
        n = s.resolve_matching("我妹妹成绩出来了")
        self.assertEqual(n, 1)
        self.assertEqual(s.entries(), [])  # 不再活跃
        resolved = [e for e in s._entries if e.status == "resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertIn("相似度", resolved[0].resolution)

    def test_resolve_matching_no_match(self):
        s = self._state({"问问妹妹高考成绩": self.e1, "无关内容": self.e2})
        s.apply_updates(add=["问问妹妹高考成绩"])
        self.assertEqual(s.resolve_matching("无关内容"), 0)
        self.assertEqual(s.entries(), ["问问妹妹高考成绩"])


class TestRecordOutcome(unittest.TestCase):
    """L4-6a: 反馈闭环对 priority 与 resolved 的影响。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self):
        return InnerDriveState("outcome", state_dir=self.dir)

    def test_positive_boosts_same_type_priority(self):
        s = self._state()
        s.apply_updates(add=[
            {"content": "关心用户面试", "type": "care", "priority": 0.5},
            {"content": "另一个挂念", "type": "care", "priority": 0.5},
            {"content": "无关好奇", "type": "curiosity", "priority": 0.5},
        ])
        entry_id = s.active_entries()[0].id
        self.assertTrue(s.record_outcome(entry_id, positive=True))
        # The driven entry is resolved; the other care entry is boosted.
        care_priorities = [e.priority for e in s.active_entries() if e.type == "care"]
        self.assertEqual(care_priorities, [0.55])
        # curiosity unaffected
        self.assertEqual([e.priority for e in s.active_entries() if e.type == "curiosity"], [0.5])

    def test_negative_dampens_same_type_priority(self):
        s = self._state()
        s.apply_updates(add=[{"content": "关心用户面试", "type": "care", "priority": 0.5}])
        entry_id = s.active_entries()[0].id
        self.assertTrue(s.record_outcome(entry_id, positive=False))
        resolved = [e for e in s._entries if e.status == "resolved"][0]
        self.assertAlmostEqual(resolved.priority, 0.45)

    def test_positive_caps_at_one(self):
        s = self._state()
        s.apply_updates(add=[{"content": "高优先级", "type": "care", "priority": 0.98}])
        entry_id = s.active_entries()[0].id
        s.record_outcome(entry_id, positive=True)
        resolved = [e for e in s._entries if e.status == "resolved"][0]
        self.assertAlmostEqual(resolved.priority, 1.0)

    def test_records_resolution(self):
        s = self._state()
        s.apply_updates(add=[{"content": "关心用户面试", "type": "care", "priority": 0.5}])
        entry_id = s.active_entries()[0].id
        s.record_outcome(entry_id, positive=True)
        resolved = [e for e in s._entries if e.status == "resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertIn("积极", resolved[0].resolution)

    def test_missing_entry_noop(self):
        s = self._state()
        self.assertFalse(s.record_outcome("nonexistent", positive=True))


if __name__ == "__main__":
    unittest.main()
