"""Tests for unified-pipeline P1: ConversationEngine + CLI gray switch."""
import unittest
from unittest.mock import MagicMock

from core.conversation_engine import ConversationEngine, Frontend


class RecordingFrontend(Frontend):
    def __init__(self):
        self.events = []

    def on_token(self, token): self.events.append(("token", token))
    def on_message_done(self, text): self.events.append(("done", text))
    def on_proactive(self, text): self.events.append(("proactive", text))
    def on_sleep_reply(self, text): self.events.append(("sleep", text))
    def on_status(self, status): self.events.append(("status", status))
    def on_error(self, error): self.events.append(("error", error))


def _mock_agent(sleeping=False):
    a = MagicMock()
    a._sleeping = sleeping
    a._messages.handle_message.return_value = "回复"
    a.process_proactive.return_value = "主动消息"
    a.process_explore.return_value = "探索分享"
    a.ltm.get_relationship.return_value = {"trust": 0.5}
    a.personality.emotion.dominant_emotion = "joyful"
    a.personality.emotion.valence = 0.6
    a.personality.emotion.arousal = 0.4
    a.personality.emotion.consecutive_negative = 0
    return a


class TestConversationEngine(unittest.TestCase):
    def test_handle_message_done_event(self):
        fe = RecordingFrontend()
        result = ConversationEngine(_mock_agent()).handle_message("你好", fe)
        self.assertEqual(result, "回复")
        self.assertEqual(fe.events, [("done", "回复")])

    def test_handle_message_sleep_reply(self):
        fe = RecordingFrontend()
        ConversationEngine(_mock_agent(sleeping=True)).handle_message("你好", fe)
        self.assertEqual(fe.events, [("sleep", "回复")])

    def test_on_token_threaded_through(self):
        a = _mock_agent()
        fe = RecordingFrontend()
        ConversationEngine(a).handle_message("你好", fe)
        _, kwargs = a._messages.handle_message.call_args
        # bound methods are new objects per access but compare equal by
        # (instance, function) — assertEqual, not assertIs
        self.assertEqual(kwargs["on_token"], fe.on_token)
        self.assertEqual(getattr(kwargs["on_token"], "__self__", None), fe)

    def test_on_status_threaded_through(self):
        """CLI-UI: engine 把 frontend 的 on_status 透传给管线。"""
        a = _mock_agent()
        fe = RecordingFrontend()
        ConversationEngine(a).handle_message("你好", fe)
        _, kwargs = a._messages.handle_message.call_args
        self.assertEqual(kwargs["on_status"], fe.on_status)
        self.assertEqual(getattr(kwargs["on_status"], "__self__", None), fe)

    def test_proactive_and_explore_events(self):
        fe = RecordingFrontend()
        engine = ConversationEngine(_mock_agent())
        engine.handle_proactive(fe)
        engine.handle_explore(fe)
        self.assertEqual(fe.events, [("proactive", "主动消息"), ("proactive", "探索分享")])

    def test_explore_silent_no_event(self):
        a = _mock_agent()
        a.process_explore.return_value = None
        fe = RecordingFrontend()
        ConversationEngine(a).handle_explore(fe)
        self.assertEqual(fe.events, [])

    def test_error_event_and_empty_result(self):
        a = _mock_agent()
        a._messages.handle_message.side_effect = RuntimeError("boom")
        fe = RecordingFrontend()
        result = ConversationEngine(a).handle_message("你好", fe)
        self.assertEqual(result, "")
        self.assertEqual(fe.events, [("error", "boom")])

    def test_two_frontends_equivalent_events(self):
        """Equivalence: same input → CLI mock frontend and Web mock frontend
        receive the same event sequence."""
        cli_fe, web_fe = RecordingFrontend(), RecordingFrontend()
        ConversationEngine(_mock_agent()).handle_message("你好", cli_fe)
        ConversationEngine(_mock_agent()).handle_message("你好", web_fe)
        self.assertEqual(cli_fe.events, web_fe.events)

    def test_state_queries(self):
        engine = ConversationEngine(_mock_agent())
        self.assertEqual(engine.get_relationship(), {"trust": 0.5})
        summary = engine.get_emotion_summary()
        self.assertEqual(summary["dominant"], "joyful")
        self.assertAlmostEqual(summary["valence"], 0.6)


