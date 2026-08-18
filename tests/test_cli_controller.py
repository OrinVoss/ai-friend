"""Tests for core/cli_controller.py"""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from core.cli_controller import CliController, _CliFrontend, _StreamTagFilter


class TestCliController(unittest.TestCase):
    def setUp(self):
        self.agent = MagicMock()
        self.agent.ui = None  # headless mode for testing
        self.agent.personality.config.name = "TestBot"
        self.agent.personality.config.first_run_greeting = ""
        self.agent._running = True
        self.agent._context = MagicMock()
        self.agent._context.compressed_summary = ""
        self.agent._context.estimated_tokens = 0
        self.agent._context.reset_estimate = MagicMock()
        self.agent._context.add_estimate = MagicMock()
        self.agent._context.compress = MagicMock()
        self.agent.short_term.get_all_reversed.return_value = []
        self.agent.short_term.format_for_prompt.return_value = ""
        self.agent.short_term.get_all.return_value = []
        self.agent.retriever.retrieve_for_query.return_value = MagicMock()
        self.agent.ltm.repo.insert_turn = MagicMock()
        self.agent._pick_proactive_topic.return_value = "test topic"
        self.agent._max_tokens_for_emotion.return_value = 512
        self.agent._react_iteration = 0
        self.agent._max_tool_iterations = 10
        self.agent._tool_registry = MagicMock()
        self.agent._consecutive_negative = 0
        self.agent._prompt_shown = False
        self.agent.current_input = None
        self.agent.current_response = ""
        self.agent.turn_count = 0
        self.agent.last_activity_time = 0
        self.agent.config.proactive_min_idle = 180.0
        self.agent.config.max_facts = 200
        self.agent.config.max_experiences = 100
        self.agent.config.max_reflections = 50
        self.agent.config.personality_file = "test_role.json"
        self.agent._calculate_proactivity.return_value = 0.0
        self.agent.consolidator.should_consolidate.return_value = False
        self.agent.consolidator.consolidate = MagicMock()
        self.agent.consolidator.add_pending = MagicMock()

        self.ctrl = CliController(self.agent)

    def test_init(self):
        self.assertEqual(self.ctrl._agent, self.agent)

    def test_handle_command_exit(self):
        self.ctrl._handle_command("/exit")
        self.assertFalse(self.agent._running)

    def test_handle_command_quit(self):
        self.ctrl._handle_command("/quit")
        self.assertFalse(self.agent._running)

    def test_handle_command_save(self):
        self.ctrl._handle_command("/save")
        self.agent.consolidator.consolidate.assert_called_once()

    def test_handle_command_forget(self):
        self.ctrl._handle_command("/forget")
        self.agent.short_term.clear.assert_called_once()

    def test_handle_command_unknown(self):
        self.agent.ui = MagicMock()
        # TUI-1 后命令输出统一走 emit（sink 缺省为 print），断言实际输出
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.ctrl._handle_command("/unknown_cmd")
        self.assertIn("未知命令", buf.getvalue())

    def test_on_boot_with_custom_greeting(self):
        from core.agent import AgentState
        self.agent.personality.config.first_run_greeting = "Welcome!"
        self.agent.ui = MagicMock()
        self.ctrl._on_boot()
        self.agent.ui.display.respond.assert_called_once()
        self.assertEqual(self.agent.state, AgentState.IDLE)

    def test_reset_react_on_agent(self):
        from core.agent import Agent, AgentState
        # Use the real _reset_react from Agent
        # L-03: _react_messages 死代码已删除，不再参与重置
        agent = MagicMock(spec=Agent)
        agent._react_iteration = 3
        agent._tool_calls_pending = [{"name": "test"}]
        Agent._reset_react(agent)
        self.assertEqual(agent._react_iteration, 0)
        self.assertEqual(agent._tool_calls_pending, [])


