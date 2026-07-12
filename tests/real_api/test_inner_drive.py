"""Real API tests for InnerDriveAgent."""
import os
import sys
import unittest

sys.path.insert(0, ".")

from tests.real_api.conftest import RealAPITestCase


class TestRealInnerDrive(RealAPITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from config import load_config
        cfg = load_config()
        cls.cfg = cfg

        from core.provider import DeepSeekProvider
        cls.provider = DeepSeekProvider(
            endpoint=cfg.api_endpoint, api_key=cfg.api_key,
            model=cfg.api_model, timeout=cfg.api_timeout,
        )

        # Setup minimal agent with real memory
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
        from memory.retrieval import MemoryRetriever
        cls.retriever = MemoryRetriever(cls.ltm)

        from tools.traits import ToolRegistry
        from tools.memory_tools import RecallTool, RememberTool
        cls.tool_registry = ToolRegistry()
        cls.tool_registry.register(RecallTool(cls.retriever, cls.ltm))
        cls.tool_registry.register(RememberTool(cls.ltm))

    def test_assess_casual_chat(self):
        from core.inner_drive import InnerDriveAgent
        agent = InnerDriveAgent(
            provider=self.provider, personality=self.personality,
            ltm=self.ltm, retriever=self.retriever,
            short_term=self.short_term, tool_registry=self.tool_registry,
        )
        result = agent.assess("你好")
        self.assertIsNotNone(result)
        # Simple greeting should not need external tools
        # (but we don't enforce this - LLM may vary)

    def test_assess_url_request(self):
        from core.inner_drive import InnerDriveAgent
        agent = InnerDriveAgent(
            provider=self.provider, personality=self.personality,
            ltm=self.ltm, retriever=self.retriever,
            short_term=self.short_term, tool_registry=self.tool_registry,
        )
        result = agent.assess("看看这个链接 https://example.com")
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_external_tools)


if __name__ == "__main__":
    unittest.main()
