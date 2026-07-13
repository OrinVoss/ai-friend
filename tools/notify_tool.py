"""Windows notification tools."""
import logging
import subprocess
from typing import Any

from tools.traits import Tool, ToolResult

logger = logging.getLogger(__name__)


class NotifyTool(Tool):
    """Send Windows desktop toast notifications."""

    def name(self) -> str:
        return "notify"

    def description(self) -> str:
        return "发送 Windows 桌面通知弹窗。当你需要提醒用户某事、或用户要求你通知ta时使用。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "通知标题，简短醒目（必填）",
                },
                "message": {
                    "type": "string",
                    "description": "通知正文内容（必填）。注意：请用 message 字段传正文，不要写成 content/text/msg",
                },
                "duration": {
                    "type": "integer",
                    "description": "显示时长（秒），默认5秒",
                    "default": 5,
                },
            },
            "required": ["title", "message"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        title = args.get("title", "").strip()
        # LLM 经常把正文写成 content/text/msg 而不是 message，这里做兼容
        message = (
            args.get("message", "").strip()
            or args.get("content", "").strip()
            or args.get("text", "").strip()
            or args.get("msg", "").strip()
            or args.get("body", "").strip()
        )
        logger.debug(f"[notify] args={args} resolved title={title!r} message={message!r}")

        if not title:
            return ToolResult.fail(f"标题不能为空，收到的参数：{args}")
        if not message:
            return ToolResult.fail(f"内容不能为空，收到的参数：{args}")

        # #150: escape PowerShell injection
        esc_title = title.replace("'", "''")
        esc_msg = message.replace("'", "''")

        ps = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$textNodes.Item(0).AppendChild($template.CreateTextNode('{esc_title}')) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode('{esc_msg}')) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AI Friend').Show($toast)
'''
        # #272: synchronous call with proper error reporting (removed silent thread)
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace')[:200]
                logger.warning(f"Notification stderr: {stderr}")
                return ToolResult.fail(f"通知发送失败: {stderr}")
            logger.info(f"Notification sent: {title}")
            return ToolResult.ok(f"已发送通知：{title}")
        except subprocess.TimeoutExpired:
            logger.warning(f"Notification timed out: {title}")
            return ToolResult.fail("通知发送超时")
        except Exception as e:
            logger.warning(f"Notification failed: {title} - {e}")
            return ToolResult.fail(f"通知发送失败: {e}")
