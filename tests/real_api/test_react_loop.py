"""Real API integration test: full agent message processing."""
import sys
import unittest

sys.path.insert(0, ".")

from tests.real_api.conftest import RealAPITestCase


class TestRealMessageFlow(RealAPITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from config import load_config
        cfg = load_config()
        cls.cfg = cfg

        # Setup full agent with real API
        from core.provider import DeepSeekProvider
        cls.provider = DeepSeekProvider(
            endpoint=cfg.api_endpoint, api_key=cfg.api_key,
            model=cfg.api_model, temperature=0.7,
            max_tokens=cfg.max_tokens, timeout=cfg.api_timeout,
        )

        from storage.database import Database
        from storage.repository import Repository
        cls.db = Database(":memory:")
        cls.run_async(cls.db.open())
        cls.repo = Repository(cls.db)
        from memory.long_term import LongTermMemory
        cls.ltm = LongTermMemory(cls.repo)
        from memory.short_term import ConversationBuffer
        cls.short_term = ConversationBuffer(maxlen=100)
        from core.personality import Personality
        cls.personality = Personality.load(cfg.personality_file)

        def llm_gen(prompt, temperature=0.2):
            return cls.provider.generate(
                [{"role": "user", "content": prompt}],
                stream=False,
            )

        from memory.retrieval import MemoryRetriever
        cls.retriever = MemoryRetriever(cls.ltm, llm_rerank_fn=llm_gen)
        from memory.consolidation import MemoryConsolidator
        cls.consolidator = MemoryConsolidator(cls.ltm, llm_gen)

        from tools.traits import ToolRegistry
        from tools.memory_tools import RecallTool, RememberTool
        cls.tool_registry = ToolRegistry()
        cls.tool_registry.register(RecallTool(cls.retriever, cls.ltm))
        cls.tool_registry.register(RememberTool(cls.ltm))

        from core.agent import Agent
        cls.agent = Agent(
            personality=cls.personality, provider=cls.provider,
            ltm=cls.ltm, retriever=cls.retriever,
            consolidator=cls.consolidator, short_term=cls.short_term,
            config=cfg,
        )
        cls.agent._tool_registry = cls.tool_registry

    def test_process_message_returns_response(self):
        result = self.agent.process_message("你好")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_process_message_turn_count_advances(self):
        old_turn = self.agent.turn_count
        self.agent.process_message("你好！")
        self.assertGreater(self.agent.turn_count, old_turn)


if __name__ == "__main__":
    unittest.main()
