"""Tests for core/cli_controller.py"""
import unittest
from unittest.mock import MagicMock, patch

from core.cli_controller import CliController


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
        self.agent._react_messages = None
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
        self.agent.config.personality_file = "test_personality.json"
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
        self.ctrl._handle_command("/unknown_cmd")
        self.agent.ui.display.print_system.assert_called()

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
        agent = MagicMock(spec=Agent)
        agent._react_messages = [{"role": "user", "content": "test"}]
        agent._react_iteration = 3
        agent._tool_calls_pending = [{"name": "test"}]
        Agent._reset_react(agent)
        self.assertIsNone(agent._react_messages)
        self.assertEqual(agent._react_iteration, 0)
        self.assertEqual(agent._tool_calls_pending, [])


if __name__ == "__main__":
    unittest.main()
