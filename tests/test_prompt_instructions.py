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
    _build_tool_history_block,
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
        self.assertIn("有自主判断力", text)
        self.assertIn("检查清单（逐条过）", text)
        self.assertIn("用户指令优先", text)

    def test_inner_drive_no_personality_inference_rule(self):
        """R1: Agent 1 禁止人格/心理动机推断。"""
        from models.personality import PersonalityConfig
        personality = PersonalityConfig(name="TestBot")
        text = _build_inner_drive_instructions_block(personality)
        self.assertIn("用户意图", text)
        self.assertIn("不要推断用户的人格、心理动机", text)
        self.assertIn("禁止出现在 reasoning 里", text)
        self.assertIn("不写心理分析", text)

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


class TestAgent3PromptConstraints(unittest.TestCase):
    """R2 + R5：Agent 3 prompt 不再被 inner_drive_summary 带偏，
    且记忆/工具历史块瘦身。"""

    def _make_context(self):
        from models.conversation import MemoryContext
        from models.memory import Reflection
        reflections = [
            Reflection(content="洞察一" + "x" * 200),
            Reflection(content="洞察二" + "y" * 200),
            Reflection(content="洞察三" + "z" * 200),
        ]
        return MemoryContext(
            facts=[], experiences=[], reflections=reflections,
            relationship={"trust": 0.5, "familiarity": 0.5},
        )

    def test_inner_drive_summary_truncated_and_disclaimed(self):
        """R2: 超长 inner_drive_summary 截断到 300 字符并带免责声明标题。"""
        from models.personality import PersonalityConfig, EmotionalState
        long_summary = "分析开始：" + "u" * 500
        ctx = self._make_context()
        prompt = build_system_prompt(
            personality=PersonalityConfig(name="Test", traits=[], speaking_style="",
                                         backstory="", interests=[]),
            emotion=EmotionalState(),
            memory_context=ctx,
            conversation_history="",
            inner_drive_summary=long_summary,
        )
        self.assertIn("你刚才的分析（仅供参考，不要在回复里复述或展开）", prompt)
        self.assertNotIn("=== 你之前的判断 ===", prompt)
        # "分析开始：" 占 5 字符，截断后保留前 300 字符：5 + 295 个 u
        self.assertIn("分析开始：" + "u" * 295, prompt)
        self.assertNotIn("u" * 350, prompt)

    def test_agent3_no_psychoanalysis_rule(self):
        """R2: Agent 3 指令块含'不要分析用户'约束。"""
        from models.personality import PersonalityConfig, EmotionalState
        ctx = self._make_context()
        prompt = build_system_prompt(
            personality=PersonalityConfig(name="Test", traits=[], speaking_style="",
                                         backstory="", interests=[]),
            emotion=EmotionalState(),
            memory_context=ctx,
            conversation_history="",
        )
        self.assertIn("不要分析用户", prompt)
        self.assertIn("她在跟你聊天，不是来做心理咨询", prompt)
        self.assertIn("不要替她下结论", prompt)

    def _section_lines(self, prompt: str, header: str) -> list[str]:
        """提取 prompt 中某个 === 标题块下的 - 条目。"""
        start = prompt.find(header)
        self.assertGreater(start, -1)
        end = prompt.find("\n===", start + len(header))
        section = prompt[start:end] if end > -1 else prompt[start:]
        return [line for line in section.split("\n") if line.startswith("- ")]

    def test_reflections_truncated_to_two_and_120_chars(self):
        """R5: reflection 最多 2 条，每条 ≤120 字符。"""
        from models.personality import PersonalityConfig, EmotionalState
        ctx = self._make_context()
        prompt = build_system_prompt(
            personality=PersonalityConfig(name="Test", traits=[], speaking_style="",
                                         backstory="", interests=[]),
            emotion=EmotionalState(),
            memory_context=ctx,
            conversation_history="",
        )
        lines = self._section_lines(prompt, "=== 你的最近思考 ===")
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertLessEqual(len(line), 120 + len("- ") + 1)  # 含 "- " 与可能的 "…"
            self.assertIn("…", line)

    def test_tool_history_limited_to_three_and_60_chars(self):
        """R5: tool history 最多 3 条，output 摘要 ≤60 字符。"""
        from models.personality import PersonalityConfig, EmotionalState
        from models.conversation import MemoryContext
        tool_history = [
            {"name": f"tool_{i}", "success": True,
             "output": f"结果{i}: " + "o" * 200}
            for i in range(5)
        ]
        prompt = build_system_prompt(
            personality=PersonalityConfig(name="Test", traits=[], speaking_style="",
                                         backstory="", interests=[]),
            emotion=EmotionalState(),
            memory_context=MemoryContext(),
            conversation_history="",
            tool_call_history=tool_history,
        )
        lines = self._section_lines(prompt, "=== 你的工具调用记录 ===")
        self.assertEqual(len(lines), 3)
        # output 摘要截断到 60 字符（含 "…" 后缀）
        for line in lines:
            # line 格式: "- ✅ tool_i: 结果i: ooooo…"
            prefix, output_part = line.split(": ", 1)
            self.assertLessEqual(len(output_part), 61, output_part)
            self.assertIn("…", output_part)

    def test_memory_block_slimmer_than_untrimmed(self):
        """R5: _build_memory_block 对长 reflection 截断后明显变短。"""
        from models.conversation import MemoryContext
        from models.memory import Reflection
        reflections = [Reflection(content="洞察" + "x" * 250) for _ in range(3)]
        ctx = MemoryContext(reflections=reflections)
        from prompts.system import _build_memory_block
        block = _build_memory_block(ctx)
        # 未截断基线 = 3 * 254；截断后 = 2 * (120 + "…") + 标题/前缀
        self.assertLess(len(block), sum(len(r.content) for r in reflections))
        self.assertIn("=== 你的最近思考 ===", block)

    def test_tool_history_block_slimmer_than_untrimmed(self):
        """R5: _build_tool_history_block 截断后明显变短。"""
        tool_history = [
            {"name": f"tool_{i}", "success": True,
             "output": f"结果{i}: " + "o" * 200}
            for i in range(5)
        ]
        block = _build_tool_history_block(tool_history)
        # 未截断基线 = 5 * 200+；截断后 = 3 * 60
        self.assertLess(len(block), sum(len(t["output"]) for t in tool_history))
        self.assertIn("=== 你的工具调用记录 ===", block)


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


class TestTimeQueryNoToolRule(unittest.TestCase):
    """2026-07-22 Review：Agent 1 prompt 必须明示'问时间直接用上下文，
    不要调工具'——防止 Inner Drive 为时间问题触发工具链空转。"""

    def test_checklist_has_time_no_tool_rule(self):
        from prompts.instructions import INNER_DRIVE_CHECKLIST
        self.assertIn("问时间/日期/星期", INNER_DRIVE_CHECKLIST)
        self.assertIn("永远不需要为此调用工具", INNER_DRIVE_CHECKLIST)

    def test_agent1_prompt_contains_time_and_rule(self):
        from prompts.system import build_inner_drive_prompt
        from models.personality import PersonalityConfig, EmotionalState
        from models.conversation import MemoryContext
        personality = PersonalityConfig(name="Test", traits=[], speaking_style="",
                                       backstory="", interests=[])
        ctx = MemoryContext(facts=[], experiences=[], reflections=[],
                            relationship={"trust": 0.5})
        prompt = build_inner_drive_prompt(
            personality=personality, emotion=EmotionalState(),
            memory_context=ctx, conversation_history="",
        )
        self.assertIn("当前时间：", prompt)
        self.assertIn("永远不需要为此调用工具", prompt)
