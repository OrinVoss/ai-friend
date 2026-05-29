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
                    "description": "文件路径，相对于项目目录或绝对路径。支持逗号分隔的多个路径",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "每个文件最多读取字符数（默认 10000）",
                    "default": 10000,
                },
                "offset": {
                    "type": "integer",
                    "description": "从文件的第几个字符开始读（默认 0）",
                    "default": 0,
                },
            },
            "required": ["path"],
        }

    def _read_one(self, filepath: str, max_chars: int, offset: int) -> ToolResult:
        resolved = os.path.abspath(filepath)
        allowed_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        rel = os.path.relpath(resolved, allowed_root)
        if rel.startswith(".."):
            return ToolResult.fail(f"路径超出项目目录范围: {filepath}")
        if not os.path.exists(resolved):
            return ToolResult.fail(f"文件不存在: {filepath}")
        if not os.path.isfile(resolved):
            return ToolResult.fail(f"路径不是文件: {filepath}")
        size = os.path.getsize(resolved)
        if size > MAX_FILE_SIZE:
            return ToolResult.fail(f"文件太大 ({size/1024:.0f}KB)，超过 100KB 限制")
        _, ext = os.path.splitext(resolved)
        if ext and ext.lower() not in TEXT_EXTENSIONS:
            return ToolResult.fail(f"不支持的文件类型: {ext}")
        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                if offset > 0:
                    f.seek(offset)
                content = f.read(max_chars)
            if len(content) >= max_chars:
                content += "\n...(已截断)"
            short_path = os.path.relpath(resolved) if os.path.isabs(resolved) else resolved
            return ToolResult.ok(f"文件 {short_path} ({size / 1024:.1f}KB, offset={offset}):\n```\n{content}\n```")
        except PermissionError:
            return ToolResult.fail(f"无权限读取文件: {filepath}")
        except Exception as e:
            return ToolResult.fail(f"读取文件失败: {e}")

    def execute(self, args: dict[str, Any]) -> ToolResult:
        filepath_raw = args.get("path", "").strip()
        max_chars = min(int(args.get("max_chars", 10000)), 50000)
        offset = max(0, int(args.get("offset", 0)))

        if not filepath_raw:
            return ToolResult.fail("请提供文件路径")

        # Support multiple files separated by comma
        paths = [p.strip() for p in filepath_raw.split(",") if p.strip()]
        if len(paths) > 5:
            return ToolResult.fail("最多同时读取 5 个文件")

        if len(paths) == 1:
            return self._read_one(paths[0], max_chars, offset)

        results = []
        for p in paths:
            r = self._read_one(p, max_chars, offset)
            results.append(r.output if r.success else f"[失败] {p}: {r.output}")
        return ToolResult.ok("\n\n---\n\n".join(results))
