"""Conversation context models: single turn and memory context for prompt building."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal

from models.memory import UserFact, Experience, Reflection


@dataclass
class Turn:
    turn_id: int
    role: Literal["user", "assistant"]    # MC-002: typed
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """MC-001: serialize to a JSON-safe dict with ISO 8601 timestamp."""
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class MemoryContext:
    facts: list[UserFact] = field(default_factory=list)
    experiences: list[Experience] = field(default_factory=list)
    reflections: list[Reflection] = field(default_factory=list)
    relationship: dict[str, float] = field(default_factory=dict)  # MC-003: empty default