class TestCliFrontend(unittest.TestCase):
    def test_stream_then_done_no_double_render(self):
        from core.cli_controller import _CliFrontend
        ui = MagicMock()
        fe = _CliFrontend(ui, "小星")
        fe.on_token("你")
        fe.on_token("好")
        fe.on_message_done("你好")
        ui.display.respond.assert_not_called()  # already streamed

    def test_done_without_stream_renders_whole(self):
        from core.cli_controller import _CliFrontend
        ui = MagicMock()
        fe = _CliFrontend(ui, "小星")
        fe.on_message_done("完整回复")
        ui.display.respond.assert_called_once_with("完整回复", prefix="小星")

    def test_sleep_reply_renders(self):
        from core.cli_controller import _CliFrontend
        ui = MagicMock()
        fe = _CliFrontend(ui, "小星")
        fe.on_sleep_reply("zzz...ZZZ...💤")
        ui.display.respond.assert_called_once_with("zzz...ZZZ...💤", prefix="💤小星")


class TestCliPromptToolkitLoop(unittest.TestCase):
    """CLI-UI（2026-07-26）：主循环改由 prompt_toolkit 读输入。"""

    def _make_agent(self, ui):
        a = MagicMock()
        a.personality.config.name = "Luna"
        a.personality.config.first_run_greeting = ""
        a._running = True
        a.turn_count = 0
        a.ui = ui
        return a

    def test_run_loop_reads_via_read_input_and_exits_cleanly(self):
        from unittest.mock import patch
        from core.cli_controller import CliController
        ui = MagicMock()
        ui.read_input.side_effect = KeyboardInterrupt
        ctrl = CliController(self._make_agent(ui))
        with patch("core.runtime_driver.RuntimeDriver") as mock_driver:
            ctrl.run()
        ui.read_input.assert_called_once()
        mock_driver.return_value.start_in_thread.assert_called_once()
        mock_driver.return_value.stop.assert_called_once()

    def test_slash_exit_stops_loop(self):
        from unittest.mock import patch
        from core.cli_controller import CliController
        ui = MagicMock()
        ui.read_input.side_effect = ["/exit", AssertionError("loop did not stop")]
        a = self._make_agent(ui)
        ctrl = CliController(a)
        with patch("core.runtime_driver.RuntimeDriver"):
            ctrl.run()
        self.assertFalse(a._running)

    def test_frontend_on_status_prints_dim_hint(self):
        from core.cli_controller import _CliFrontend
        ui = MagicMock()
        fe = _CliFrontend(ui, "小星")
        fe.on_status("她在翻工具箱…")
        ui.display.print_status.assert_called_once_with("她在翻工具箱…")


class TestStatusHints(unittest.TestCase):
    """CLI-UI: MessageHandler._transition 按阶段发射中文提示。"""

    def _handler(self):
        from core.message_handler import MessageHandler, MessageHandlerState
        mh = MessageHandler.__new__(MessageHandler)  # 只测 _transition，绕过装配
        mh._state = MessageHandlerState.IDLE
        return mh, MessageHandlerState

    def test_hints_for_pipeline_phases(self):
        mh, S = self._handler()
        seen = []
        mh._status_cb = seen.append
        mh._transition(S.ASSESSING)
        mh._transition(S.EXECUTING_TOOLS)
        mh._transition(S.GENERATING_RESPONSE)
        self.assertEqual(seen, ["她在想…", "她在翻工具箱…", "她在写回复…"])

    def test_no_hint_for_done_and_no_cb(self):
        mh, S = self._handler()
        seen = []
        mh._status_cb = seen.append
        mh._transition(S.DONE)  # DONE 无提示
        self.assertEqual(seen, [])
        mh._status_cb = None  # 无回调时静默
        mh._transition(S.ASSESSING)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
