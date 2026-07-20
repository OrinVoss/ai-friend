"""Tests for centralized instructions and registry-derived tool rules (#294)."""
import unittest
from unittest.mock import MagicMock

from prompts import instructions
from prompts.tools_description import (
    format_intent_options,
    format_tool_followup_rules,
    format_tool_rules,
)
from prompts.system import (
    _build_emotion_block,
    _build_inner_drive_instructions_block,
    _build_instructions_block,
    _build_internal_tools_block,
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


class TestAgent1RuleTools(unittest.TestCase):
    """M-06: Agent 1 prompt 的工具规则/检查清单以 rule_tools（全量 registry）
    为数据源，不再因隔离 registry 误报"无可用的外部工具"。"""

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

    def _build_prompt(self, tools, rule_tools):
        from models.personality import PersonalityConfig, EmotionalState
        from models.conversation import MemoryContext
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        ctx = MemoryContext(facts=[], experiences=[], reflections=[],
                            relationship={"trust": 0.5, "familiarity": 0.5})
        return build_inner_drive_prompt(
            personality=personality, emotion=EmotionalState(),
            memory_context=ctx, conversation_history="",
            tools=tools, rule_tools=rule_tools,
        )

    def test_internal_registry_with_full_rule_tools(self):
        internal = self._make_registry(["recall", "remember"])
        full = self._make_registry(
            ["web_fetch", "web_search", "music_play", "recall", "remember"])
        prompt = self._build_prompt(internal, full)
        # 不再误报"无可用的外部工具"
        self.assertNotIn("（当前无可用的外部工具）", prompt)
        # 规则文本与全量 registry 一致
        self.assertIn(format_tool_rules(full), prompt)
        # 检查清单的跟进规则同样由 registry 动态派生
        self.assertIn("刚用过 music_play", prompt)
        self.assertIn("刚用过 web_fetch", prompt)

    def test_rule_tools_defaults_to_tools(self):
        """兼容旧行为：rule_tools=None 时回退到 tools。"""
        internal = self._make_registry(["recall", "remember"])
        prompt = self._build_prompt(internal, None)
        self.assertIn("（当前无可用的外部工具）", prompt)

    def test_checklist_followup_rules_filtered_by_registry(self):
        registry = self._make_registry(["music_play"])
        rules = format_tool_followup_rules(registry)
        self.assertIn("刚用过 music_play", rules)
        self.assertNotIn("刚用过 web_fetch", rules)
        self.assertNotIn("刚用过 notify", rules)


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

    def test_build_system_prompt_renders_live_emotion(self):
        # M-07: emotion_summary 参数已删除，情绪块统一读活 EmotionalState
        from models.personality import PersonalityConfig, EmotionalState
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        emotion = EmotionalState()
        summary = emotion.to_prompt_summary()
        ctx = self._make_context()

        prompt = build_system_prompt(
            personality=personality, emotion=emotion,
            memory_context=ctx, conversation_history="",
        )
        self.assertIn("=== 你现在啥状态 ===", prompt)
        self.assertIn(summary["mood"], prompt)

    def test_build_inner_drive_prompt_renders_live_emotion(self):
        # M-07: 同上，内驱 prompt 的情绪行也直接读活对象
        from models.personality import PersonalityConfig, EmotionalState
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        emotion = EmotionalState()
        ctx = self._make_context()

        prompt = build_inner_drive_prompt(
            personality=personality, emotion=emotion,
            memory_context=ctx, conversation_history="",
        )
        self.assertIn(emotion.dominant_emotion, prompt)

    def test_build_emotion_block_from_live_emotion(self):
        from models.personality import EmotionalState
        emotion = EmotionalState()
        block = _build_emotion_block(emotion)
        self.assertIn("=== 你现在啥状态 ===", block)
        self.assertIn(emotion.to_prompt_summary()["mood"], block)


class TestInternalToolsBlock(unittest.TestCase):
    """#281: _build_internal_tools_block 的工具清单与示例都从 registry 派生。"""

    def _make_registry(self, names, params=None):
        registry = ToolRegistry()
        for name in names:
            tool = MagicMock()
            tool.name.return_value = name
            tool.description.return_value = f"Mock {name}"
            p = (params or {}).get(name, {})
            tool.parameters_schema.return_value = p
            tool.spec.return_value = ToolSpec(name=name, description=f"Mock {name}", parameters=p)
            registry.register(tool)
        return registry

    def test_block_derives_names_from_registry(self):
        registry = self._make_registry(["recall", "remember"])
        block = _build_internal_tools_block(registry)
        self.assertIn("recall", block)
        self.assertIn("remember", block)

    def test_block_changes_with_registry(self):
        # 注册不同工具名时输出随之变化，不再硬编码 recall/remember
        registry = self._make_registry(["dream_log"])
        block = _build_internal_tools_block(registry)
        self.assertIn("dream_log", block)
        self.assertNotIn("recall", block)

    def test_example_derived_from_first_tool_schema(self):
        params = {"recall": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "q"}},
            "required": ["query"],
        }}
        registry = self._make_registry(["recall"], params)
        block = _build_internal_tools_block(registry)
        self.assertIn('"name": "recall"', block)
        self.assertIn('"query"', block)

    def test_empty_registry_returns_empty(self):
        self.assertEqual(_build_internal_tools_block(ToolRegistry()), "")
        self.assertEqual(_build_internal_tools_block(None), "")


class TestTemplateBraceSafety(unittest.TestCase):
    """所有 prompt 模板必须能被 safe_format 正常格式化——JSON 字面量的
    花括号必须 doubled（{{ }}），否则 format() 静默失败、LLM 拿到的是
    未替换占位符的空模板（2026-07-20 生产事故：INSIGHT/CARE_CLUE 因此
    失效）。"""

    def test_all_templates_format_safely(self):
        import string
        import prompts.templates as T

        checked = 0
        for name in dir(T):
            if not name.endswith("_PROMPT"):
                continue
            tpl = getattr(T, name)
            if not isinstance(tpl, str):
                continue
            checked += 1
            fields = set()
            try:
                for _, field, _, _ in string.Formatter().parse(tpl):
                    if field:
                        fields.add(field)
            except ValueError as e:
                self.fail(f"{name} 花括号非法（JSON 字面量需 doubled）: {e}")
            kwargs = {f: f"@@{f}@@" for f in fields}
            out = T.safe_format(tpl, **kwargs)
            for f in fields:
                self.assertIn(
                    f"@@{f}@@", out,
                    f"{name} 的 {{{f}}} 未被替换——模板里有未转义的 JSON 花括号")
        self.assertGreater(checked, 3, "模板数量异常，测试可能没生效")


if __name__ == "__main__":
    unittest.main()
