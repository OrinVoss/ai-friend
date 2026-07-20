import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional

from models.conversation import Turn

logger = logging.getLogger(__name__)

MAX_TURN_LENGTH = 10000  # #176: max chars per turn (~2.5k-5k tokens)


@dataclass
class ConversationBuffer:
    maxlen: int = 20
    _turns: deque = field(default_factory=lambda: deque())
    _next_id: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        # #186: deque supports maxlen directly, no need for list() intermediate
        self._turns = deque(self._turns, maxlen=self.maxlen)

    def add_turn(self, role: str, content: str,
                 metadata: Optional[dict] = None) -> Turn:
        # #176: truncate oversized turns
        if len(content) > MAX_TURN_LENGTH:
            logger.warning(f"[mem] turn too long ({len(content)} chars), truncating to {MAX_TURN_LENGTH}")
            content = content[:MAX_TURN_LENGTH] + "\n...[内容过长，已截断]"
        with self._lock:  # #245: lock before Turn construction for atomic ID+append
            turn = Turn(
                turn_id=self._next_id,
                role=role,
                content=content,
                timestamp=datetime.now(),
                metadata=metadata or {},
            )
            self._next_id += 1
            self._turns.append(turn)
        logger.debug(f"[mem] short_term add: role={role} len={len(content)} total={len(self._turns)}")
        return turn

    def get_recent(self, k: int) -> list[Turn]:
        with self._lock:
            return list(self._turns)[-k:]

    def get_all(self) -> list[Turn]:
        with self._lock:
            return list(self._turns)

    def get_all_reversed(self) -> list[Turn]:
        """Return turns newest-first. #ST-002: builds a new list (reversed view
        of the deque) — the old 'without copy' comment was inaccurate."""
        with self._lock:
            return list(reversed(self._turns))

    def format_for_prompt(self, max_tokens: int = 1800) -> str:
        """#ST-003: param is a token budget, not a char count — renamed from
        max_chars. Behavior preserved: the old max_chars=3000 with a *0.6
        multiplier yielded a ~1800-token budget, so callers now pass tokens
        directly.

        2026-07-20: 睡眠/梦话轮（metadata.sleep=True）不占 prompt 预算——
        它们对理解用户输入没有帮助，却会把真正的对话挤出 token 窗口；
        连续重复消息（刷屏）只保留一条。睡眠轮仍在缓冲里，consolidation
        等其他消费方不受影响。"""
        from core.context_manager import estimate_tokens
        with self._lock:
            lines = []
            total = 0
            for t in reversed(self._turns):
                if t.metadata.get("sleep"):
                    continue
                label = "你" if t.role == "assistant" else "用户"
                line = f"{label}: {t.content}"
                if lines and lines[-1] == line:
                    continue  # 连续重复刷屏合并为一条
                # #187: use token count for accurate truncation
                total += estimate_tokens(line)
                if total > max_tokens:
                    lines.append("...[省略更早对话]")
                    break
                lines.append(line)
            lines.reverse()
        return "\n".join(lines)

    def clear(self) -> None:
        with self._lock:
            n = len(self._turns)
            self._turns.clear()
        logger.info(f"[mem] short_term cleared: was {n} turns")

    @property
    def is_full(self) -> bool:
        with self._lock:
            return len(self._turns) == self.maxlen  # #188: deque maxlen is a hard cap
