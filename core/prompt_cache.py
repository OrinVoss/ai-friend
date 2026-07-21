"""Hierarchical prompt cache for AI Friend.

Static blocks (identity, examples, inner-drive instructions) are cached without
TTL and invalidated only when the personality file changes.  Slow-changing
blocks (relationship, long-term memory) use a short TTL so they are not rebuilt
for every Agent inside the same request.  Dynamic blocks (time, current
conversation, tool records) are never cached.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Callable

logger = logging.getLogger(__name__)


class PromptCache:
    """Process-level cache for prompt components.

    Keys are ``(session_id, personality_version, component_name)``.
    ``personality_version`` should be derived from the personality file so that
    edits to the character invalidate stale static blocks automatically.
    """

    # L-02: 容量上限 + FIFO 淘汰——人格文件每次保存都会产生新 key
    # （personality_version 含 mtime），旧 key 必须被淘汰而不是无限堆积。
    MAX_ENTRIES = 200

    def __init__(self) -> None:
        self._store: OrderedDict[tuple[str, str, str], tuple[str, float, float | None]] = OrderedDict()
        self._lock = threading.Lock()
        # PC-002: lightweight hit/miss/saved_chars counters for observability
        self.hits: int = 0
        self.misses: int = 0
        self.saved_chars: int = 0
        self._stats_log_counter: int = 0

    @staticmethod
    def personality_version(personality_file: str) -> str:
        """Return a version string for a personality file.

        Uses ``mtime:size:path`` so that editing the character invalidates the
        static prompt blocks without needing to hash the file contents.
        """
        try:
            stat = os.stat(personality_file)
            return f"{stat.st_mtime}:{stat.st_size}:{personality_file}"
        except (OSError, FileNotFoundError):
            return f"missing:{personality_file}"

    def get_or_build(
        self,
        session_id: str,
        personality_version: str,
        component_name: str,
        builder: Callable[[], str],
        ttl: float | None = None,
    ) -> str:
        """Return a cached component or build and cache it.

        Args:
            session_id: Session identifier.
            personality_version: Version token from ``personality_version()``.
            component_name: Logical block name, e.g. ``identity``.
            builder: Callable that produces the block text.
            ttl: Cache TTL in seconds. ``None`` means no expiration.

        Returns:
            The block text.
        """
        key = (session_id, personality_version, component_name)
        now = time.monotonic()

        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                value, created_at, entry_ttl = entry
                if entry_ttl is None or now - created_at < entry_ttl:
                    logger.debug(
                        f"[prompt_cache] hit: {component_name} "
                        f"session={session_id}"
                    )
                    self.hits += 1
                    self.saved_chars += len(value)
                    return value
                logger.debug(
                    f"[prompt_cache] expired: {component_name} "
                    f"session={session_id}"
                )

        value = builder()

        with self._lock:
            self._store[key] = (value, now, ttl)
            self.misses += 1
            while len(self._store) > self.MAX_ENTRIES:
                self._store.popitem(last=False)  # L-02: FIFO 淘汰最旧 key

        logger.debug(
            f"[prompt_cache] build: {component_name} "
            f"session={session_id} ttl={ttl}"
        )
        return value

    def invalidate(
        self,
        session_id: str | None = None,
        personality_version: str | None = None,
        component_name: str | None = None,
    ) -> int:
        """Remove matching entries from the cache.

        ``None`` acts as a wildcard.  Returns the number of removed entries.
        """
        removed = 0
        with self._lock:
            keys = list(self._store.keys())
            for key in keys:
                sid, pver, comp = key
                if session_id is not None and sid != session_id:
                    continue
                if personality_version is not None and pver != personality_version:
                    continue
                if component_name is not None and comp != component_name:
                    continue
                del self._store[key]
                removed += 1
        logger.debug(f"[prompt_cache] invalidated {removed} entries")
        return removed

    def clear(self) -> None:
        """Drop all cached entries."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
        logger.debug(f"[prompt_cache] cleared {count} entries")

    def stats(self) -> dict:
        """Return cache counters: hits, misses, hit_rate, saved_chars."""
        with self._lock:
            total = self.hits + self.misses
            hit_rate = self.hits / total if total > 0 else 0.0
            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate,
                "saved_chars": self.saved_chars,
            }

    def reset_stats(self) -> None:
        """Reset cache counters."""
        with self._lock:
            self.hits = 0
            self.misses = 0
            self.saved_chars = 0
            self._stats_log_counter = 0

    def maybe_log_stats(self, logger, tag: str = "") -> None:
        """Log cumulative cache stats every 50 total calls, otherwise debug.

        Args:
            logger: A logging.Logger-like object.
            tag: Optional tag appended to the log message (e.g. session id).
        """
        with self._lock:
            total = self.hits + self.misses
            self._stats_log_counter += 1
            hit_rate = self.hits / total if total > 0 else 0.0
            msg = (
                f"[prompt_cache] stats: hit_rate={hit_rate:.1%} "
                f"saved={self.saved_chars} chars "
                f"hits={self.hits} misses={self.misses}"
            )
            if tag:
                msg = f"{msg} tag={tag}"
            if total > 0 and total % 50 == 0:
                logger.info(msg)
            else:
                logger.debug(msg)
