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
        ui.display.respond.assert_called_once_with("zzz...ZZZ...💤", prefix="小星")


class TestCliPrompt(unittest.TestCase):
    def test_prompt_printed_once_per_wait(self):
        """Field regression 2026-07-16: the input prompt must be printed once
        per wait, not on every 0.1s poll iteration."""
        from unittest.mock import patch
        from core.cli_controller import CliController

        a = MagicMock()
        a.personality.config.name = "Luna"
        a.personality.config.first_run_greeting = ""
        a._running = True
        a.turn_count = 0
        ui = MagicMock()
        a.ui = ui
        # no input for 3 polls, then Ctrl-C to exit
        ui.reader.read_line.side_effect = [None, None, None, KeyboardInterrupt]
        ctrl = CliController(a)
        with patch("core.runtime_driver.RuntimeDriver") as mock_driver, \
                patch("builtins.print") as mock_print:
            ctrl.run()

        prompt_calls = [c for c in mock_print.call_args_list
                        if c.args and "用户输入" in str(c.args[0])]
        self.assertEqual(len(prompt_calls), 1)
        mock_driver.return_value.start_in_thread.assert_called_once()
        mock_driver.return_value.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
