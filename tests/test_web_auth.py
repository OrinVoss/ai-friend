"""Tests for A1 Web token auth (web/server.py, 2026-07-21)."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestTokenAuth(unittest.TestCase):
    def _client(self, token: str):
        import web.server as server
        # 直接改模块级 config 的字段（dataclass 实例可变）
        server.config.web_access_token = token
        return TestClient(server.app)

    def tearDown(self):
        import web.server as server
        server.config.web_access_token = ""

    def test_disabled_by_default_open(self):
        c = self._client("")
        r = c.get("/api/roles")
        self.assertNotEqual(r.status_code, 401)

    def test_enabled_no_credentials_401(self):
        c = self._client("secret")
        r = c.get("/api/roles")
        self.assertEqual(r.status_code, 401)

    def test_enabled_wrong_token_401(self):
        c = self._client("secret")
        r = c.get("/api/roles", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status_code, 401)

    def test_enabled_bearer_ok(self):
        c = self._client("secret")
        r = c.get("/api/roles", headers={"Authorization": "Bearer secret"})
        self.assertNotEqual(r.status_code, 401)

    def test_enabled_query_token_ok(self):
        # EventSource 不能自定义头，中间件接受 ?token=（路径无关）
        c = self._client("secret")
        r = c.get("/api/roles?token=secret")
        self.assertNotEqual(r.status_code, 401)

    def test_static_not_protected(self):
        c = self._client("secret")
        r = c.get("/")
        self.assertNotEqual(r.status_code, 401)


class TestWsTokenAuth(unittest.TestCase):
    def tearDown(self):
        import web.server as server
        server.config.web_access_token = ""

    def test_ws_init_bad_token_closes_4001(self):
        import web.server as server
        server.config.web_access_token = "secret"
        client = TestClient(server.app)
        with self.assertRaises(Exception):
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "init", "token": "wrong"})
                ws.receive_json()  # 应被 close(4001) 断开

    def test_ws_init_no_token_required_when_disabled(self):
        import web.server as server
        server.config.web_access_token = ""
        # mock session_manager：避免真实装配（生产 DB + 全工具栈）拖慢测试
        mock_agent = MagicMock()
        mock_agent.role_id = "auth_test"
        mock_agent.emotion = {}
        mock_agent.personality.config.name = "T"
        mock_sm = MagicMock()
        mock_sm.get_or_create.return_value = ("auth_test", mock_agent)
        client = TestClient(server.app)
        with patch.object(server, "session_manager", mock_sm):
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "init", "session_id": "auth_test"})
                data = ws.receive_json()
                self.assertEqual(data["type"], "init_ok")


if __name__ == "__main__":
    unittest.main()
