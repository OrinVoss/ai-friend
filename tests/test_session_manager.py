"""Tests for web/session.py — SessionManager role/session binding."""
import asyncio
import unittest
from unittest.mock import MagicMock, patch

from config import Config
from web.session import SessionManager


class TestSessionManagerRoleBinding(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.cfg.db_path = ":memory:"
        self.cfg.personality_file = "personality.json"
        self.cfg.api_endpoint = "http://localhost"
        self.cfg.api_key = "test"
        self.cfg.api_model = "test"
        self.cfg.embedding_endpoint = "http://localhost:8080/v1/embeddings"
        self.cfg.embedding_dim = 768
        self.cfg.temperature = 0.7
        self.cfg.max_tokens = 512
        self.cfg.thinking = False
        self.cfg.reasoning_effort = "low"
        self.cfg.api_timeout = 10
        self.cfg.short_term_capacity = 10
        self.cfg.proactive_min_idle = 60
        self.cfg.consolidation_interval = 5
        self.cfg.conversation_examples = []

        self.manager = SessionManager(self.cfg)
        asyncio.run(self.manager.open())

    def tearDown(self):
        asyncio.run(self.manager.shutdown())

    def test_get_or_create_binds_session_to_role(self):
        sid, agent = self.manager.get_or_create(role_id="小星")
        self.assertEqual(sid, "小星")
        self.assertEqual(agent.role_id, "小星")
        self.assertEqual(agent.session_id, "小星")

    def test_get_or_create_reuses_existing_session(self):
        sid1, agent1 = self.manager.get_or_create(role_id="小星")
        sid2, agent2 = self.manager.get_or_create(session_id="小星")
        self.assertEqual(sid1, sid2)
        self.assertIs(agent1, agent2)

    def test_one_role_one_session(self):
        _, agent1 = self.manager.get_or_create(role_id="小星")
        _, agent2 = self.manager.get_or_create(role_id="小星")
        self.assertIs(agent1, agent2)

    def test_different_roles_different_sessions(self):
        _, agent1 = self.manager.get_or_create(role_id="小星")
        _, agent2 = self.manager.get_or_create(role_id="小明")
        self.assertIsNot(agent1, agent2)
        self.assertEqual(agent1.role_id, "小星")
        self.assertEqual(agent2.role_id, "小明")

    def test_session_role_persisted(self):
        self.manager.get_or_create(role_id="小星")
        role = asyncio.run(self.manager.repo.get_role_for_session("小星"))
        self.assertEqual(role, "小星")

    def test_remove_session(self):
        sid, agent = self.manager.get_or_create(role_id="小星")
        self.assertIn(sid, self.manager._sessions)
        self.manager.remove(sid)
        self.assertNotIn(sid, self.manager._sessions)


if __name__ == "__main__":
    unittest.main()
