"""Tests for core/session_factory.py — unified assembly (unified-pipeline P0)."""
import asyncio
import os
import tempfile
import unittest

from config import Config
from core.personality import Personality
from core.session_factory import (assemble_session, build_embed_engine,
                                  build_provider)
from models.personality import PersonalityConfig
from storage.database import Database


class TestSessionFactory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config()
        self.cfg.db_path = os.path.join(self.tmp.name, "test.db")
        self.cfg.api_key = "test"
        self.db = Database(self.cfg.db_path)
        asyncio.run(self.db.open())

    def tearDown(self):
        asyncio.run(self.db.close())
        self.tmp.cleanup()

    def _bundle(self, session_id, **kw):
        personality = Personality(PersonalityConfig())
        provider = build_provider(self.cfg)
        return assemble_session(self.cfg, self.db, session_id, personality,
                                provider, **kw)

    def test_per_session_repositories_are_independent(self):
        """Each session gets its own Repository — no shared session_id race."""
        a = self._bundle("sess_a")
        b = self._bundle("sess_b")

        self.assertIsNot(a.repo, b.repo)
        self.assertEqual(a.repo.session_id, "sess_a")
        self.assertEqual(b.repo.session_id, "sess_b")

        asyncio.run(a.repo.upsert_fact("preference", "颜色", "蓝", confidence=0.9))
        facts_a = asyncio.run(a.repo.get_active_facts(limit=10))
        facts_b = asyncio.run(b.repo.get_active_facts(limit=10))
        self.assertEqual(len(facts_a), 1)
        self.assertEqual(len(facts_b), 0)

    def test_tool_sets_match_frontend_variants(self):
        """CLI registers file_tree, Web does not (preserved difference)."""
        cli = self._bundle("cli", include_file_tree=True)
        web = self._bundle("web")

        self.assertIsNotNone(cli.tool_registry.get("file_tree"))
        self.assertIsNone(web.tool_registry.get("file_tree"))
        for name in ("recall", "remember", "read_file", "notify",
                     "web_search", "web_fetch", "music_play", "glob", "grep"):
            self.assertIsNotNone(cli.tool_registry.get(name), name)
            self.assertIsNotNone(web.tool_registry.get(name), name)

    def test_llm_rerank_optional(self):
        """CLI passes an LLM rerank fn, Web does not (preserved difference)."""
        with_rerank = self._bundle("a", enable_llm_rerank=True)
        without = self._bundle("b")

        self.assertIsNotNone(with_rerank.retriever.llm_rerank_fn)
        self.assertIsNone(without.retriever.llm_rerank_fn)

    def test_bundle_wiring(self):
        bundle = self._bundle("sess")

        self.assertIs(bundle.agent._tool_registry, bundle.tool_registry)
        self.assertIs(bundle.agent.short_term, bundle.short_term)
        self.assertIs(bundle.agent.retriever, bundle.retriever)
        self.assertIs(bundle.agent.consolidator, bundle.consolidator)
        self.assertEqual(bundle.agent.turn_count, 0)
        self.assertEqual(bundle.repo.session_id, "sess")

    def test_embed_engine_optional(self):
        bundle = self._bundle("sess", embed_engine=build_embed_engine(self.cfg))
        self.assertIsNotNone(bundle.retriever._embed)


if __name__ == "__main__":
    unittest.main()
