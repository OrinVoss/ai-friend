"""Hardcore file search tools: glob pattern matching + grep content search."""
import fnmatch
import logging
import os
import re
import signal
import time
from typing import Any

from tools.file_tools import _get_allowed_roots, _is_binary
from tools.traits import Tool, ToolResult

logger = logging.getLogger(__name__)

# #172: simple TTL cache for search results (glob + grep)
_SEARCH_CACHE: dict[str, tuple[float, str]] = {}
_SEARCH_CACHE_TTL = 60  # seconds
_SEARCH_CACHE_MAX = 20


def _cache_get(key: str) -> str | None:
    """Get cached result if fresh. Returns None if missing or expired."""
    entry = _SEARCH_CACHE.get(key)
    if entry is None:
        return None
    ts, val = entry
    if time.time() - ts > _SEARCH_CACHE_TTL:
        del _SEARCH_CACHE[key]
        return None
    return val


def _cache_set(key: str, val: str) -> None:
    """Store result in cache, evicting oldest if at capacity."""
    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
        oldest = min(_SEARCH_CACHE.items(), key=lambda kv: kv[1][0])
        _SEARCH_CACHE.pop(oldest[0], None)
        logger.debug(f"[tool] search cache evicted oldest key={oldest[0]}")
    _SEARCH_CACHE[key] = (time.time(), val)

# #150: regex timeout to prevent ReDoS
GREP_TIMEOUT = 5  # seconds per file match

# SR-009: named constants instead of magic numbers
GLOB_MAX_RESULTS = 200
GREP_MAX_MATCHES_PER_FILE = 20
GREP_RESULTS_LIMIT = 50
WALK_FILE_LIMIT = 10_000
MAX_RESULTS_DISPLAY = 50
MAX_HEADER_LINES = 200
SORTED_DIRS_MAX = 30
SORTED_FILES_MAX = 50


def _resolve_search_path(search_path: str) -> str | None:
    """Resolve a search path, return realpath if within any allowed root. (#209)"""
    resolved = os.path.realpath(search_path)
    for root in _get_allowed_roots():
        try:
            root_real = os.path.realpath(root)
            if resolved.startswith(root_real + os.sep) or resolved == root_real:
                return resolved
        except Exception:
            pass
    return None


# SR-007: check directory name exactly against skip list instead of
# substring-match on the whole path, which could match mid-segment.
SKIP_DIR_COMPONENTS = {"__pycache__", ".git", "node_modules", ".venv", "data"}


def _should_skip_dir(dirpath: str) -> bool:
    """Return True if any path component matches a skip directory (SR-007)."""
    parts = dirpath.replace(os.sep, "/").split("/")
    return any(p in SKIP_DIR_COMPONENTS for p in parts)


