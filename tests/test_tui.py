"""TUI-1/TUI-2（全屏界面）无头测试：ChatModel / TuiChatApp 写入路由 /
命令 sink / Esc 中断。

本环境无 Windows 控制台，不渲染——Application 以 DummyOutput 构造，
只验证模型与路由逻辑；视觉效果需人工确认。
"""
import logging
import tempfile
import unittest
from unittest.mock import MagicMock

from prompt_toolkit.output import DummyOutput

from core.provider import StreamAborted


def _make_controller():
    controller = MagicMock()
    controller.a.personality.config.name = "Luna"
    controller.a.personality.config.first_run_greeting = ""
    controller.a.turn_count = 5
    controller.a._running = True
    controller._status_snapshot = lambda: {
        "emotion": "engaged", "turn": 5, "sleeping": False}
    return controller


def _make_app(controller=None):
    from ui.tui import TuiChatApp
    controller = controller or _make_controller()
    ui = MagicMock()
    ui._history_file = tempfile.mktemp(suffix=".hist")
    engine = MagicMock()
    app = TuiChatApp(controller, engine, ui, output=DummyOutput())
    return app, controller, engine


def _joined(app):
    return "".join(t for _, t in app.model.fragments())


class TestChatModel(unittest.TestCase):
    def test_add_and_fragments_with_prefix(self):
        from ui.tui import ChatModel
        m = ChatModel()
        m.add("user", "你好", prefix="> ")
        m.add("ai", "第一行\n第二行", prefix="● Luna: ")
        frags = m.fragments()
        texts = [t for _, t in frags if t != "\n"]
        self.assertIn("> 你好", texts)
        self.assertIn("● Luna: ", texts)          # AI 前缀是独立 fragment
        self.assertIn("第一行", texts)
        # 续行按前缀宽度缩进（"● Luna: " 宽 8；前缀与内容是独立 fragment，按拼接文本断言）
        joined = "".join(t for _, t in frags)
        self.assertIn(" " * 8 + "第二行", joined)

    def test_ai_stage_direction_dimmed(self):
        from ui.tui import ChatModel
        m = ChatModel()
        m.add("ai", "（挠头）你说得对", prefix="● Luna: ")
        frags = m.fragments()
        dim = [t for s, t in frags if s == "class:dim"]
        plain = [t for s, t in frags if s == "" and t.strip()]
        self.assertIn("（挠头）", dim)
        self.assertIn("你说得对", plain)

    def test_stream_accumulates_single_block(self):
        from ui.tui import ChatModel
        m = ChatModel()
        m.stream("ai", "● Luna: ", "你")
        m.stream("ai", "● Luna: ", "好呀")
        self.assertEqual(len(m.blocks), 1)
        self.assertEqual(m.blocks[0][2], "你好呀")
        # 流式结束后 end_stream 不重复落块
        m.end_stream("ai", "● Luna: ", "你好呀")
        self.assertEqual(len(m.blocks), 1)
        # 未流式的整段回复落新块
        m.end_stream("ai", "● Luna: ", "整段回复")
        self.assertEqual(len(m.blocks), 2)

    def test_block_cap(self):
        from ui.tui import ChatModel
        m = ChatModel()
        for i in range(ChatModel.MAX_BLOCKS + 50):
            m.add("ai", f"块{i}")
        self.assertEqual(len(m.blocks), ChatModel.MAX_BLOCKS)
        self.assertEqual(m.blocks[-1][2], f"块{ChatModel.MAX_BLOCKS + 49}")

    def test_raw_fragments_parse_ansi(self):
        from ui.tui import ChatModel
        m = ChatModel()
        m.add("raw", "\x1b[31m红色\x1b[0m")
        styles = [s for s, t in m.fragments() if t.strip()]
        self.assertTrue(any("ansired" in s or "#" in s or s for s in styles))


