"""File operation tools: read local files (read-only)."""
import logging
import os
from typing import Any

from tools.traits import Tool, ToolResult

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 500 * 1024  # 500KB
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".rs", ".js", ".ts", ".json", ".xml", ".html",
    ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".log", ".sh", ".bat", ".ps1", ".env", ".gitignore",
    ".java", ".cpp", ".c", ".h", ".hpp", ".go", ".rb", ".php",
    ".vue", ".svelte", ".jsx", ".tsx", ".sql", ".r", ".lua",
}


def _is_binary(filepath: str) -> bool:
    """Quick check if file is likely binary."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
        return b"\x00" in chunk
    except Exception:
        return False


def _get_allowed_roots() -> list[str]:
    """Load allowed read directories from config."""
    try:
        from config import load_config
        cfg = load_config()
        paths = []
        project = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for p in getattr(cfg, 'allowed_read_paths', []):
            if p == ".":
                paths.append(project)
            else:
                paths.append(os.path.abspath(os.path.expanduser(p)))
        if project not in paths:
            paths.append(project)
        return paths
    except Exception:
        return [os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))]


def _path_in_allowed(filepath: str) -> str | None:
    """Resolve and check path is in an allowed directory. Returns absolute path or None."""
    resolved = os.path.abspath(filepath)
    for root in _get_allowed_roots():
        try:
            if resolved.startswith(os.path.abspath(root)):
                return resolved
        except Exception:
            pass
    return None


class ReadFileTool(Tool):
    """Read content from a local text file with line numbers."""

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "读取本地文件内容（只读）。自动添加行号，支持分段读取和批量读取。\n"
            "先用 glob 找文件，再用 grep 搜内容，最后用本工具读具体文件。\n"
            "可读取的目录：项目根目录、D:\\音乐、D:\\桌面、Documents、Downloads"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径（绝对路径）。支持逗号分隔多个路径，最多 5 个",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取多少行（默认 200，最大 2000）",
                    "default": 200,
                },
                "offset": {
                    "type": "integer",
                    "description": "从第几行开始读（0=第一行）",
                    "default": 0,
                },
            },
            "required": ["path"],
        }

    def _read_one(self, filepath: str, limit: int, offset: int) -> ToolResult:
        resolved = _path_in_allowed(filepath)
        if resolved is None:
            return ToolResult.fail(f"路径超出项目范围: {filepath}")

        if not os.path.exists(resolved):
            return ToolResult.fail(f"文件不存在: {filepath}")

        # If it's a directory, list contents
        if os.path.isdir(resolved):
            try:
                items = sorted(os.listdir(resolved))
            except PermissionError:
                return ToolResult.fail(f"无权限访问目录: {filepath}")
            if not items:
                return ToolResult.ok(f"目录 {filepath}: (空)")
            files = []
            dirs = []
            for item in items:
                full = os.path.join(resolved, item)
                try:
                    if os.path.isdir(full):
                        dirs.append(item + "/")
                    else:
                        sz = os.path.getsize(full)
                        files.append((item, sz))
                except OSError:
                    files.append((item, 0))
            lines = [f"目录 {filepath} ({len(items)} 项):"]
            for d in sorted(dirs)[:30]:
                lines.append(f"  📁 {d}")
            for fname, sz in sorted(files)[:50]:
                lines.append(f"  📄 {fname}  ({sz/1024:.1f} KB)")
            return ToolResult.ok("\n".join(lines))

        if not os.path.isfile(resolved):
            return ToolResult.fail(f"不是文件也不是目录: {filepath}")

        size = os.path.getsize(resolved)
        if size > MAX_FILE_SIZE:
            return ToolResult.fail(f"文件太大 ({size/1024:.0f}KB > {MAX_FILE_SIZE/1024:.0f}KB)")

        if _is_binary(resolved):
            return ToolResult.fail(f"二进制文件，无法读取文本内容")

        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except PermissionError:
            return ToolResult.fail(f"无权限: {filepath}")
        except Exception as e:
            return ToolResult.fail(f"读取失败: {e}")

        total_lines = len(all_lines)
        start = max(0, offset)
        end = min(total_lines, start + limit)
        selected = all_lines[start:end]

        short = os.path.relpath(resolved, os.path.join(os.path.dirname(__file__), ".."))
        header = f"{short}  ({total_lines}行, {size/1024:.1f}KB, L{start+1}-L{end})"

        out = [header]
        for i, line in enumerate(selected):
            line_num = start + i + 1
            out.append(f"{line_num:>6}|{line.rstrip()}")

        if end < total_lines:
            out.append(f"...(剩余 {total_lines - end} 行, offset={end} 继续)")

        return ToolResult.ok("\n".join(out))

    def execute(self, args: dict[str, Any]) -> ToolResult:
        filepath_raw = args.get("path", "").strip()
        limit = min(int(args.get("limit", 200)), 2000)
        offset = max(0, int(args.get("offset", 0)))

        if not filepath_raw:
            return ToolResult.fail("请提供文件路径")

        paths = [p.strip() for p in filepath_raw.split(",") if p.strip()]
        if len(paths) > 5:
            return ToolResult.fail("最多同时读取 5 个文件")

        if len(paths) == 1:
            return self._read_one(paths[0], limit, offset)

        results = []
        for p in paths:
            r = self._read_one(p, limit, offset)
            results.append(r.output if r.success else f"[失败] {p}: {r.output}")
        return ToolResult.ok("\n\n---\n\n".join(results))
