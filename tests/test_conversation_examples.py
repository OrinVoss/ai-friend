"""Tests for configurable conversation examples (#28)."""
import unittest
from unittest.mock import MagicMock

from prompts.system import build_system_prompt
from config import Config


class TestConversationExamplesConfigurable(unittest.TestCase):
    def _make_config(self):
        cfg = Config()
        cfg.conversation_examples = [
            {
                "user": "测试用户输入",
                "replies": ["回复一", "回复二"],
            }
        ]
        return cfg

    def _make_context(self):
        from models.conversation import MemoryContext
        return MemoryContext(
            facts=[], experiences=[], reflections=[],
            relationship={"trust": 0.5, "familiarity": 0.5},
        )

    def test_examples_rendered_in_prompt(self):
        cfg = self._make_config()
        from models.personality import PersonalityConfig, EmotionalState
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        emotion = EmotionalState()
        ctx = self._make_context()
        prompt = build_system_prompt(
            personality=personality, emotion=emotion,
            memory_context=ctx, conversation_history="",
            conversation_examples=cfg.conversation_examples,
        )
        self.assertIn("=== 对话示例 ===", prompt)
        self.assertIn("测试用户输入", prompt)
        self.assertIn("回复一", prompt)
        self.assertIn("或者：回复二", prompt)

    def test_empty_examples_omits_content(self):
        from models.personality import PersonalityConfig, EmotionalState
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        emotion = EmotionalState()
        ctx = self._make_context()
        prompt = build_system_prompt(
            personality=personality, emotion=emotion,
            memory_context=ctx, conversation_history="",
            conversation_examples=[],
        )
        self.assertIn("=== 对话示例 ===", prompt)
        self.assertNotIn("用户：", prompt)


if __name__ == "__main__":
    unittest.main()
