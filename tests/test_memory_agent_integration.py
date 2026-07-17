"""Integration tests: MemoryAgent into InnerDrive (use_memory_agent, MA-001)."""
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.inner_drive import InnerDriveAgent
from memory.memory_agent import MemoryAnswer, MemoryEvidence
from models.conversation import MemoryContext
from tools.traits import ToolRegistry


def _json_resp():
    return json.dumps({
        "needs_external_tools": False,
        "reasoning": "测试推理",
        "summary": "测试摘要",
    }, ensure_ascii=False)


def _empty_mem_ctx():
    return MemoryContext(facts=[], experiences=[], reflections=[], relationship={})


def _make_drive(memory_agent=None):
    provider = MagicMock()
    provider.generate.return_value = _json_resp()
    retriever = MagicMock()
    retriever.retrieve_for_query.return_value = _empty_mem_ctx()
    personality = MagicMock()
    personality.config.name = "Luna"
    personality.config.traits = {}
    personality.config.speaking_style = "活泼"
    personality.config.backstory = ""
    personality.config.interests = []
    personality.emotion.to_prompt_summary.return_value = {
        "dominant_emotion": "neutral", "valence": 0.0, "arousal": 0.3,
    }
    short_term = MagicMock()
    short_term.format_for_prompt.return_value = ""
    drive = InnerDriveAgent(
        provider=provider, personality=personality, ltm=MagicMock(),
        retriever=retriever, short_term=short_term,
        tool_registry=ToolRegistry(),
        memory_agent=memory_agent,
    )
    return drive, provider, retriever


def _ma_answer():
    return MemoryAnswer(
        answer="preference|最爱食物: 披萨",
        confidence=0.8,
        evidences=[MemoryEvidence(
            "fact", 1, "preference|最爱食物: 披萨", 0.9, "2026-07-15 10:00:00")],
    )


class TestMemoryAgentIntegration(unittest.TestCase):
    def test_memory_agent_path_replaces_retriever(self):
        ma = MagicMock()
        ma.answer = AsyncMock(return_value=_ma_answer())
        drive, provider, retriever = _make_drive(memory_agent=ma)

        result = drive.assess("我想知道按照你的记忆我平时最喜欢吃的东西是什么")

        self.assertIn("披萨", result.context_summary)
        self.assertIn("置信度", result.context_summary)
        retriever.retrieve_for_query.assert_not_called()
        ma.answer.assert_awaited_once_with("我想知道按照你的记忆我平时最喜欢吃的东西是什么")
        # Agent 1 的 prompt 也应携带同一份摘要（一个替换点升级两个消费方）
        messages = provider.generate.call_args.args[0]
        self.assertIn("披萨", messages[0]["content"])

    def test_memory_agent_failure_falls_back(self):
        ma = MagicMock()
        ma.answer = AsyncMock(side_effect=RuntimeError("boom"))
        drive, _, retriever = _make_drive(memory_agent=ma)

        result = drive.assess("我想知道按照你的记忆我平时最喜欢吃的东西是什么")

        retriever.retrieve_for_query.assert_called_once()
        self.assertIsNotNone(result.context_summary)

    def test_flag_off_uses_retriever(self):
        drive, _, retriever = _make_drive(memory_agent=None)

        result = drive.assess("我想知道按照你的记忆我平时最喜欢吃的东西是什么")

        retriever.retrieve_for_query.assert_called_once()
        self.assertIsNotNone(result.context_summary)

    def test_short_input_path_uses_memory_agent(self):
        ma = MagicMock()
        ma.answer = AsyncMock(return_value=_ma_answer())
        drive, provider, retriever = _make_drive(memory_agent=ma)

        result = drive.assess("你好")

        provider.generate.assert_not_called()  # 短输入跳过 LLM
        self.assertIn("披萨", result.context_summary)
        retriever.retrieve_for_query.assert_not_called()

    def test_format_memory_answer_markers(self):
        from core.inner_drive import InnerDriveAgent as IDA
        ma = MemoryAnswer(
            answer="a: 1 vs a: 2", confidence=0.25,
            contradictions=["a: 1 vs a: 2"], needs_more_evidence=True,
        )
        text = IDA._format_memory_answer(ma)
        self.assertIn("⚠️ 矛盾记忆", text)
        self.assertIn("待确认", text)
        self.assertEqual(IDA._format_memory_answer(None), "")
        self.assertEqual(IDA._format_memory_answer(MemoryAnswer(answer="", confidence=0.0)), "")


class TestMessageHandlerWiring(unittest.TestCase):
    def _handler(self, use_memory_agent):
        from core.message_handler import MessageHandler
        a = MagicMock()
        a.config.use_memory_agent = use_memory_agent
        a.config.prompt_cache_ttl_seconds = 60
        a.config.agent1_short_input_threshold = 20
        a._tool_call_history = []
        a.consolidator._embed = None
        return MessageHandler(a)

    def test_wires_memory_agent_when_enabled(self):
        handler = self._handler(True)
        handler._ensure_inner_drive()
        self.assertIsNotNone(handler._inner_drive._memory_agent)

    def test_no_memory_agent_when_disabled(self):
        handler = self._handler(False)
        handler._ensure_inner_drive()
        self.assertIsNone(handler._inner_drive._memory_agent)


if __name__ == "__main__":
    unittest.main()
