from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UserFact:
    id: Optional[int] = None
    category: str = ""
    fact_key: str = ""
    fact_value: str = ""
    fact_type: str = "user_fact"    # user_fact | agent_fact | system_fact (#127)
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


@dataclass
class Experience:
    id: Optional[int] = None
    summary: str = ""
    emotional_tone: str = "neutral"
    significance: float = 0.5
    importance: float = 0.5       # 同上
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
    insight_type: str = ""
    related_experience_ids: list[int] = field(default_factory=list)
    significance: float = 0.5
    created_at: str = ""
