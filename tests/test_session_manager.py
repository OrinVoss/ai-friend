"""Tests for web/session.py — SessionManager role/session binding."""
import asyncio
import threading
import unittest
from unittest.mock import MagicMock, patch

from config import Config
import web.session as session_mod
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


class TestScheduleRemove(unittest.TestCase):
    """M-12: WS 断开的延迟销毁与多 tab 归属判断。"""

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

    def test_inactive_ws_disconnect_keeps_session(self):
        """M-12: 多 tab — 非活跃连接（旧 tab）断开不清归属、不销毁 session。"""
        sid, _ = self.manager.get_or_create(role_id="小星")
        ws_tab1, ws_tab2 = MagicMock(name="tab1"), MagicMock(name="tab2")
        self.manager.register_proactive(sid, MagicMock(), ws_tab1)
        self.manager.register_proactive(sid, MagicMock(), ws_tab2)  # tab2 接管

        # tab1 断开：server finally 的归属判断不通过
        self.assertIsNot(self.manager.get_active_ws(sid), ws_tab1)
        # 即使误调 unregister_ws，非活跃连接也不会清除归属
        self.manager.unregister_ws(sid, ws_tab1)
        self.assertIs(self.manager.get_active_ws(sid), ws_tab2)
        self.assertIn(sid, self.manager._sessions)
        self.assertNotIn(sid, self.manager._pending_remove)

        # tab2（活跃连接）断开才允许清除归属
        self.manager.unregister_ws(sid, ws_tab2)
        self.assertIsNone(self.manager.get_active_ws(sid))

    def test_schedule_remove_cancelled_on_reuse(self):
        """M-12: 宽限期内 get_or_create 复用存活 session → 取消延迟销毁。"""
        async def run():
            sid, agent = self.manager.get_or_create(role_id="小星")
            self.manager.schedule_remove(sid, delay=0.05)
            self.assertIn(sid, self.manager._pending_remove)
            await asyncio.sleep(0.01)  # 仍在宽限期内
            _, reused = self.manager.get_or_create(session_id=sid)
            self.assertIs(reused, agent)
            self.assertNotIn(sid, self.manager._pending_remove)  # 已取消
            await asyncio.sleep(0.1)  # 超过原定到期时间
            self.assertIn(sid, self.manager._sessions)  # 未被销毁
        asyncio.run(run())

    def test_register_proactive_cancels_pending_remove(self):
        """M-12: 宽限期内新连接 register_proactive → 取消延迟销毁。"""
        async def run():
            sid, _ = self.manager.get_or_create(role_id="小星")
            self.manager.schedule_remove(sid, delay=0.05)
            self.manager.register_proactive(sid, MagicMock(), MagicMock())
            self.assertNotIn(sid, self.manager._pending_remove)
            await asyncio.sleep(0.1)
            self.assertIn(sid, self.manager._sessions)
        asyncio.run(run())

    def test_schedule_remove_expires(self):
        """M-12: 宽限期结束仍无活跃连接 → 真正 remove。"""
        async def run():
            sid, _ = self.manager.get_or_create(role_id="小星")
            self.manager.schedule_remove(sid, delay=0.05)
            await asyncio.sleep(0.15)
            self.assertNotIn(sid, self.manager._sessions)
            self.assertNotIn(sid, self.manager._pending_remove)
        asyncio.run(run())


class TestOpenIdempotent(unittest.TestCase):
    """L-04: SessionManager.open() 并发幂等。"""

    def test_open_concurrent_idempotent(self):
        cfg = Config()
        cfg.db_path = ":memory:"
        cfg.personality_file = "personality.json"
        cfg.api_endpoint = "http://localhost"
        cfg.api_key = "test"
        cfg.api_model = "test"
        cfg.embedding_endpoint = "http://localhost:8080/v1/embeddings"
        cfg.embedding_dim = 768
        cfg.temperature = 0.7
        cfg.max_tokens = 512
        cfg.thinking = False
        cfg.reasoning_effort = "low"
        cfg.api_timeout = 10
        cfg.short_term_capacity = 10
        cfg.proactive_min_idle = 60
        cfg.consolidation_interval = 5
        cfg.conversation_examples = []

        real_db_cls = session_mod.Database
        created = []

        def counting_db(*args, **kwargs):
            db = real_db_cls(*args, **kwargs)
            created.append(db)
            return db

        manager = SessionManager(cfg)

        async def run():
            with patch.object(session_mod, "Database", side_effect=counting_db):
                await asyncio.gather(*(manager.open() for _ in range(5)))
            self.assertIsNotNone(manager.db)
            self.assertEqual(len(created), 1)  # 只真正初始化一次
            await manager.shutdown()

        asyncio.run(run())


class TestShutdownSingleSave(unittest.TestCase):
    """L-08: shutdown 每 session 只保存一次 personality（由 close 内部保存）。"""

    def test_shutdown_closes_without_double_save(self):
        cfg = Config()
        manager = SessionManager(cfg)
        agent = MagicMock()
        manager._sessions["s1"] = agent
        asyncio.run(manager.shutdown())
        # 不再单独调 save_personality，只 close 一次（close 内保存 personality）
        agent.save_personality.assert_not_called()
        agent.close.assert_called_once()
        self.assertEqual(manager._sessions, {})


class TestSavePersonalityDebounced(unittest.TestCase):
    """#44/#276: personality 防抖落盘与线程安全。"""

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

    def test_debounce_within_window(self):
        """#44: 30s 窗口内重复调用只落盘一次。"""
        _, agent = self.manager.get_or_create(role_id="小星")
        agent._last_save_time = 0.0
        with patch.object(agent.personality, "save") as mock_save:
            agent._save_personality_debounced()
            agent._save_personality_debounced()
            self.assertEqual(mock_save.call_count, 1)

    def test_debounce_threadsafe(self):
        """#276: 多线程并发穿窗 — 加锁后只有一个线程真正落盘。"""
        _, agent = self.manager.get_or_create(role_id="小星")
        agent._last_save_time = 0.0
        with patch.object(agent.personality, "save") as mock_save:
            threads = [threading.Thread(target=agent._save_personality_debounced)
                       for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(mock_save.call_count, 1)


if __name__ == "__main__":
    unittest.main()
