"""Music player tool: browse and play music from a directory."""
import logging
import os
from typing import Any

from tools.traits import (
    Tool, ToolResult,
    ERROR_TYPE_PARAM_ERROR, ERROR_TYPE_NOT_FOUND,
    ERROR_TYPE_INTERNAL,
)

logger = logging.getLogger(__name__)

MUSIC_DIR = r"D:\音乐"
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aac", ".ogg", ".wma", ".m4a"}
# MU-002: 音频扫描上限（#271: 只对音频文件计数，非音频不再消耗额度）
MUSIC_SCAN_LIMIT = 10_000


def _is_audio(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() in AUDIO_EXTENSIONS


class MusicListTool(Tool):
    """List music files in the music directory."""

    timeout_seconds = 10.0

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
        # #271: realpath + os.sep 边界检查（仿 file_tools._path_in_allowed），
        # 防止 "D:\音乐2" 这类同前缀目录绕过白名单
        target = os.path.realpath(target)

        # Security: must be under MUSIC_DIR
        music_root = os.path.realpath(MUSIC_DIR)
        if target != music_root and not target.startswith(music_root + os.sep):
            return ToolResult.fail(
                "路径超出音乐目录范围",
                error_type=ERROR_TYPE_PARAM_ERROR,
                retryable=False,
            )

        if not os.path.exists(target):
            return ToolResult.fail(
                f"目录不存在: {target}",
                error_type=ERROR_TYPE_NOT_FOUND,
                retryable=False,
            )

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
            return ToolResult.fail(
                f"读取目录失败: {e}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )


class MusicPlayTool(Tool):
    """Play a music file."""

    timeout_seconds = 10.0

    def name(self) -> str:
        return "music_play"

    def description(self) -> str:
        return "播放音乐文件。支持指定歌曲名或路径；也可以传 song='random' 随机播放一首。"

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "song": {
                    "type": "string",
                    "description": "歌曲名称、相对于音乐目录的路径，或 'random' 随机播放一首",
                },
            },
            "required": ["song"],
        }

    def execute(self, args: dict[str, Any]) -> ToolResult:
        # dispatcher no longer globally maps "title" to "song", so handle
        # title/song_name/track aliases locally.
        song = (
            args.get("song", "").strip()
            or args.get("title", "").strip()
            or args.get("song_name", "").strip()
            or args.get("track", "").strip()
        )
        if not song:
            return ToolResult.fail(
                "请提供歌曲名称",
                error_type=ERROR_TYPE_PARAM_ERROR,
                retryable=False,
            )

        logger.info(f"[tool] music_play song={song[:60]}")

        # MU-005: support random playback
        if song.lower() in ("random", "随机", "随便"):
            all_songs = self._collect_songs(MUSIC_DIR)
            if not all_songs:
                return ToolResult.fail(
                    "音乐目录中没有可播放的歌曲",
                    error_type=ERROR_TYPE_NOT_FOUND,
                    retryable=False,
                )
            import random
            chosen = random.choice(all_songs)
            return self._play(chosen, os.path.relpath(chosen, MUSIC_DIR))

        # Try exact path first
        exact = os.path.join(MUSIC_DIR, song)
        if os.path.isfile(exact) and _is_audio(exact):
            return self._play(exact, song)

        # Search for matching file
        matches = self._find_matches(song)
        if not matches:
            return ToolResult.fail(
                f"未找到歌曲: {song}",
                error_type=ERROR_TYPE_NOT_FOUND,
                retryable=False,
            )

        if len(matches) > 1:
            rels = [os.path.relpath(m, MUSIC_DIR) for m in matches[:5]]
            return ToolResult.fail(
                f"找到 {len(matches)} 首匹配歌曲，请精确指定:\n" +
                "\n".join(f"  - {r}" for r in rels),
                error_type=ERROR_TYPE_PARAM_ERROR,
                retryable=False,
            )

        return self._play(matches[0], os.path.relpath(matches[0], MUSIC_DIR))

    def _collect_songs(self, directory: str) -> list[str]:
        """Collect all audio files under directory with a scan limit."""
        songs = []
        files_scanned = 0
        for root, _, fnames in os.walk(directory):
            for f in fnames:
                if _is_audio(f):
                    files_scanned += 1  # #271: 只对音频计数
                    if files_scanned > MUSIC_SCAN_LIMIT:
                        logger.warning(f"[music] file scan limit ({MUSIC_SCAN_LIMIT}) reached")
                        return songs
                    songs.append(os.path.join(root, f))
        return songs

    def _find_matches(self, song: str) -> list[str]:
        """Find audio files whose names contain the search term."""
        matches = []
        files_scanned = 0
        for root, _, fnames in os.walk(MUSIC_DIR):
            for f in fnames:
                if _is_audio(f):
                    files_scanned += 1  # #271: 只对音频计数（MU-002: guard against unbounded walk）
                    if files_scanned > MUSIC_SCAN_LIMIT:
                        logger.warning(f"[music] file scan limit ({MUSIC_SCAN_LIMIT}) reached")
                        return matches
                    if song.lower() in f.lower():
                        matches.append(os.path.join(root, f))
        return matches

    def _play(self, filepath: str, display_name: str) -> ToolResult:
        # MU-004: resolve real path and verify extension before os.startfile
        # to prevent execution of arbitrary non-audio files.
        try:
            real = os.path.realpath(filepath)
        except Exception as e:
            return ToolResult.fail(
                f"路径解析失败: {e}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )
        if not _is_audio(real):
            return ToolResult.fail(
                f"不支持的文件类型: {display_name}",
                error_type=ERROR_TYPE_PARAM_ERROR,
                retryable=False,
            )
        try:
            os.startfile(real)
            return ToolResult.ok(f"正在播放: {display_name}")
        except Exception as e:
            return ToolResult.fail(
                f"播放失败: {e}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )
