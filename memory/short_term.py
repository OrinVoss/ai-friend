from dataclasses import dataclass
from datetime import datetime
from collections import deque
from typing import Optional

from models.conversation import Turn


@dataclass
class ConversationBuffer:
    maxlen: int = 20
    _turns: deque = None
    _next_id: int = 0

    def __post_init__(self):
        self._turns = deque(maxlen=self.maxlen)

    def add_turn(self, role: str, content: str,
                 metadata: Optional[dict] = None) -> Turn:
        turn = Turn(
            turn_id=self._next_id,
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {},
        )
        self._next_id += 1
        self._turns.append(turn)
        return turn

    def get_recent(self, k: int) -> list[Turn]:
        return list(self._turns)[-k:]

    def get_all(self) -> list[Turn]:
        return list(self._turns)

    def format_for_prompt(self, max_chars: int = 3000) -> str:
        lines = []
        total = 0
        for t in self._turns:
            label = "你" if t.role == "assistant" else "用户"
            line = f"{label}: {t.content}"
            total += len(line)
            if total > max_chars:
                lines.append("...[省略较早对话]")
                break
            lines.append(line)
        return "\n".join(lines)

    def clear(self) -> None:
        self._turns.clear()

    @property
    def is_full(self) -> bool:
        return len(self._turns) >= self.maxlen

    @property
    def last_n_turns_content(self) -> str:
        return "\n".join(
            f"{'用户' if t.role == 'user' else '你'}: {t.content}"
            for t in self._turns[-5:]
        )
