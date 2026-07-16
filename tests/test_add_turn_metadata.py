"""Regression tests for #156: add_turn metadata without is_tool_claim key.

Root cause of the sleep-message persistence failure: metadata={"sleep": True}
made is_tool_claim=None via .get(), and int(None) crashed insert_turn —
silently dropping the turn and, in the runtime driver, killing the whole tick.
"""
import unittest
from unittest.mock import MagicMock

from core.agent import Agent


class TestAddTurnMetadata(unittest.TestCase):
    def _agent(self):
        a = Agent.__new__(Agent)
        a.short_term = MagicMock()
        a.ltm = MagicMock()
        a.personality = MagicMock()
        a.turn_count = 0
        return a

    def test_sleep_metadata_coerces_to_false(self):
        a = self._agent()
        a.add_turn("assistant", "夜深了...我睡了，晚安[月亮]", metadata={"sleep": True})
        _, kwargs = a.ltm.repo.insert_turn_sync.call_args
        self.assertIs(kwargs["is_tool_claim"], False)

    def test_explicit_tool_claim_true(self):
        a = self._agent()
        a.add_turn("assistant", "（调用工具）", metadata={"is_tool_claim": True})
        _, kwargs = a.ltm.repo.insert_turn_sync.call_args
        self.assertIs(kwargs["is_tool_claim"], True)

    def test_no_metadata_defaults_false(self):
        a = self._agent()
        a.add_turn("user", "你好")
        _, kwargs = a.ltm.repo.insert_turn_sync.call_args
        self.assertIs(kwargs["is_tool_claim"], False)

    def test_sleep_metadata_does_not_raise(self):
        """End-to-end through a real insert path mock: the call must complete."""
        a = self._agent()
        try:
            a.add_turn("user", "睡了？", metadata={"sleep": True})
            a.add_turn("assistant", "zzz...ZZZ...💤", metadata={"sleep": True})
        except Exception as e:
            self.fail(f"add_turn raised with sleep metadata: {e}")


if __name__ == "__main__":
    unittest.main()
