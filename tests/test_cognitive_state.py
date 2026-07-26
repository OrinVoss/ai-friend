"""Tests for CognitiveState / World State unification."""
import unittest
from unittest.mock import MagicMock, patch

from core.cognitive_state import CognitiveState
from core.message_handler import MessageHandler
from core.inner_drive import InnerDriveResult


def _make_agent():
    """Build a minimal agent mock for MessageHandler tests."""
    a = MagicMock()
    a.is_sleeping = False
    a.turn_count = 1
    a.last_activity_time = 0.0
    a.consecutive_negative = 0
    a.tool_call_history = []
    a.current_memory_context = None
    a.compressed_summary = ""
    a.personality.config.name = "TestBot"
    a.personality.emotion.to_prompt_summary.return_value = {
        "dominant_emotion": "neutral",
        "mood": "平静",
        "primary_hint": "",
        "valence": 0.4,
        "arousal": 0.5,
        "valence_desc": "积极",
        "arousal_desc": "平衡",
        "behavior": "你心情平静。",
    }
    a.ltm.get_relationship.return_value = {
        "trust": 0.5, "familiarity": 0.5, "intimacy": 0.5, "playfulness": 0.5,
    }
    a.retriever.retrieve_for_query.return_value = MagicMock(
        facts=[], experiences=[], reflections=[],
        relationship={"trust": 0.5, "familiarity": 0.5},
    )
    a.short_term.format_for_prompt.return_value = ""
    a.short_term.get_all_reversed.return_value = []
    a.config.prompt_cache_ttl_seconds = 60
    a.config.conversation_examples_max_turns = 3
    a.config.conversation_examples = []
    a.config.use_memory_agent = False
    a.config.proactive_think_loop = False
    a.provider.generate.return_value = "NO_TOOLS"
    a._react_loop.return_value = "Hello!"
    return a


class TestCognitiveStateData(unittest.TestCase):
    def test_defaults(self):
        s = CognitiveState(personality_name="Test", emotion_summary={}, relationship={})
        self.assertEqual(s.memory_summary, "")
        self.assertIsNone(s.memory_confidence)
        self.assertEqual(s.care_surface, [])
        self.assertEqual(s.pending, {})
        self.assertEqual(s.turn_count, 0)

    def test_pending_mutation(self):
        s = CognitiveState(personality_name="Test", emotion_summary={}, relationship={})
        s.pending = {"needs_tools": False, "summary": "x"}
        self.assertEqual(s.pending["summary"], "x")


class TestMessageHandlerStateAssembly(unittest.TestCase):
    @patch("core.message_handler.MessageHandler._run_agent3")
    @patch("prompts.system.build_inner_drive_prompt", return_value="mock inner prompt")
    def test_handle_message_passes_state_to_agent3(self, _mock_prompt, mock_run3):
        a = _make_agent()
        a.provider.generate.return_value = (
            '{"needs_external_tools": false, "reasoning": "闲聊", '
            '"summary": "只是闲聊", "tool_requests": []}'
        )
        mock_run3.return_value = "你好呀"
        handler = MessageHandler(a)
        handler.handle_message("你好")
        self.assertEqual(mock_run3.call_count, 1)
        _, kwargs = mock_run3.call_args
        state = kwargs.get("state")
        self.assertIsInstance(state, CognitiveState)
        self.assertEqual(state.personality_name, "TestBot")
        self.assertEqual(state.emotion_summary["dominant_emotion"], "neutral")
        self.assertEqual(state.relationship["trust"], 0.5)
        self.assertEqual(state.pending["summary"], "只是闲聊")
        self.assertFalse(state.pending["needs_tools"])
        self.assertIn("信任", state.memory_summary)


