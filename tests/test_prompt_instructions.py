"""Tests for centralized instructions and registry-derived tool rules (#294)."""
import unittest
from unittest.mock import MagicMock

from prompts import instructions
from prompts.tools_description import format_intent_options, format_tool_rules
from prompts.system import (
    _build_emotion_block,
    _build_inner_drive_instructions_block,
    _build_instructions_block,
    _build_output_rules_block,
    build_inner_drive_prompt,
    build_system_prompt,
    build_tool_agent_prompt,
)
from tools.traits import ToolRegistry, ToolSpec


class TestCentralizedInstructions(unittest.TestCase):
    def test_inner_drive_instructions_use_constants(self):
        from models.personality import PersonalityConfig
        personality = PersonalityConfig(name="TestBot")
        text = _build_inner_drive_instructions_block(personality)
        self.assertIn("=== 内驱推理 ===", text)
        self.assertIn("TestBot", text)
        self.assertIn("你不是一个只会等指令的客服机器人", text)
        self.assertIn("内驱检查清单", text)
        self.assertIn("用户指令优先", text)

    def test_tool_agent_prompt_uses_constants(self):
        registry = ToolRegistry()
        text = build_tool_agent_prompt(registry)
        self.assertIn("=== 工具调用代理 ===", text)
        self.assertIn("可用工具：", text)
        self.assertIn('"calls":', text)

    def test_agent3_instructions_modes(self):
        base = _build_instructions_block("2026-07-14 12:00 星期一", False, False)
        proactive = _build_instructions_block("2026-07-14 12:00 星期一", True, False)
        explore = _build_instructions_block("2026-07-14 12:00 星期一", False, True)
        self.assertIn("像朋友一样回她", base)
        self.assertIn("用户有一会儿没说话了", proactive)
        self.assertIn("自由探索模式", explore)

    def test_output_rules_final(self):
        text = _build_output_rules_block(final_response=True)
        self.assertIn("外部工具已经执行完毕", text)

    def test_output_rules_default_no_hardcoded_aliases(self):
        """Agent 3 output rules should not contain old hard-coded intent aliases."""
        text = _build_output_rules_block(final_response=False)
        self.assertNotIn("send_notify", text)
        self.assertNotIn("search_web", text)
        self.assertIn("play_music", text)  # derived from registry mapping


class TestRegistryDerivedToolRules(unittest.TestCase):
    def _make_registry(self, names):
        registry = ToolRegistry()
        for name in names:
            tool = MagicMock()
            tool.name.return_value = name
            tool.description.return_value = f"Mock {name}"
            tool.parameters_schema.return_value = {}
            tool.spec.return_value = ToolSpec(name=name, description=f"Mock {name}", parameters={})
            registry.register(tool)
        return registry

    def test_format_tool_rules_filters_unknown_tools(self):
        registry = self._make_registry(["web_fetch", "web_search", "unknown_tool"])
        rules = format_tool_rules(registry)
        self.assertIn("web_fetch", rules)
        self.assertIn("web_search", rules)
        self.assertNotIn("unknown_tool", rules)

    def test_format_intent_options(self):
        registry = self._make_registry(["music_play", "notify", "web_search", "glob"])
        options = format_intent_options(registry)
        self.assertIn("play_music", options)
        self.assertIn("send_notify", options)
        self.assertIn("search_web", options)
        self.assertNotIn("glob", options)

    def test_inner_drive_instructions_derive_rules_from_registry(self):
        from models.personality import PersonalityConfig
        registry = self._make_registry(["web_fetch", "music_play"])
        personality = PersonalityConfig(name="TestBot")
        text = _build_inner_drive_instructions_block(personality, tools=registry)
        self.assertIn("用户提供了 URL → 立即调用 web_fetch", text)
        self.assertIn("用户要求放音乐 → 调用 music_play", text)


class TestEmotionPromptSummary(unittest.TestCase):
    def _make_context(self):
        from models.conversation import MemoryContext
        return MemoryContext(
            facts=[], experiences=[], reflections=[],
            relationship={"trust": 0.5, "familiarity": 0.5},
        )

    def test_to_prompt_summary_structure(self):
        from models.personality import EmotionalState
        emotion = EmotionalState()
        summary = emotion.to_prompt_summary()
        self.assertIn("dominant_emotion", summary)
        self.assertIn("mood", summary)
        self.assertIn("valence_desc", summary)
        self.assertIn("arousal_desc", summary)
        self.assertIn("behavior", summary)
        # P2-5: numeric dimensions must be present for inner drive prompt
        self.assertIn("valence", summary)
        self.assertIn("arousal", summary)

    def test_build_system_prompt_with_emotion_summary(self):
        from models.personality import PersonalityConfig, EmotionalState
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        emotion = EmotionalState()
        summary = emotion.to_prompt_summary()
        ctx = self._make_context()

        prompt_with_emotion = build_system_prompt(
            personality=personality, emotion=emotion,
            memory_context=ctx, conversation_history="",
        )
        prompt_with_summary = build_system_prompt(
            personality=personality, emotion=emotion, emotion_summary=summary,
            memory_context=ctx, conversation_history="",
        )
        self.assertEqual(prompt_with_emotion, prompt_with_summary)
        self.assertIn("=== 你现在啥状态 ===", prompt_with_summary)
        self.assertIn(summary["mood"], prompt_with_summary)

    def test_build_inner_drive_prompt_with_emotion_summary(self):
        from models.personality import PersonalityConfig, EmotionalState
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        emotion = EmotionalState()
        summary = emotion.to_prompt_summary()
        ctx = self._make_context()

        prompt_with_emotion = build_inner_drive_prompt(
            personality=personality, emotion=emotion,
            memory_context=ctx, conversation_history="",
        )
        prompt_with_summary = build_inner_drive_prompt(
            personality=personality, emotion=emotion, emotion_summary=summary,
            memory_context=ctx, conversation_history="",
        )
        self.assertEqual(prompt_with_emotion, prompt_with_summary)
        self.assertIn(emotion.dominant_emotion, prompt_with_summary)

    def test_build_emotion_block_requires_emotion_or_summary(self):
        with self.assertRaises(ValueError):
            _build_emotion_block()


if __name__ == "__main__":
    unittest.main()