class GlobTool(Tool):
    """Find files matching glob patterns."""

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return (
            "用 glob 模式搜索文件。支持 ** 递归匹配。例如 '**/*.py' 找所有 Python 文件。\n"
            "搜索范围：项目根目录、D:\\音乐、D:\\桌面、Documents、Downloads"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob 模式，如 '**/*.py'、'src/**/*.rs'、'*.json'",
                },
                "path": {
                    "type": "string",
                    "description": "搜索起始目录，默认项目根目录",
                    "default": ".",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        pattern = args.get("pattern", "").strip()
        search_root = args.get("path", ".").strip()

        if not pattern:
            return ToolResult.fail("请提供 glob 模式")

        logger.info(f"[tool] glob pattern={pattern} root={search_root}")
        root = _resolve_search_path(search_root)
        if root is None:
            return ToolResult.fail(f"路径不在可访问范围内: {search_root}")

        # #172: check cache
        cache_key = f"glob:{pattern}:{root}"
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug(f"[tool] glob cache hit: {cache_key}")
            return ToolResult.ok(cached)

        results = []
        file_count = 0  # SR-003: guard against unbounded os.walk
        for dirpath, _, fnames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            for fname in fnames:
                file_count += 1
                if file_count > WALK_FILE_LIMIT:
                    break
                rel_path = os.path.join(rel_dir, fname) if rel_dir != "." else fname
                # SR-004: single check matching both full path and bare filename
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(fname, pattern):
                    full_path = os.path.join(dirpath, fname)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0
                    results.append((rel_path, size))
            if file_count > WALK_FILE_LIMIT:
                logger.warning(f"[glob] file count limit ({WALK_FILE_LIMIT}) reached, truncating")
                break

        if not results:
            return ToolResult.ok(f"未找到匹配 '{pattern}' 的文件")

        # Sort by name, limit to 200 (GLOB_MAX_RESULTS)
        results.sort()
        header_items = min(len(results), GLOB_MAX_RESULTS)
        lines = [f"匹配 '{pattern}' 的文件 ({len(results)} 个):"]
        for path, size in results[:header_items]:
            lines.append(f"  {path}  ({size:,} B)")
        if len(results) > GLOB_MAX_RESULTS:
            lines.append(f"  ... 还有 {len(results) - GLOB_MAX_RESULTS} 个文件未显示")

        output = "\n".join(lines)
        _cache_set(cache_key, output)  # #172
        return ToolResult.ok(output)


class GrepTool(Tool):
    """Search file contents using regex patterns."""

    MAX_SIZE = 500 * 1024  # 500KB per file
    MAX_RESULTS = 50

    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return (
            "用正则表达式搜索文件内容。支持 glob 过滤文件、上下文行数。\n"
            "搜索范围：项目根目录、D:\\音乐、D:\\桌面、Documents、Downloads"
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "正则表达式搜索模式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索目录或文件，默认项目根目录",
                    "default": ".",
                },
                "glob": {
                    "type": "string",
                    "description": "文件过滤 glob，如 '*.py'、'**/*.json'",
                },
                "context": {
                    "type": "integer",
                    "description": "显示匹配行前后各几行上下文，默认 0",
                    "default": 0,
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "是否忽略大小写，默认 false",
                    "default": False,
                },
            },
            "required": ["pattern"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        pattern = args.get("pattern", "").strip()
        search_path = args.get("path", ".").strip()
        file_glob = args.get("glob", "").strip() or "*"
        context_lines = max(0, min(5, int(args.get("context", 0))))
        ignore_case = bool(args.get("ignore_case", False))

        if not pattern:
            return ToolResult.fail("请提供搜索模式")

        logger.info(f"[tool] grep pattern={pattern[:60]} path={search_path} glob={file_glob}")
        target = _resolve_search_path(search_path)
        if target is None:
            return ToolResult.fail(f"路径不在可访问范围内: {search_path}")

        # #172: check cache
        cache_key = f"grep:{pattern}:{target}:{file_glob}:{ignore_case}"
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug(f"[tool] grep cache hit: {cache_key}")
            return ToolResult.ok(cached)

        try:
            # #150: validate regex doesn't have catastrophic backtracking patterns
            if len(pattern) > 500:  # unreasonably long regex
                return ToolResult.fail("正则表达式过长")
            flags = re.IGNORECASE if ignore_case else 0
            regex = re.compile(pattern, flags)
            # Quick ReDoS check: reject nested quantifiers like (a+)+
            if re.search(r'\(\s*[^)]+[\*\+]\s*\)[\*\+]', pattern):
                return ToolResult.fail("正则表达式包含潜在的 ReDoS 模式，请简化")
        except re.error as e:
            return ToolResult.fail(f"正则表达式错误: {e}")

        # Collect files
        files = []
        if os.path.isfile(target):
            files = [target]
        else:
            file_count = 0  # SR-003: limit total walked files
            for dirpath, _, fnames in os.walk(target):
                # SR-007: precise path component check instead of substring
                if _should_skip_dir(dirpath):
                    continue
                for fname in fnames:
                    file_count += 1
                    if file_count > WALK_FILE_LIMIT:
                        break
                    full = os.path.join(dirpath, fname)
                    rel = os.path.relpath(full, target)
                    if fnmatch.fnmatch(fname, file_glob) or fnmatch.fnmatch(rel, file_glob):
                        try:
                            if os.path.getsize(full) <= self.MAX_SIZE:
                                files.append(full)
                        except OSError:
                            pass
                if file_count > WALK_FILE_LIMIT:
                    logger.warning(f"[grep] file count limit ({WALK_FILE_LIMIT}) reached")
                    break

        if not files:
            return ToolResult.ok(f"未找到匹配文件: {search_path} (glob: {file_glob})")

        results = []
        total_matches = 0
        for filepath in files:
            # SR-008: skip binary files *before* opening with errors="ignore",
            # which mangles binary data into garbage unicode silently.
            if _is_binary(filepath):
                continue
            try:
                with open(filepath, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                continue

            file_matches = []
            for i, line in enumerate(lines):
                if regex.search(line):
                    file_matches.append(i)
                    total_matches += 1

            if file_matches:
                rel = os.path.relpath(filepath, target)
                results.append(f"\n--- {rel} ({len(file_matches)} matches) ---")
                shown = set()
                for line_num in file_matches[:GREP_MAX_MATCHES_PER_FILE]:
                    start = max(0, line_num - context_lines)
                    end = min(len(lines), line_num + context_lines + 1)
                    for ctx_line in range(start, end):
                        if ctx_line not in shown:
                            prefix = ">" if ctx_line == line_num else " "
                            results.append(f"  {prefix} {ctx_line+1}: {lines[ctx_line].rstrip()}")
                            shown.add(ctx_line)
                    if len(results) > self.MAX_RESULTS * 3:
                        break

            if len(results) > self.MAX_RESULTS * 3:
                results.append(f"\n...(结果过多，已截断)")
                break

        if not results:
            return ToolResult.ok(f"未找到匹配 '{pattern}' 的内容")

        header = f"搜索 '{pattern}' ({total_matches} 处匹配, {len(files)} 个文件):"
        output = header + "\n".join(results[:self.MAX_RESULTS * 4])
        _cache_set(cache_key, output)  # #172
        return ToolResult.ok(output)
