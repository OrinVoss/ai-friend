"""File operation tools: read local files."""

import os
import logging
from typing import Any

from tools.traits import Tool, ToolResult

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024  # 100KB
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".rs", ".js", ".ts", ".json", ".xml", ".html",
    ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".log", ".sh", ".bat", ".ps1", ".env", ".gitignore",
    ".java", ".cpp", ".c", ".h", ".hpp", ".go", ".rb", ".php",
    ".vue", ".svelte", ".jsx", ".tsx", ".sql", ".r", ".lua",
}


class ReadFileTool(Tool):
    """Read content from a local text file."""

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "读取本地文件的内容。支持文本文件（代码、文档、配置等），最大 100KB。用于查看项目文件、配置文件、笔记等。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，相对于项目目录或绝对路径",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "最多读取多少字符（默认 10000）",
                    "default": 10000,
                },
            },
            "required": ["path"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        filepath = args.get("path", "").strip()
        max_chars = int(args.get("max_chars", 10000))

        if not filepath:
            return ToolResult.fail("请提供文件路径")

        # Resolve path
        resolved = os.path.abspath(filepath)
        if not os.path.exists(resolved):
            return ToolResult.fail(f"文件不存在: {filepath}")

        if not os.path.isfile(resolved):
            return ToolResult.fail(f"路径不是文件: {filepath}")

        # Check file size
        size = os.path.getsize(resolved)
        if size > MAX_FILE_SIZE:
            return ToolResult.fail(
                f"文件太大 ({size/1024:.0f}KB)，超过 100KB 限制"
            )

        # Check extension (warn but allow if no extension)
        _, ext = os.path.splitext(resolved)
        if ext and ext.lower() not in TEXT_EXTENSIONS:
            return ToolResult.fail(
                f"不支持的文件类型: {ext}。支持: {', '.join(sorted(TEXT_EXTENSIONS))}"
            )

        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)
            if len(content) >= max_chars:
                content += "\n...(已截断，文件超过读取限制)"

            short_path = os.path.relpath(resolved) if os.path.isabs(resolved) else resolved
            return ToolResult.ok(f"文件 {short_path} ({size / 1024:.1f}KB):\n```\n{content}\n```")
        except PermissionError:
            return ToolResult.fail(f"无权限读取文件: {filepath}")
        except Exception as e:
            return ToolResult.fail(f"读取文件失败: {e}")
