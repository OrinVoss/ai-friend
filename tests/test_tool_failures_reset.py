"""H-07: _tool_failures 每条消息重置，失败额度不跨消息累积。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from tools.traits import ToolRegistry, ToolResult


_FAIL_XML = '<tool_call>\n{"name": "recall", "arguments": {"query": "x"}}\n</tool_call>'


def _make_agent(tmpdir):
    """真实 Agent + 真实 _react_loop，外部依赖全部 mock。"""
    from core.agent import Agent
    from config import Config

    cfg = Config()
    cfg.max_tokens = 512
    cfg.personality_file = os.path.join(tmpdir, "role.json")

    personality = MagicMock()
    personality.config.name = "TestBot"
    personality.config.interests = []
    personality.config.traits = []
    personality.emotion.dominant_emotion = "neutral"
    personality.emotion.valence = 0.4
    personality.emotion.arousal = 0.5
    personality.emotion.resentment = 0.0
    personality.emotion.emotion_events = []

    provider = MagicMock()

    short_term = MagicMock()
    short_term.get_all_reversed.return_value = []
    short_term.get_all.return_value = []

    agent = Agent(
        personality=personality,
        provider=provider,
        ltm=MagicMock(),
        retriever=MagicMock(),
        consolidator=MagicMock(),
        short_term=short_term,
        config=cfg,
    )
    # 一个总是失败的 recall 工具
    registry = ToolRegistry()
    failing = MagicMock()
    failing.name.return_value = "recall"
    failing.execute.return_value = ToolResult.fail("boom")
    registry.register(failing)
    agent._tool_registry = registry
    return agent, provider


class TestToolFailuresReset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()

    def test_tool_failures_do_not_accumulate_across_messages(self):
        agent, provider = _make_agent(self._tmpdir)

        # 消息 1：两次全失败 + 一次正常回复 → 消耗 2 次失败额度
        provider.generate.side_effect = [_FAIL_XML, _FAIL_XML, "第一条回复"]
        r1 = agent._react_loop([{"role": "user", "content": "第一条"}],
                               skip_post_process=True)
        self.assertEqual(r1, "第一条回复")
        self.assertEqual(agent._tool_failures, 2)

        # 消息 2：开头重置——本条第 1 次失败不应触发降级。
        # 修复前这里累积到 3，直接 break 返回降级文案。
        provider.generate.side_effect = [_FAIL_XML, "第二条回复"]
        r2 = agent._react_loop([{"role": "user", "content": "第二条"}],
                               skip_post_process=True)
        self.assertEqual(r2, "第二条回复")
        self.assertEqual(agent._tool_failures, 1)

    def test_degrade_threshold_still_works_within_one_message(self):
        """同一条消息内连续 3 次全失败仍然触发降级。"""
        agent, provider = _make_agent(self._tmpdir)
        provider.generate.side_effect = [_FAIL_XML] * 5
        result = agent._react_loop([{"role": "user", "content": "测试"}],
                                   skip_post_process=True)
        self.assertIn("暂时无法获取外部信息", result)
        self.assertEqual(agent._tool_failures, 3)


if __name__ == "__main__":
    unittest.main()