class TestRunAgent3StateDataSource(unittest.TestCase):
    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_uses_state_memory_summary(self, mock_build):
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        state = CognitiveState(
            personality_name="TestBot", emotion_summary={},
            relationship={},
            memory_summary="=== 关系 ===\n信任: 0.9",
        )
        drive_result = InnerDriveResult(
            needs_external_tools=False, reasoning="x", summary="y", context_summary="",
        )
        handler._run_agent3("你好", drive_result, tool_result=None, state=state)
        _, kwargs = mock_build.call_args
        self.assertEqual(
            kwargs.get("memory_context_summary"),
            "=== 关系 ===\n信任: 0.9",
        )

    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_falls_back_to_drive_result_summary(self, mock_build):
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        drive_result = InnerDriveResult(
            needs_external_tools=False, reasoning="x", summary="y",
            context_summary="=== 关系 ===\n信任: 0.8",
        )
        handler._run_agent3("你好", drive_result, tool_result=None, state=None)
        _, kwargs = mock_build.call_args
        self.assertEqual(
            kwargs.get("memory_context_summary"),
            "=== 关系 ===\n信任: 0.8",
        )

    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_prompt_equivalence_state_vs_drive_result(self, mock_build):
        """WS-15: 同样数据下，state 路径与旧 drive_result 路径生成的 prompt 等价。"""
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        summary = "=== 关系 ===\n信任: 0.7"
        inner_summary = "只是闲聊"

        # state 路径
        state = CognitiveState(
            personality_name="TestBot", emotion_summary={},
            relationship={},
            memory_summary=summary,
        )
        state.pending = {"summary": inner_summary}
        drive_state = InnerDriveResult(
            needs_external_tools=False, reasoning="x", summary=inner_summary,
            context_summary="",
        )
        handler._run_agent3("你好", drive_state, tool_result=None, state=state)
        kwargs_state = dict(mock_build.call_args[1])

        # 旧路径
        drive_old = InnerDriveResult(
            needs_external_tools=False, reasoning="x", summary=inner_summary,
            context_summary=summary,
        )
        handler._run_agent3("你好", drive_old, tool_result=None, state=None)
        kwargs_old = dict(mock_build.call_args[1])

        # 比较影响 prompt 的关键字段
        self.assertEqual(
            kwargs_state["memory_context_summary"],
            kwargs_old["memory_context_summary"],
        )
        self.assertEqual(
            kwargs_state["inner_drive_summary"],
            kwargs_old["inner_drive_summary"],
        )

    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_inner_drive_summary_from_state_pending(self, mock_build):
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        state = CognitiveState(
            personality_name="TestBot", emotion_summary={},
            relationship={},
        )
        state.pending = {"summary": "来自 state 的摘要"}
        handler._run_agent3("你好", None, tool_result=None, state=state)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("inner_drive_summary"), "来自 state 的摘要")

    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_passes_emotion_summary(self, mock_build):
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        emotion_summary = {
            "dominant_emotion": "joyful", "mood": "欣喜", "primary_hint": "",
            "valence": 0.8, "arousal": 0.7,
            "valence_desc": "积极", "arousal_desc": "充满能量",
            "behavior": "你心情很好。",
        }
        state = CognitiveState(
            personality_name="TestBot", emotion_summary=emotion_summary,
            relationship={}, memory_summary="=== 关系 ===\n信任: 0.9",
        )
        handler._run_agent3("你好", None, tool_result=None, state=state)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("emotion_summary"), emotion_summary)

    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_uses_light_render_from_memory_answer(self, mock_build):
        """WS-27: Agent 3 优先从 state.memory_answer 渲染轻量视图。"""
        from memory.retrieval_pipeline import MemoryEvidence
        from memory.memory_agent import MemoryAnswer
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        ma = MemoryAnswer(
            answer="相关记忆", confidence=0.8,
            evidences=[MemoryEvidence(
                source_type="fact", source_id=1,
                content="preference|最爱食物: 披萨",
                confidence=0.9, timestamp="2026-07-26 10:00:00",
            )],
        )
        state = CognitiveState(
            personality_name="TestBot", emotion_summary={},
            relationship={},
            memory_summary="=== 关系 ===\n信任: 0.9",
            memory_answer=ma,
        )
        handler._run_agent3("你好", None, tool_result=None, state=state)
        _, kwargs = mock_build.call_args
        summary = kwargs.get("memory_context_summary")
        self.assertIn("最爱食物", summary)
        # memory_summary should remain the raw snapshot, not be rewritten.
        self.assertEqual(state.memory_summary, "=== 关系 ===\n信任: 0.9")

    @patch("prompts.system.build_system_prompt")
    def test_run_agent3_no_redundant_retrieval_when_summary_present(self, mock_build):
        """WS-28: 已有 memory_summary 时 Agent 3 不再 retrieve_for_query。"""
        mock_build.return_value = "mock prompt"
        a = _make_agent()
        handler = MessageHandler(a)
        state = CognitiveState(
            personality_name="TestBot", emotion_summary={},
            relationship={},
            memory_summary="=== 关系 ===\n信任: 0.9",
        )
        handler._run_agent3("你好", None, tool_result=None, state=state)
        a.retriever.retrieve_for_query.assert_not_called()