class TestTuiChatApp(unittest.TestCase):
    def test_preload_and_on_boot_sink(self):
        app, controller, _ = _make_app()
        app.preload()
        controller.a.personality.config.first_run_greeting = "开机问候"
        from core.cli_controller import CliController
        CliController._on_boot(controller.a and controller, sink=app.post_ai)
        joined = _joined(app)
        self.assertIn("欢迎", joined)
        self.assertIn("开机问候", joined)
        self.assertIn("Luna: ", joined)

    def test_submit_message_dispatches_engine(self):
        app, controller, engine = _make_app()
        buf = MagicMock()
        buf.text = "你好"
        app._on_submit(buf)
        engine.handle_message.assert_called_once()
        args = engine.handle_message.call_args.args
        self.assertEqual(args[0], "你好")
        self.assertIn("> 你好", _joined(app))

    def test_submit_slash_command_goes_to_controller(self):
        app, controller, _ = _make_app()
        buf = MagicMock()
        buf.text = "/help"
        app._on_submit(buf)
        controller._handle_command.assert_called_once()
        args, kwargs = controller._handle_command.call_args
        self.assertEqual(args[0], "/help")
        self.assertEqual(kwargs.get("sink") or args[1], app.post_raw)

    def test_submit_exit_requests_exit(self):
        app, controller, _ = _make_app()
        buf = MagicMock()
        buf.text = "/exit"
        app._on_submit(buf)
        self.assertFalse(controller.a._running)
        self.assertTrue(app._done.is_set())

    def test_frontend_streaming_flow(self):
        app, _, _ = _make_app()
        fe = app.frontend
        fe.on_token("你好")           # 普通文本直出
        fe.on_token("<tool")          # 跨 chunk 标签前缀被抑制
        fe.on_token("_call>{}</tool_call>")  # 完整标签被吞
        fe.on_token("！")
        fe.on_message_done("你好！")
        joined = _joined(app)
        self.assertIn("Luna: 你好！", joined)
        self.assertNotIn("tool_call", joined)

    def test_esc_aborts_stream_and_raises(self):
        """TUI-2：Esc 中断——on_token 抛 StreamAborted，块补"已中断"注记。"""
        app, _, _ = _make_app()
        fe = app.frontend
        fe.on_token("说到一半")
        app.interrupt.set()
        with self.assertRaises(StreamAborted):
            fe.on_token("后续内容")
        joined = _joined(app)
        self.assertIn("说到一半", joined)
        self.assertIn("已中断", joined)
        self.assertFalse(app._generating)

    def test_completion_menu_mounted_and_while_typing(self):
        """TUI-2 实测修复：补全菜单挂进 FloatContainer + complete_while_typing。"""
        from prompt_toolkit.layout import FloatContainer
        app, _, _ = _make_app()
        root = app.app.layout.container
        self.assertIsInstance(root, FloatContainer)
        self.assertEqual(len(root.floats), 1)  # CompletionsMenu float
        self.assertTrue(app.input_buffer.complete_while_typing())

    def test_log_sink_receives_warning_not_info(self):
        from core.logging_setup import setup_logging, use_prompt_toolkit_console
        app, _, _ = _make_app()
        setup_logging("INFO")
        try:
            use_prompt_toolkit_console("WARNING", sink=app.post_log)
            logging.getLogger("tui.test").info("info-不该进面板")
            logging.getLogger("tui.test").warning("warning-该进面板")
            joined = "\n".join(app.model.logs)
            self.assertIn("warning-该进面板", joined)
            self.assertNotIn("info-不该进面板", joined)
        finally:
            setup_logging("INFO")  # 恢复，避免影响其他测试

    def test_status_fragments_contain_activity_and_spinner_hint(self):
        app, _, _ = _make_app()
        app.set_activity("她在想…")
        text = "".join(t for _, t in app._status_fragments())
        self.assertIn("她在想…", text)
        self.assertIn("esc 中断", text)
        self.assertIn("F2 日志", text)
        app.post_ai("回复")  # 回复落块时清除活动状态
        self.assertEqual(app.model.activity, "")


class TestReactLoopAbort(unittest.TestCase):
    """TUI-2：StreamAborted 经 provider 直穿（不重试），_react_loop 返回空串。"""

    def test_react_loop_abort_returns_empty(self):
        from core.agent import Agent
        from tools.traits import ToolRegistry
        a = Agent.__new__(Agent)
        a.provider = MagicMock()
        a.provider.generate.side_effect = StreamAborted()
        a._tool_registry = ToolRegistry()
        a._max_tool_iterations = 3
        a._max_fake_actions = 3
        a._degrade_threshold = 3
        a._tool_failures = 0
        a._react_iteration = 0
        a._tool_calls_pending = []
        a.config = MagicMock()
        a.personality = MagicMock()
        a.ltm = MagicMock()
        a.short_term = MagicMock()
        out = a._react_loop([{"role": "user", "content": "hi"}],
                            add_to_history=False, skip_post_process=True)
        self.assertEqual(out, "")
        a.provider.generate.assert_called_once()  # 不重试
        a.ltm.repo.insert_turn_sync.assert_not_called()  # 不落库


class TestCommandSink(unittest.TestCase):
    """_handle_command 的 sink 输出（TUI 面板路径）。"""

    def _controller(self):
        from core.cli_controller import CliController
        agent = MagicMock()
        agent.turn_count = 5
        agent.ltm.get_relationship.return_value = {"trust": 0.62}
        agent.ltm.get_all_active_facts.return_value = [1, 2, 3]
        agent.ltm.get_relationship_history.return_value = []
        agent.personality.emotion.dominant_emotion = "engaged"
        agent.personality.emotion.valence = 0.5
        agent.personality.emotion.arousal = 0.4
        return CliController(agent)

    def test_help_sink(self):
        out = []
        self._controller()._handle_command("/help", sink=out.append)
        self.assertEqual(len(out), 1)
        self.assertIn("/exit", out[0])

    def test_status_sink_uses_rel_bar(self):
        out = []
        self._controller()._handle_command("/status", sink=out.append)
        self.assertIn("trust", out[0])
        self.assertIn("▰", out[0])

    def test_mood_sink(self):
        out = []
        self._controller()._handle_command("/mood", sink=out.append)
        self.assertIn("engaged", out[0])

    def test_unknown_command_sink(self):
        out = []
        self._controller()._handle_command("/nope", sink=out.append)
        self.assertIn("未知命令", out[0])


if __name__ == "__main__":
    unittest.main()
