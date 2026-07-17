"""Tests for core/message_handler.py"""
import unittest
from unittest.mock import ANY, MagicMock, patch

from core.message_handler import MessageHandler
from core.inner_drive import ProactiveIntent
from tests.mocks import mock_tool_registry


def _make_memory_mock():
    """Create a mock MemoryContext with proper numeric relationship values."""
    m = MagicMock()
    m.facts = []
    m.experiences = []
    m.reflections = []
    m.relationship = {"trust": 0.5, "familiarity": 0.5, "intimacy": 0.5, "playfulness": 0.5}
    return m


class TestMessageHandler(unittest.TestCase):
    def setUp(self):
        self.agent = MagicMock()
        self.agent._sleeping = False
        self.agent.turn_count = 0
        self.agent._consecutive_negative = 0
        self.agent._tool_call_history = []
        self.agent._tool_registry = mock_tool_registry()
        self.agent._context = MagicMock()
        self.agent._context.compressed_summary = ""
        self.agent._context.compress = MagicMock()
        self.agent.short_term.get_all_reversed.return_value = []
        self.agent.short_term.format_for_prompt.return_value = ""
        self.agent.short_term.get_all.return_value = []
        self.agent.retriever.retrieve_for_query.return_value = _make_memory_mock()
        self.agent.ltm.repo.insert_turn = MagicMock()
        self.agent.personality.config.name = "TestBot"
        self.agent.personality.config.interests = ["music", "art"]
        self.agent.personality.emotion.dominant_emotion = "neutral"
        self.agent.personality.emotion.valence = 0.4
        self.agent.personality.emotion.arousal = 0.5
        self.agent.personality.emotion.resentment = 0.0
        self.agent.personality.emotion.emotion_events = []
        self.agent.personality.emotion.record_emotion_event = MagicMock()
        self.agent.personality.config.traits = []
        self.agent.personality.emotion.to_prompt_summary.return_value = {
            "dominant_emotion": "neutral", "valence": 0.4, "arousal": 0.5,
        }
        self.agent.provider.generate.return_value = "NO_TOOLS"
        self.agent._react_loop.return_value = "Hello!"
        self.agent._pick_proactive_topic.return_value = "聊聊天气"
        # Give the mocked config concrete values for the new prompt-cache fields.
        self.agent.config.prompt_cache_ttl_seconds = 60
        self.agent.config.conversation_examples_max_turns = 3
        self.agent.config.use_memory_agent = False

        self.handler = MessageHandler(self.agent)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_message_normal(self, _mock):
        result = self.handler.handle_message("你好")
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()

    def test_handle_message_sleeping(self):
        self.agent._sleeping = True
        result = self.handler.handle_message("你好")
        self.assertIn("zzz", result.lower())
        self.agent._react_loop.assert_not_called()
        # Sleep reply should be persisted through the Agent facade.
        self.agent.add_turn.assert_any_call("assistant", result, metadata={"sleep": True})
        self.assertEqual(self.agent.increment_turn_count.call_count, 2)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive(self, _mock):
        result = self.handler.handle_proactive()
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_share(self, _mock):
        self.agent._react_loop.return_value = "我发现了一篇非常非常有趣的文章，关于人工智能技术的最新突破进展！"
        result = self.handler.handle_explore()
        self.assertIsNotNone(result)
        self.assertIn("人工智能", result)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_silent(self, _mock):
        self.agent._react_loop.return_value = "没啥"
        result = self.handler.handle_explore()
        self.assertIsNone(result)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_short_result(self, _mock):
        self.agent._react_loop.return_value = "ok"
        result = self.handler.handle_explore()
        self.assertIsNone(result)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_build_messages_overflow(self, _mock):
        mock_turn = MagicMock()
        mock_turn.role = "user"
        mock_turn.content = "x" * 100000
        self.agent.short_term.get_all_reversed.return_value = [mock_turn]
        self.agent._context.compressed_summary = "previous summary"
        result = self.handler.handle_message("hello")
        self.assertEqual(result, "Hello!")

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive_with_intent(self, _mock):
        intent = ProactiveIntent(
            action="chat", topic_hint="旅行计划",
            reasoning="上次聊到旅行，可以继续"
        )
        result = self.handler.handle_proactive(intent=intent)
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()
        # Should NOT have called pick_proactive_topic (intent was provided)
        self.agent._pick_proactive_topic.assert_not_called()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive_without_intent_fallback(self, _mock):
        result = self.handler.handle_proactive()  # no intent
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()
        # Should fall back to pick_proactive_topic
        self.agent._pick_proactive_topic.assert_called()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_with_intent(self, _mock):
        self.agent._react_loop.return_value = "我发现了一篇关于机器学习的有趣文章，内容非常有启发性值得大家阅读！"
        intent = ProactiveIntent(
            action="explore", topic_hint="机器学习最新动态",
            reasoning="用户是程序员，可能对ML感兴趣"
        )
        result = self.handler.handle_explore(intent=intent)
        self.assertIsNotNone(result)
        self.agent._pick_proactive_topic.assert_not_called()

    def test_parse_agent3_output_plain_text(self):
        result = self.handler._parse_agent3_output("你好呀！")
        self.assertEqual(result["type"], "plain")
        self.assertEqual(result["text"], "你好呀！")

    def test_parse_agent3_output_intent(self):
        result = self.handler._parse_agent3_output(
            '{"reply_to_user": "那我放首歌吧", "intent": "play_music", '
            '"intent_description": "放首歌给用户听", "intent_target": ""}'
        )
        self.assertEqual(result["type"], "intent")
        self.assertEqual(result["intent"], "play_music")
        self.assertEqual(result["reply_to_user"], "那我放首歌吧")

    def test_parse_agent3_output_invalid_json(self):
        result = self.handler._parse_agent3_output("{不是json}")
        self.assertEqual(result["type"], "plain")

    def test_handle_agent3_intent_plain(self):
        result = self.handler._handle_agent3_intent("你好", "嗨！今天怎么样？")
        self.assertEqual(result, "嗨！今天怎么样？")

    @patch('prompts.system.build_system_prompt')
    def test_agent3_reuses_context_summary(self, mock_build):
        """Agent 3 should receive Agent 1's formatted summary to avoid a second retrieval."""
        mock_build.return_value = "mock prompt"
        from core.inner_drive import InnerDriveResult
        self.handler._ensure_inner_drive()
        drive_result = InnerDriveResult(
            needs_external_tools=False,
            reasoning="闲聊",
            summary="",
            context_summary="=== 你和用户的关系 ===\n信任: 0.9",
        )
        self.handler._run_agent3("你好", drive_result, tool_result=None)
        # The summary should be forwarded as memory_context_summary.
        _, kwargs = mock_build.call_args
        self.assertEqual(
            kwargs.get("memory_context_summary"),
            "=== 你和用户的关系 ===\n信任: 0.9",
        )
        # No extra retrieval should happen because the summary is reused.
        self.assertEqual(self.agent.retriever.retrieve_for_query.call_count, 0)

    @patch('prompts.system.build_system_prompt')
    def test_conversation_examples_hidden_after_threshold(self, mock_build):
        """Examples should only be injected for the first N turns."""
        mock_build.return_value = "mock prompt"
        self.agent.turn_count = 4
        self.agent.config.conversation_examples_max_turns = 3
        self.handler.handle_message("你好")
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("demo_turns_remaining"), 0)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_agent3_intent_rejected(self, _mock):
        self.handler._ensure_inner_drive()
        self.handler._inner_drive.assess_agent3_intent = MagicMock(
            return_value=MagicMock(needs_external_tools=False, summary="用户很忙")
        )
        result = self.handler._handle_agent3_intent(
            "我现在很忙",
            '{"reply_to_user": "那我放首歌吧", "intent": "play_music", '
            '"intent_description": "放首歌给用户听", "intent_target": ""}'
        )
        self.assertEqual(result, "那我放首歌吧")

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_agent3_intent_approved(self, _mock):
        from core.inner_drive import InnerDriveResult, ToolRequest
        self.handler._ensure_inner_drive()
        self.handler._inner_drive.assess_agent3_intent = MagicMock(
            return_value=InnerDriveResult(
                needs_external_tools=True,
                reasoning="合理",
                tool_requests=[ToolRequest(description="播放音乐", suggested_tool="music_play")],
            )
        )
        self.handler._ensure_tool_agent()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.any_success = True
        mock_result.total_calls = 1
        mock_result.success_count = 1
        mock_result.records = [MagicMock(name="music_play", success=True, output="ok")]
        self.handler._tool_agent.run_with_requests = MagicMock(return_value=mock_result)
        self.handler._tool_agent.format_for_phase2 = MagicMock(return_value="[音乐播放成功]")
        self.agent._react_loop.return_value = "给你放了首轻音乐~"

        result = self.handler._handle_agent3_intent(
            "有点无聊",
            '{"reply_to_user": "那我放首歌吧", "intent": "play_music", '
            '"intent_description": "放首歌给用户听", "intent_target": ""}'
        )
        self.assertEqual(result, "给你放了首轻音乐~")

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_state_machine_transitions_no_tools(self, _mock):
        """Normal chat should transition IDLE -> ASSESSING -> GENERATING_RESPONSE -> DONE."""
        from core.message_handler import MessageHandlerState
        self.assertEqual(self.handler.current_state, MessageHandlerState.IDLE)
        self.handler.handle_message("你好")
        self.assertEqual(self.handler.current_state, MessageHandlerState.DONE)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_run_agent2_returns_tool_execution_result(self, _mock):
        """_run_agent2 should return a ToolExecutionResult with correct stats."""
        from core.inner_drive import InnerDriveResult, ToolRequest
        from core.message_handler import ToolExecutionResult
        self.handler._ensure_tool_agent()
        mock_result = MagicMock()
        mock_result.has_results = True
        mock_result.any_success = True
        mock_result.total_calls = 2
        mock_result.success_count = 1
        mock_result.records = [
            MagicMock(name="glob", success=True, output="found files"),
            MagicMock(name="read_file", success=False, output="missing"),
        ]
        self.handler._tool_agent.run_with_requests = MagicMock(return_value=mock_result)
        self.handler._tool_agent.format_for_phase2 = MagicMock(return_value="[工具结果]")

        drive_result = InnerDriveResult(
            needs_external_tools=True,
            reasoning="需要查文件",
            tool_requests=[ToolRequest(description="查文件")],
        )
        exec_result = self.handler._run_agent2("查文件", drive_result)
        self.assertIsInstance(exec_result, ToolExecutionResult)
        self.assertEqual(exec_result.total_calls, 2)
        self.assertEqual(exec_result.success_count, 1)
        self.assertIn("[工具结果]", exec_result.records_text)

    def test_internal_registry_isolation(self):
        """Agent 1 internal registry must only contain fresh recall/remember instances."""
        from tools.memory_tools import RecallTool, RememberTool
        registry = self.handler._make_internal_registry()
        specs = {s.name for s in registry.list_specs()}
        self.assertEqual(specs, {"recall", "remember"})
        recall = registry.get("recall")
        remember = registry.get("remember")
        self.assertIsInstance(recall, RecallTool)
        self.assertIsInstance(remember, RememberTool)
        # Must be fresh instances, not borrowed from the main registry
        self.assertIsNot(recall, self.agent._tool_registry.get("recall"))
        self.assertIsNot(remember, self.agent._tool_registry.get("remember"))


if __name__ == "__main__":
    unittest.main()
