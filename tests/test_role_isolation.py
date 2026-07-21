"""多角色数据隔离验证（Layer 6 验收）。"""
import asyncio
import os
import tempfile
import unittest

from config import Config
from core.personality import Personality
from core.personality_manager import PersonalityManager
from core.session_factory import assemble_session, build_provider
from core.sleep_manager import SleepManager
from models.personality import PersonalityConfig, Trait
from storage.database import Database


class TestRoleIsolation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = Config()
        self.cfg.db_path = os.path.join(self._tmp.name, "t.db")
        self.cfg.api_key = "test"
        self.cfg.personality_file = os.path.join(self._tmp.name, "personalities", "default.json")

        self.personalities_dir = os.path.join(self._tmp.name, "personalities")
        os.makedirs(self.personalities_dir, exist_ok=True)
        pm = PersonalityManager(self.personalities_dir)
        default = Personality(PersonalityConfig(name="Default", traits=[Trait("curiosity", 0.5)]))
        default.save(pm.personality_path("default"))
        for role in ("角色A", "角色B"):
            pm.create_role(role)

        self.db = Database(self.cfg.db_path, backup_enabled=False)
        asyncio.run(self.db.open())

    def tearDown(self):
        asyncio.run(self.db.close())
        self._tmp.cleanup()

    def _repo(self, role):
        from storage.repository import Repository
        r = Repository(self.db)
        r.session_id = role
        return r

    def _bundle(self, role):
        pm = PersonalityManager(self.personalities_dir)
        provider = build_provider(self.cfg)
        return assemble_session(
            self.cfg, self.db, session_id=role, role_id=role,
            personality_manager=pm, provider=provider,
        )

    def test_facts_isolated_by_role(self):
        a, b = self._repo("角色A"), self._repo("角色B")
        asyncio.run(a.upsert_fact_v2("preference", "最爱食物", "披萨"))
        asyncio.run(b.upsert_fact_v2("preference", "最爱食物", "寿司"))
        fa = asyncio.run(a.get_active_facts_v2())
        fb = asyncio.run(b.get_active_facts_v2())
        self.assertEqual(len(fa), 1)
        self.assertEqual(len(fb), 1)
        self.assertEqual(fa[0].fact_value, "披萨")
        self.assertEqual(fb[0].fact_value, "寿司")
        # A 的检索看不到 B 的事实
        self.assertEqual(len(asyncio.run(a.search_facts_v2("寿司"))), 0)
        self.assertEqual(len(asyncio.run(b.search_facts_v2("披萨"))), 0)

    def test_relationship_isolated_by_role(self):
        a, b = self._repo("角色A"), self._repo("角色B")
        asyncio.run(a.ensure_relationship_defaults())
        asyncio.run(b.ensure_relationship_defaults())
        asyncio.run(a.upsert_relationship("trust", 0.9))
        asyncio.run(b.upsert_relationship("trust", 0.2))
        ra = asyncio.run(a.get_all_relationships())
        rb = asyncio.run(b.get_all_relationships())
        self.assertEqual(ra["trust"], 0.9)
        self.assertEqual(rb["trust"], 0.2)

    def test_turns_isolated_by_role(self):
        a, b = self._repo("角色A"), self._repo("角色B")
        asyncio.run(a.insert_turn(1, "user", "A 的消息"))
        asyncio.run(b.insert_turn(1, "user", "B 的消息"))
        ta = asyncio.run(a.get_recent_turns(limit=10))
        tb = asyncio.run(b.get_recent_turns(limit=10))
        self.assertEqual(len(ta), 1)
        self.assertEqual(len(tb), 1)
        self.assertIn("A 的消息", ta[0]["content"])
        self.assertIn("B 的消息", tb[0]["content"])

    def test_insights_isolated_by_role(self):
        a, b = self._repo("角色A"), self._repo("角色B")
        asyncio.run(a.insert_insight("A 的洞察", insight_type="pattern", confidence=0.8))
        asyncio.run(b.insert_insight("B 的洞察", insight_type="pattern", confidence=0.6))
        ia = asyncio.run(a.get_active_insights(limit=10))
        ib = asyncio.run(b.get_active_insights(limit=10))
        self.assertEqual(len(ia), 1)
        self.assertEqual(len(ib), 1)
        self.assertIn("A 的洞察", ia[0].hypothesis)
        self.assertIn("B 的洞察", ib[0].hypothesis)

    def test_session_factory_uses_role_id_for_namespace(self):
        """assemble_session 内部所有 session 命名空间必须落在 role_id 上。"""
        a = self._bundle("角色A")
        b = self._bundle("角色B")
        self.assertEqual(a.repo.session_id, "角色A")
        self.assertEqual(b.repo.session_id, "角色B")
        self.assertNotEqual(a.agent._sleep._sleep_state_file, b.agent._sleep._sleep_state_file)
        self.assertIn("角色A", a.agent._sleep._sleep_state_file)
        self.assertIn("角色B", b.agent._sleep._sleep_state_file)

    def test_sleep_state_isolated_by_role(self):
        """两个 SleepManager 使用不同 state_file 时互不影响。"""
        tmp = self._tmp.name
        p = Personality(PersonalityConfig())
        a = SleepManager(os.path.join(tmp, ".sleep_state.角色A"), p, None, None, session_id="角色A")
        b = SleepManager(os.path.join(tmp, ".sleep_state.角色B"), p, None, None, session_id="角色B")
        self.assertFalse(a.is_sleeping)
        self.assertFalse(b.is_sleeping)
        with a._lock:
            a._sleeping = True
            a._save_sleep_state()
        self.assertTrue(a.is_sleeping)
        self.assertFalse(b.is_sleeping)
        # 重新加载确认持久化隔离
        a2 = SleepManager(os.path.join(tmp, ".sleep_state.角色A"), p, None, None, session_id="角色A")
        self.assertTrue(a2.is_sleeping)


if __name__ == "__main__":
    unittest.main()