class TestStreamTagFilter(unittest.TestCase):
    """M-15: 流式标签过滤——<think>/<tool_call> 跨 chunk 也不得泄漏。"""

    def _run(self, chunks):
        f = _StreamTagFilter()
        out = "".join(f.feed(c) for c in chunks)
        return out + f.flush()

    def test_tool_call_block_suppressed(self):
        out = self._run(["你好", "<tool_call>", '{"name": "x"}', "</tool_call>", "再见"])
        self.assertEqual(out, "你好再见")

    def test_tags_split_across_chunks(self):
        chunks = ["先说一句", "<tool", "_call>", '{"name": "web_search"}',
                  "</tool", "_call>", "后一句"]
        out = self._run(chunks)
        self.assertEqual(out, "先说一句后一句")

    def test_close_tag_split_at_angle_bracket(self):
        out = self._run(["<tool_call>abc</tool_call", ">尾巴"])
        self.assertEqual(out, "尾巴")

    def test_think_block_suppressed(self):
        out = self._run(["<th", "ink>想了想", "</think>", "正式回复"])
        self.assertEqual(out, "正式回复")

    def test_angle_bracket_in_normal_text(self):
        out = self._run(["1 < 2，<div> 不是目标标签"])
        self.assertEqual(out, "1 < 2，<div> 不是目标标签")

    def test_unclosed_tag_suppressed_at_flush(self):
        out = self._run(["可见", "<think>没闭合的思考"])
        self.assertEqual(out, "可见")

    def test_incomplete_tag_prefix_flushed_as_text(self):
        out = self._run(["文本结尾<tool"])
        self.assertEqual(out, "文本结尾<tool")

    def test_normal_text_streams_immediately(self):
        f = _StreamTagFilter()
        self.assertEqual(f.feed("实时"), "实时")
        self.assertEqual(f.feed("输出"), "输出")
        self.assertEqual(f.flush(), "")


class TestCliFrontendStreamingFilter(unittest.TestCase):
    """M-15: _CliFrontend 逐 token 输出经过标签过滤状态机。"""

    def _make_frontend(self):
        return _CliFrontend(MagicMock(), "TestBot")

    def test_terminal_output_has_no_tag_markup(self):
        fe = self._make_frontend()
        chunks = ["你好", "<tool", "_call>", '{"name": "web_search", "secret": 1}',
                  "</tool", "_call>", "，我查查"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            for c in chunks:
                fe.on_token(c)
            fe.on_message_done("你好，我查查")
        out = buf.getvalue()
        self.assertNotIn("tool_call", out)
        self.assertNotIn("web_search", out)
        self.assertIn("你好", out)
        self.assertIn("我查查", out)
        # 名字前缀只在第一个可见文本时打印一次
        self.assertEqual(out.count("TestBot:"), 1)

    def test_pure_tool_stream_rerenders_on_done(self):
        """整段流都是工具标记时：终端不流式，完成后整段渲染干净文本。"""
        fe = self._make_frontend()
        buf = io.StringIO()
        with redirect_stdout(buf):
            fe.on_token("<tool_call>")
            fe.on_token("{}")
            fe.on_token("</tool_call>")
            fe.on_message_done("最终回复")
        out = buf.getvalue()
        self.assertNotIn("TestBot:", out)  # 无可见文本，不留裸前缀
        self.assertEqual(out, "")
        fe._ui.display.respond.assert_called_once_with("最终回复", prefix="TestBot")

    def test_think_then_text_flushes_on_done(self):
        fe = self._make_frontend()
        buf = io.StringIO()
        with redirect_stdout(buf):
            for c in ["<think>思考一下</think>", "真正的回复"]:
                fe.on_token(c)
            fe.on_message_done("真正的回复")
        out = buf.getvalue()
        self.assertNotIn("think", out)
        self.assertNotIn("思考一下", out)
        self.assertIn("真正的回复", out)


if __name__ == "__main__":
    unittest.main()
