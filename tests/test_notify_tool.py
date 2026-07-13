"""Tests for the Windows notify tool."""
import subprocess
import unittest
from unittest.mock import patch

from tools.notify_tool import NotifyTool


class TestNotifyTool(unittest.TestCase):
    def setUp(self):
        self.tool = NotifyTool()

    def test_spec_requires_title_and_message(self):
        schema = self.tool.parameters_schema()
        self.assertEqual(schema["required"], ["title", "message"])

    def test_fail_when_title_missing(self):
        result = self.tool.execute({"message": "hello"})
        self.assertFalse(result.success)
        self.assertIn("标题不能为空", result.output)

    def test_fail_when_message_missing(self):
        result = self.tool.execute({"title": "hi"})
        self.assertFalse(result.success)
        self.assertIn("内容不能为空", result.output)

    def test_accept_content_alias(self):
        """LLM 经常传 content 而不是 message，需要兼容。"""
        with patch("tools.notify_tool.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            result = self.tool.execute({
                "title": "标题",
                "content": "正文内容",
            })
        self.assertTrue(result.success)
        self.assertIn("已发送通知", result.output)

    def test_accept_text_msg_body_aliases(self):
        """兼容 text/msg/body 等常见别名。"""
        with patch("tools.notify_tool.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            for key in ("text", "msg", "body"):
                with self.subTest(alias=key):
                    result = self.tool.execute({
                        "title": "标题",
                        key: f"用 {key} 传的正文",
                    })
                    self.assertTrue(result.success, f"{key} 别名应被接受")

    def test_message_takes_precedence_over_content(self):
        with patch("tools.notify_tool.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            self.tool.execute({
                "title": "标题",
                "message": "真实消息",
                "content": "被忽略",
            })
        ps_script = mock_run.call_args[0][0][3]
        self.assertIn("真实消息", ps_script)
        self.assertNotIn("被忽略", ps_script)

    def test_powershell_failure_reported(self):
        with patch("tools.notify_tool.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = "something went wrong".encode()
            result = self.tool.execute({
                "title": "标题",
                "message": "正文",
            })
        self.assertFalse(result.success)
        self.assertIn("something went wrong", result.output)

    def test_powershell_timeout_reported(self):
        with patch("tools.notify_tool.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="powershell", timeout=10)
            result = self.tool.execute({
                "title": "标题",
                "message": "正文",
            })
        self.assertFalse(result.success)
        self.assertIn("通知发送超时", result.output)

    def test_title_escaped_for_powershell(self):
        with patch("tools.notify_tool.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""
            self.tool.execute({
                "title": "it's ok",
                "message": "say 'hello'",
            })
        ps_script = mock_run.call_args[0][0][3]
        self.assertIn("it''s ok", ps_script)
        self.assertIn("say ''hello''", ps_script)


if __name__ == "__main__":
    unittest.main()
