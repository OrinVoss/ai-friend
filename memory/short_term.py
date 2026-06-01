import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional

from models.conversation import Turn

logger = logging.getLogger(__name__)


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
        turn = Turn(
            turn_id=self._next_id,
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {},
        )
        with self._lock:
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
        """Return turns in reverse order (newest first) without extra copy."""
        with self._lock:
            return list(reversed(self._turns))

    def format_for_prompt(self, max_chars: int = 3000) -> str:
        from core.context_manager import estimate_tokens
        with self._lock:
            lines = []
            total = 0
            for t in reversed(self._turns):
                label = "你" if t.role == "assistant" else "用户"
                line = f"{label}: {t.content}"
                # #187: use token count instead of character count for accurate truncation
                total += estimate_tokens(line)
                if total > max_chars * 0.6:  # ~60% of char budget as token budget
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

    @property
    def last_n_turns_content(self) -> str:
        with self._lock:
            return "\n".join(
                f"{'用户' if t.role == 'user' else '你'}: {t.content}"
                for t in list(self._turns)[-5:]
            )
