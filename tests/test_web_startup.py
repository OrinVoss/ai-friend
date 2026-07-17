"""L-10/L-12: web 链路 config 全进程单例；M-19: setup_logging 可重复初始化。"""
import logging
import unittest

from config import Config


class TestWebConfigSingleton(unittest.TestCase):
    def test_server_config_shared(self):
        import web.server as srv
        self.assertIsInstance(srv.config, Config)
        # L-10/L-12: SessionManager 与模块级 config 是同一对象（只 load 一次）
        self.assertIs(srv.session_manager.config, srv.config)

    def test_web_main_reuses_server_config(self):
        # web_main.main 不再自调 load_config，而是从 web.server 导入同一 config
        import inspect
        import web_main
        src = inspect.getsource(web_main.main)
        self.assertIn("from web.server import config", src)
        self.assertNotIn("= load_config()", src)


class TestSetupLoggingReentrant(unittest.TestCase):
    def test_re_setup_does_not_duplicate_handlers(self):
        # M-19: 启动顺序改为 setup_logging("INFO") → load_config →
        # setup_logging(config.log_level)，依赖重初始化不堆叠 handler
        from core.logging_setup import setup_logging
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        try:
            setup_logging("INFO")
            count_after_first = len(root.handlers)
            setup_logging("DEBUG")
            self.assertEqual(len(root.handlers), count_after_first)
            self.assertEqual(root.level, logging.DEBUG)
            setup_logging("INFO")
            self.assertEqual(len(root.handlers), count_after_first)
        finally:
            root.handlers.clear()
            root.handlers.extend(saved_handlers)
            root.setLevel(saved_level)


if __name__ == "__main__":
    unittest.main()
