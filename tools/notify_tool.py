"""Windows notification tools."""
import logging
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
                    "description": "通知标题，简短醒目",
                },
                "message": {
                    "type": "string",
                    "description": "通知正文内容",
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
        message = args.get("message", "").strip()

        if not title or not message:
            return ToolResult.fail("标题和内容不能为空")

        # #150: escape PowerShell injection — double single-quote in single-quoted strings
        esc_title = title.replace("'", "''")
        esc_msg = message.replace("'", "''")

        import subprocess, threading

        def _show():
            ps = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$textNodes.Item(0).AppendChild($template.CreateTextNode('{esc_title}')) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode('{esc_msg}')) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AI Friend').Show($toast)
'''
            try:
                subprocess.run(
                    ['powershell', '-NoProfile', '-Command', ps],
                    capture_output=True, timeout=10,
                )
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                logger.warning(f"Notification failed: {title}")

        threading.Thread(target=_show, daemon=True).start()
        logger.info(f"Notification sent: {title}")
        return ToolResult.ok(f"已发送通知：{title}")
