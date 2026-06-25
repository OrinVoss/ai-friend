"""Data models for the AI Friend memory system."""
from dataclasses import dataclass, field
from typing import Optional, Literal


# MM-004: Emotional tone enum — used by Experience
EmotionalTone = Literal[
    "neutral", "joyful", "sad", "angry", "anxious", "trusting", "surprised",
    "melancholy", "frustrated", "disgusted", "excited", "engaged", "content",
    "anticipating", "afraid",
]

# MM-005: Insight type enum — used by Reflection
InsightType = Literal[
    "pattern", "contradiction", "connection", "emotion", "decision",
]

FactType = Literal["user_fact", "agent_fact", "system_fact"]


@dataclass
class UserFact:
    id: Optional[int] = None
    category: str = ""
    fact_key: str = ""
    fact_value: str = ""
    fact_type: FactType = "user_fact"    # MM-003: now a Literal
    confidence: float = 1.0
    importance: float = 0.5
    source_turn: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""
    recall_count: int = 0
    is_active: bool = True
    composite_score: float = 1.0
    embedding: Optional[bytes] = None        # (#138)
    embedding_version: int = 0               # (#138)

    def __post_init__(self) -> None:
        # MM-002: clamp confidence/importance to valid range
        if not 0.0 <= self.confidence <= 1.0:
            self.confidence = max(0.0, min(1.0, self.confidence))
        if not 0.0 <= self.importance <= 1.0:
            self.importance = max(0.0, min(1.0, self.importance))

    @property
    def runtime_score(self) -> float:
        """MM-001: composite score weighted by current confidence."""
        return self.composite_score * self.confidence


@dataclass
class Experience:
    id: Optional[int] = None
    summary: str = ""
    emotional_tone: EmotionalTone = "neutral"   # MM-004: typed
    significance: float = 0.5
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    turn_range_start: Optional[int] = None
    turn_range_end: Optional[int] = None
    created_at: str = ""
    recall_count: int = 0
    is_archived: bool = False
    composite_score: float = 0.5


@dataclass
class Reflection:
    id: Optional[int] = None
    content: str = ""
    insight_type: InsightType = "pattern"         # MM-005: typed
    related_experience_ids: list[int] = field(default_factory=list)
    significance: float = 0.5
    created_at: str = ""
    level: int = 1                                # MM-006: L1/L2/L3
    parent_ids: list[int] = field(default_factory=list)  # MM-006
