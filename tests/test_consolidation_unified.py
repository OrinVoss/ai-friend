"""Tests for #164: memory consolidation unified LLM call path."""
import unittest
from unittest.mock import MagicMock, patch

from models.conversation import Turn


class TestConsolidationUnified(unittest.TestCase):
    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.ltm = MagicMock()
        self.ltm.repo.upsert_fact_v2 = MagicMock()
        self.llm = MagicMock()
        self.config = MagicMock()
        self.config.consolidation_unified_call = True
        self.consolidator = MemoryConsolidator(
            self.ltm, self.llm, config=self.config
        )
        # Replace real lifecycle with mock so run_async bridge is safe.
        self.consolidator._lifecycle = MagicMock()
        self.consolidator._lifecycle.promote_fact = MagicMock()
        self.consolidator._lifecycle.create_insight = MagicMock()
        self.consolidator._lifecycle.observe = MagicMock()
        # No extra LLM calls from relationship / care / embed / prune.
        self.consolidator._update_relationship = MagicMock()
        self.consolidator._extract_care_clues = MagicMock()
        self.consolidator._embed_new_items = MagicMock()
        self.consolidator._prune = MagicMock()

        self.ltm.get_recent_experiences.return_value = []
        self.ltm.get_all_active_facts.return_value = []
        self.ltm.get_recent_reflections.return_value = []
        self.ltm.get_relationship.return_value = {"trust": 0.5}

        self.personality = MagicMock()
        self.personality.emotion.dominant_emotion = "content"

    def _buffer_long_user_turn(self):
        # 接地校验要求 mock 的事实值（咖啡）能在用户话语中找到出处
        t = Turn(turn_id=1, role="user", content="我喜欢喝咖啡，" + "x" * 250)
        self.consolidator._pending_buffer = [t]
        self.consolidator._seen_ids = {(1, "user")}

    def _unified_output(self, with_insight: bool = True) -> str:
        out = """FACTS:
FACT|preference|饮品|咖啡|0.8|0.7|user_fact

EXPERIENCE:
SUMMARY: 用户参与了一次测试对话
TONE: 平静
SIGNIFICANCE: 0.6
IMPORTANCE: 0.5
TAGS: 测试,对话
"""
        if with_insight:
            out += """
INSIGHT:
{"hypothesis": "用户可能愿意参与测试", "insight_type": "pattern", "evidence": [], "confidence": 0.5, "needs_more_evidence": true}
"""
        return out

    def test_unified_path_persists_all_three_with_one_llm_call(self):
        """合并路径：一次 LLM 调用，facts/experience/insight 各落库一次。"""
        self._buffer_long_user_turn()
        self.llm.return_value = self._unified_output(with_insight=True)

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            self.consolidator.consolidate(MagicMock(), self.personality)

        self.assertEqual(self.llm.call_count, 1)
        self.consolidator._lifecycle.promote_fact.assert_called_once()
        self.ltm.store_experience.assert_called_once()
        self.consolidator._lifecycle.create_insight.assert_called_once()

    def test_unified_missing_insight_section_skips_insight(self):
        """格式损坏（缺 INSIGHT 段）：其余两段正常落库并记 warning。"""
        self._buffer_long_user_turn()
        self.llm.return_value = self._unified_output(with_insight=False)

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            with self.assertLogs("memory.consolidation", level="WARNING") as cm:
                self.consolidator.consolidate(MagicMock(), self.personality)

        self.assertEqual(self.llm.call_count, 1)
        self.consolidator._lifecycle.promote_fact.assert_called_once()
        self.ltm.store_experience.assert_called_once()
        self.consolidator._lifecycle.create_insight.assert_not_called()
        self.assertTrue(
            any("unified output missing INSIGHT section" in m for m in cm.output)
        )

    def test_unified_unparseable_fallback_to_old_path(self):
        """完全无法解析：回退旧三次调用路径，总调用 1+3 次，数据不丢。"""
        self._buffer_long_user_turn()

        def side_effect(prompt, temperature=0.2):
            # First call is the unified prompt.
            if "FACTS:" in prompt and "EXPERIENCE:" in prompt:
                return "这不是统一格式输出"
            # Fallback old-path prompts.
            if "从这段对话中提取" in prompt:
                return "FACT|preference|饮品|咖啡|0.8|0.7|user_fact"
            if "将这段对话总结为一段共享体验" in prompt:
                return ("SUMMARY: 回退体验\nTONE: 平静\n"
                        "SIGNIFICANCE: 0.6\nIMPORTANCE: 0.5\nTAGS: 回退")
            if "假设性洞察" in prompt:
                return ('{"hypothesis": "回退洞察", "insight_type": "pattern", '
                        '"evidence": [], "confidence": 0.5, '
                        '"needs_more_evidence": true}')
            return ""

        self.llm.side_effect = side_effect

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            self.consolidator.consolidate(MagicMock(), self.personality)

        self.assertEqual(self.llm.call_count, 4)
        self.consolidator._lifecycle.promote_fact.assert_called_once()
        self.ltm.store_experience.assert_called_once()
        self.consolidator._lifecycle.create_insight.assert_called_once()

    def test_unified_disabled_uses_old_path(self):
        """consolidation_unified_call=false：完全走旧三次调用路径。"""
        self.config.consolidation_unified_call = False
        self._buffer_long_user_turn()

        def side_effect(prompt, temperature=0.2):
            if "从这段对话中提取" in prompt:
                return "FACT|preference|饮品|咖啡|0.8|0.7|user_fact"
            if "将这段对话总结为一段共享体验" in prompt:
                return ("SUMMARY: 旧路径体验\nTONE: 平静\n"
                        "SIGNIFICANCE: 0.6\nIMPORTANCE: 0.5\nTAGS: 旧路径")
            if "假设性洞察" in prompt:
                return ('{"hypothesis": "旧路径洞察", "insight_type": "pattern", '
                        '"evidence": [], "confidence": 0.5, '
                        '"needs_more_evidence": true}')
            return ""

        self.llm.side_effect = side_effect

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            self.consolidator.consolidate(MagicMock(), self.personality)

        self.assertEqual(self.llm.call_count, 3)
        self.consolidator._lifecycle.promote_fact.assert_called_once()
        self.ltm.store_experience.assert_called_once()
        self.consolidator._lifecycle.create_insight.assert_called_once()

    def test_l2_turn_uses_old_path(self):
        """L2 节奏批次走旧路径，L2 insight 正常触发。"""
        self.consolidator._consolidation_count = 2  # next +1 -> 3 -> L2
        self._buffer_long_user_turn()

        def side_effect(prompt, temperature=0.2):
            if "从这段对话中提取" in prompt:
                return "FACT|preference|饮品|咖啡|0.8|0.7|user_fact"
            if "将这段对话总结为一段共享体验" in prompt:
                return ("SUMMARY: L2 批次体验\nTONE: 平静\n"
                        "SIGNIFICANCE: 0.6\nIMPORTANCE: 0.5\nTAGS: L2")
            if "行为模式" in prompt:
                return ('{"hypothesis": "L2 洞察", "insight_type": "pattern", '
                        '"evidence": [], "confidence": 0.5, '
                        '"needs_more_evidence": true}')
            return ""

        self.llm.side_effect = side_effect

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            self.consolidator.consolidate(MagicMock(), self.personality)

        self.assertEqual(self.llm.call_count, 3)
        # L2 prompt should have been used.
        prompts = [call.args[0] for call in self.llm.call_args_list]
        self.assertTrue(any("行为模式" in p for p in prompts))
        self.consolidator._lifecycle.create_insight.assert_called_once()

    def test_l3_turn_uses_old_path(self):
        """L3 节奏批次走旧路径，L3 insight 正常触发。"""
        self.consolidator._consolidation_count = 9  # next +1 -> 10 -> L3
        self._buffer_long_user_turn()

        def side_effect(prompt, temperature=0.2):
            if "从这段对话中提取" in prompt:
                return "FACT|preference|饮品|咖啡|0.8|0.7|user_fact"
            if "将这段对话总结为一段共享体验" in prompt:
                return ("SUMMARY: L3 批次体验\nTONE: 平静\n"
                        "SIGNIFICANCE: 0.6\nIMPORTANCE: 0.5\nTAGS: L3")
            if "长期模式" in prompt or "深度动机" in prompt:
                return ('{"hypothesis": "L3 洞察", "insight_type": "emotion", '
                        '"evidence": [], "confidence": 0.6, '
                        '"needs_more_evidence": true}')
            return ""

        self.llm.side_effect = side_effect

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            self.consolidator.consolidate(MagicMock(), self.personality)

        self.assertEqual(self.llm.call_count, 3)
        prompts = [call.args[0] for call in self.llm.call_args_list]
        self.assertTrue(
            any("长期模式" in p or "深度动机" in p for p in prompts)
        )
        self.consolidator._lifecycle.create_insight.assert_called_once()

    def test_unified_call_uses_enlarged_token_budget(self):
        """防回归：统一调用必须带 max_tokens>=1024（默认 512 会截掉末段，
        2026-07-21 生产事故：finish_reason=length 导致 INSIGHT 段丢失）。"""
        self._buffer_long_user_turn()
        self.llm.return_value = self._unified_output(with_insight=True)

        with patch("memory.consolidation.run_async",
                   lambda coro: coro.send(None)):
            self.consolidator.consolidate(MagicMock(), self.personality)

        _, kwargs = self.llm.call_args
        self.assertGreaterEqual(kwargs.get("max_tokens", 0), 1024)


if __name__ == "__main__":
    unittest.main()
