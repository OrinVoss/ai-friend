"""File operation tools: read local files (read-only)."""
import logging
import os
import time
from itertools import islice
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

# FL-002: cache allowed roots for 60s to avoid re-reading config on every call
_ALLOWED_ROOTS_CACHE: list[str] | None = None
_ALLOWED_ROOTS_CACHE_TS: float = 0.0
_ALLOWED_ROOTS_TTL = 60.0


def _is_binary(filepath: str) -> bool:
    """Quick check if file is likely binary."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
        return b"\x00" in chunk
    except Exception as e:
        logger.debug(f"Binary check failed for {filepath}: {e}")
        return False


def _get_allowed_roots() -> list[str]:
    """Load allowed read directories from config. FL-002: cached for 60s."""
    global _ALLOWED_ROOTS_CACHE, _ALLOWED_ROOTS_CACHE_TS
    now = time.time()
    if _ALLOWED_ROOTS_CACHE is not None and (now - _ALLOWED_ROOTS_CACHE_TS) < _ALLOWED_ROOTS_TTL:
        return _ALLOWED_ROOTS_CACHE
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
        _ALLOWED_ROOTS_CACHE = paths
        _ALLOWED_ROOTS_CACHE_TS = now
        return paths
    except Exception as e:
        logger.warning(f"Config load failed for allowed roots, using project fallback: {e}")
        fallback = [os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))]
        _ALLOWED_ROOTS_CACHE = fallback
        _ALLOWED_ROOTS_CACHE_TS = now
        return fallback


def _path_in_allowed(filepath: str) -> str | None:
    """Resolve and check path is in an allowed directory. Returns real path or None."""
    resolved = os.path.realpath(filepath)  # #209: resolve symlinks/junctions
    for root in _get_allowed_roots():
        try:
            root_real = os.path.realpath(root)
            if resolved.startswith(root_real + os.sep) or resolved == root_real:  # #209: boundary check
                return resolved
        except Exception as e:
            logger.debug(f"Path check failed for root {root}: {e}")
            continue
    return None


class ReadFileTool(Tool):
    """Read content from a local text file with line numbers."""

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "读取本地文件内容（只读）。自动添加行号，支持分段读取和批量读取。\n"
            "先用 glob 找文件，再用 grep 搜内容，最后用本工具读具体文件。\n"
            "可读取的目录：项目根目录、以及 config.json 中 allowed_read_paths 配置的目录"
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
                # FL-005: filter hidden files (dot-prefixed) from listing
                items = sorted(i for i in os.listdir(resolved) if not i.startswith("."))
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
            # FL-007: stream only the needed slice instead of readlines() loading
            # the whole file into memory — large files no longer OOM.
            with open(resolved, encoding="utf-8", errors="replace") as f:
                if offset > 0:
                    # consume and discard the offset prefix without materializing it
                    next(islice(f, offset, offset), None)
                selected = list(islice(f, limit))
        except PermissionError:
            return ToolResult.fail(f"无权限: {filepath}")
        except Exception as e:
            return ToolResult.fail(f"读取失败: {e}")

        # total_lines is approximate when streaming; re-stat via size heuristic only.
        # We report the slice range instead of total to avoid a second full read.
        start = max(0, offset)
        end = start + len(selected)
        # If we read exactly `limit` lines there may be more remaining.
        has_more = len(selected) >= limit

        short = os.path.relpath(resolved, os.path.join(os.path.dirname(__file__), ".."))
        header = f"{short}  ({size/1024:.1f}KB, L{start+1}-L{end})"

        out = [header]
        for i, line in enumerate(selected):
            line_num = start + i + 1
            out.append(f"{line_num:>6}|{line.rstrip()}")

        if has_more:
            out.append(f"...(后续 offset={end} 继续)")

        return ToolResult.ok("\n".join(out))

    def execute(self, args: dict[str, Any]) -> ToolResult:
        filepath_raw = args.get("path", "").strip()
        limit = min(int(args.get("limit", 200)), 2000)
        offset = max(0, int(args.get("offset", 0)))

        if not filepath_raw:
            return ToolResult.fail("请提供文件路径")

        logger.info(f"[tool] read_file path={filepath_raw[:80]} limit={limit} offset={offset}")

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
