"""Tests for core/inner_drive_state.py — minimal care list (一期)."""
import tempfile
import unittest

from core.inner_drive_state import InnerDriveState


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


if __name__ == "__main__":
    unittest.main()
