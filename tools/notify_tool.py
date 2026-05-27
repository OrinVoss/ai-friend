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
        duration = int(args.get("duration", 5))

        if not title or not message:
            return ToolResult.fail("标题和内容不能为空")

        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                timeout=duration,
                app_name="小星",
            )
            logger.info(f"Notification sent: {title}")
            return ToolResult.ok(f"已发送通知：{title}")
        except ImportError:
            pass

        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x1000)
            logger.info(f"Notification sent (MessageBox): {title}")
            return ToolResult.ok(f"已发送通知：{title}")
        except Exception as e:
            logger.warning(f"Notification failed: {e}")
            return ToolResult.fail(f"通知发送失败: {e}")
