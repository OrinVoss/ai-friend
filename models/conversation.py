from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models.memory import UserFact, Experience, Reflection


@dataclass
class Turn:
    turn_id: int
    role: str          # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class MemoryContext:
    facts: list[UserFact] = field(default_factory=list)
    experiences: list[Experience] = field(default_factory=list)
    reflections: list[Reflection] = field(default_factory=list)
    relationship: dict[str, float] = field(default_factory=lambda: {
        "trust": 0.3, "familiarity": 0.3, "intimacy": 0.3, "playfulness": 0.3,
    })
