"""Tests for tools/memory_tools.py (#6 correction feature)."""
import unittest
from unittest.mock import MagicMock

from tools.memory_tools import RememberTool


class TestRememberTool(unittest.TestCase):
    def setUp(self):
        self.ltm = MagicMock()
        self.ltm.search_facts.return_value = []
        self.tool = RememberTool(self.ltm)

    def test_name(self):
        self.assertEqual(self.tool.name(), "remember")

    def test_execute_store(self):
        result = self.tool.execute({
            "category": "preference", "key": "最爱颜色", "value": "蓝色",
        })
        self.assertTrue(result.success)
        self.ltm.store_fact.assert_called_once_with(
            "preference", "最爱颜色", "蓝色", confidence=0.9, importance=0.6, fact_type="user_fact",
        )

    def test_execute_correction(self):
        # Simulate existing fact with same category+key
        from models.memory import UserFact
        self.ltm.search_facts.return_value = [
            UserFact(id=99, category="preference", fact_key="最爱颜色",
                     fact_value="红色", confidence=0.8),
        ]
        result = self.tool.execute({
            "category": "preference", "key": "最爱颜色", "value": "蓝色",
            "correct": True,
        })
        self.assertTrue(result.success)
        self.assertIn("纠正", result.output)
        self.ltm.correct_fact.assert_called_once_with(
            "preference", "最爱颜色", "蓝色", old_fact_id=99,
        )
        # store_fact should NOT be called for corrections
        self.ltm.store_fact.assert_not_called()

    def test_execute_missing_key(self):
        result = self.tool.execute({
            "category": "preference", "key": "", "value": "x",
        })
        self.assertFalse(result.success)

    def test_execute_missing_value(self):
        result = self.tool.execute({
            "category": "preference", "key": "name", "value": "",
        })
        self.assertFalse(result.success)

    def test_execute_correction_no_existing_match(self):
        """Correction without matching old fact just stores new one."""
        self.ltm.search_facts.return_value = []  # no match
        result = self.tool.execute({
            "category": "identity", "key": "名字", "value": "小明",
            "correct": True,
        })
        self.assertTrue(result.success)
        self.ltm.correct_fact.assert_called_once_with(
            "identity", "名字", "小明", old_fact_id=None,
        )


if __name__ == "__main__":
    unittest.main()