class TestPhase2RetrievalFront(unittest.TestCase):
    @patch("core.message_handler.MessageHandler._run_agent3")
    def test_handle_message_retrieves_memory_once(self, mock_run3):
        """WS-26: 每条用户消息只在状态装配处检索一次记忆。"""
        a = _make_agent()
        a.provider.generate.return_value = (
            '{"needs_external_tools": false, "reasoning": "闲聊", '
            '"summary": "只是闲聊", "tool_requests": []}'
        )
        mock_run3.return_value = "你好呀"
        handler = MessageHandler(a)
        handler.handle_message("你好")
        # _context_for_state 调用一次 retriever；assess 与 agent3 不应再检索。
        self.assertEqual(a.retriever.retrieve_for_query.call_count, 1)

    @patch("prompts.system.build_inner_drive_prompt", return_value="mock prompt")
    def test_assess_with_state_skips_internal_retrieval(self, _mock_prompt):
        from core.inner_drive import InnerDriveAgent
        from tests.mocks import mock_tool_registry

        personality = MagicMock()
        personality.config.traits = []
        personality.config.name = "TestBot"
        personality.emotion.to_prompt_summary.return_value = {
            "dominant_emotion": "neutral", "mood": "平静", "primary_hint": "",
            "valence": 0.4, "arousal": 0.5,
            "valence_desc": "积极", "arousal_desc": "平衡",
            "behavior": "你心情平静。",
        }
        retriever = MagicMock()
        retriever.retrieve_for_query.return_value = MagicMock(
            facts=[], experiences=[], reflections=[],
            relationship={"trust": 0.5, "familiarity": 0.5},
        )
        provider = MagicMock()
        provider.generate.return_value = (
            '{"needs_external_tools": false, "reasoning": "x", '
            '"summary": "y", "tool_requests": []}'
        )
        agent = InnerDriveAgent(
            provider=provider,
            personality=personality,
            ltm=MagicMock(),
            retriever=retriever,
            short_term=MagicMock(),
            tool_registry=mock_tool_registry(),
        )
        agent._context_summary_for = MagicMock(return_value="wrong summary")
        state = CognitiveState(
            personality_name="TestBot",
            emotion_summary=personality.emotion.to_prompt_summary(),
            relationship={},
            memory_summary="right summary",
            memory_confidence=0.75,
        )
        result = agent.assess("你好", cognitive_state=state)
        agent._context_summary_for.assert_not_called()
        self.assertEqual(result.context_summary, "right summary")
        self.assertEqual(result.memory_confidence, 0.75)

    @patch("prompts.system.build_inner_drive_prompt", return_value="mock prompt")
    def test_assess_without_state_keeps_legacy_path(self, _mock_prompt):
        from core.inner_drive import InnerDriveAgent
        from tests.mocks import mock_tool_registry

        personality = MagicMock()
        personality.config.traits = []
        personality.config.name = "TestBot"
        personality.emotion.to_prompt_summary.return_value = {
            "dominant_emotion": "neutral", "mood": "平静", "primary_hint": "",
            "valence": 0.4, "arousal": 0.5,
            "valence_desc": "积极", "arousal_desc": "平衡",
            "behavior": "你心情平静。",
        }
        retriever = MagicMock()
        retriever.retrieve_for_query.return_value = MagicMock(
            facts=[], experiences=[], reflections=[],
            relationship={"trust": 0.5, "familiarity": 0.5},
        )
        provider = MagicMock()
        provider.generate.return_value = (
            '{"needs_external_tools": false, "reasoning": "x", '
            '"summary": "y", "tool_requests": []}'
        )
        agent = InnerDriveAgent(
            provider=provider,
            personality=personality,
            ltm=MagicMock(),
            retriever=retriever,
            short_term=MagicMock(),
            tool_registry=mock_tool_registry(),
        )
        result = agent.assess("你好")
        self.assertTrue(retriever.retrieve_for_query.called)
        self.assertIn("信任", result.context_summary)


if __name__ == "__main__":
    unittest.main()
