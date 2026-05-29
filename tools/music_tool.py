"""Music player tool: browse and play music from a directory."""
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from tools.traits import Tool, ToolResult

logger = logging.getLogger(__name__)

MUSIC_DIR = r"D:\音乐"
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aac", ".ogg", ".wma", ".m4a"}


def _is_audio(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() in AUDIO_EXTENSIONS


class MusicListTool(Tool):
    """List music files in the music directory."""

    def name(self) -> str:
        return "music_list"

    def description(self) -> str:
        return "浏览音乐目录，查看有哪些歌曲。支持指定子目录或搜索歌曲名。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "子目录路径（相对于音乐目录），留空则列出根目录",
                    "default": "",
                },
                "search": {
                    "type": "string",
                    "description": "搜索关键词，匹配文件名",
                    "default": "",
                },
            },
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        subpath = args.get("path", "").strip()
        search = args.get("search", "").strip().lower()
        logger.info(f"[tool] music_list path={subpath or '.'} search={search or 'none'}")

        target = os.path.join(MUSIC_DIR, subpath) if subpath else MUSIC_DIR
        target = os.path.abspath(target)

        # Security: must be under MUSIC_DIR
        if not target.startswith(os.path.abspath(MUSIC_DIR)):
            return ToolResult.fail("路径超出音乐目录范围")

        if not os.path.exists(target):
            return ToolResult.fail(f"目录不存在: {target}")

        try:
            results = []
            dirs = []
            for root, dnames, fnames in os.walk(target):
                rel = os.path.relpath(root, MUSIC_DIR)
                for d in dnames:
                    dir_path = os.path.join(rel, d) if rel != "." else d
                    dirs.append(dir_path)
                for f in fnames:
                    if _is_audio(f):
                        filepath = os.path.join(root, f)
                        size_mb = os.path.getsize(filepath) / (1024 * 1024)
                        rel_path = os.path.join(rel, f) if rel != "." else f
                        if search and search not in f.lower():
                            continue
                        results.append((rel_path, size_mb))
                break  # Only current dir, don't recurse

            lines = [f"音乐目录 ({target}):"]
            if dirs:
                lines.append(f"\n📁 子目录 ({len(dirs)}):")
                for d in sorted(dirs)[:20]:
                    lines.append(f"  [{d}/]")
            if results:
                lines.append(f"\n🎵 歌曲 ({len(results)}):")
                for path, size in sorted(results)[:50]:
                    lines.append(f"  {path}  ({size:.1f} MB)")
            if not dirs and not results:
                lines.append("  (空)")

            return ToolResult.ok("\n".join(lines))
        except Exception as e:
            return ToolResult.fail(f"读取目录失败: {e}")


class MusicPlayTool(Tool):
    """Play a music file."""

    def name(self) -> str:
        return "music_play"

    def description(self) -> str:
        return "播放音乐文件。支持指定歌曲名或路径，自动在音乐目录中查找。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "song": {
                    "type": "string",
                    "description": "歌曲名称或相对于音乐目录的路径",
                },
            },
            "required": ["song"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        song = args.get("song", "").strip()
        if not song:
            return ToolResult.fail("请提供歌曲名称")

        logger.info(f"[tool] music_play song={song[:60]}")

        # Try exact path first
        exact = os.path.join(MUSIC_DIR, song)
        if os.path.isfile(exact) and _is_audio(exact):
            return self._play(exact, song)

        # Search for matching file
        matches = []
        for root, _, fnames in os.walk(MUSIC_DIR):
            for f in fnames:
                if _is_audio(f) and song.lower() in f.lower():
                    matches.append(os.path.join(root, f))
            if len(matches) > 10:
                break

        if not matches:
            return ToolResult.fail(f"未找到歌曲: {song}")

        if len(matches) > 1:
            rels = [os.path.relpath(m, MUSIC_DIR) for m in matches[:5]]
            return ToolResult.fail(
                f"找到 {len(matches)} 首匹配歌曲，请精确指定:\n" +
                "\n".join(f"  - {r}" for r in rels)
            )

        return self._play(matches[0], os.path.relpath(matches[0], MUSIC_DIR))

    def _play(self, filepath: str, display_name: str) -> ToolResult:
        try:
            os.startfile(filepath)
            return ToolResult.ok(f"正在播放: {display_name}")
        except Exception as e:
            return ToolResult.fail(f"播放失败: {e}")