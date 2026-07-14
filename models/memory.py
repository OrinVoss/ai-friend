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


# ML-001: Layer 1 Memory lifecycle models
FactV2Status = Literal["active", "decayed", "merged", "obsolete", "contradicted"]


@dataclass
class Observation:
    """A raw, low-confidence observation extracted from a conversation turn.

    Observations are the entry point of the memory lifecycle. They are cheap to
    create and should never be promoted to long-term memory without verification.
    """
    id: Optional[int] = None
    content: str = ""
    episode_turn_start: Optional[int] = None
    episode_turn_end: Optional[int] = None
    source_turn: Optional[int] = None
    created_by: str = "consolidation"
    created_at: str = ""
    session_id: str = ""
    embedding: Optional[bytes] = None
    embedding_version: int = 0
    is_archived: bool = False

    def __post_init__(self) -> None:
        if not self.content or not self.content.strip():
            raise ValueError("Observation.content cannot be empty")


@dataclass
class FactV2:
    """A verified fact with multi-dimensional scoring.

    Facts are promoted from observations after repeated evidence or explicit
    confirmation. They carry confidence, stability, freshness and importance so
    that retrieval and garbage collection can reason about their value over time.
    """
    id: Optional[int] = None
    category: str = ""
    fact_key: str = ""
    fact_value: str = ""
    confidence: float = 0.5
    stability: float = 0.5
    freshness: float = 1.0
    importance: float = 0.5
    status: FactV2Status = "active"
    source_observation_ids: list[int] = field(default_factory=list)
    verification_count: int = 0
    last_verified_at: Optional[str] = None
    created_by: str = "consolidation"
    created_at: str = ""
    updated_at: str = ""
    session_id: str = ""
    embedding: Optional[bytes] = None
    embedding_version: int = 0

    def __post_init__(self) -> None:
        for field_name in ("confidence", "stability", "freshness", "importance"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                setattr(self, field_name, max(0.0, min(1.0, value)))
        if not self.category or not self.fact_key:
            raise ValueError("FactV2.category and fact_key cannot be empty")
