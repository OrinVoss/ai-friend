from typing import Optional

from models.memory import UserFact, Experience, Reflection
from storage.repository import Repository
from models.conversation import MemoryContext


class LongTermMemory:
    def __init__(self, repo: Repository):
        self.repo = repo

    def store_fact(self, category: str, key: str, value: str,
                   confidence: float = 1.0,
                   source_turn: Optional[int] = None,
                   importance: float = 0.5) -> int:
        return self.repo.upsert_fact(category, key, value, confidence, source_turn, importance)

    def search_facts(self, query: str = "", limit: int = 30) -> list[UserFact]:
        return self.repo.search_facts(query, limit)

    def get_all_active_facts(self, limit: int = 50) -> list[UserFact]:
        return self.repo.get_active_facts(limit)

    def store_experience(self, summary: str, tone: str, significance: float,
                         tags: list[str], turn_start: Optional[int] = None,
                         turn_end: Optional[int] = None,
                         importance: float = 0.5) -> int:
        return self.repo.insert_experience(summary, tone, significance,
                                           tags, turn_start, turn_end, importance)

    def search_experiences(self, keywords: list[str] | None = None,
                           limit: int = 10) -> list[Experience]:
        return self.repo.search_experiences(keywords, limit)

    def get_recent_experiences(self, limit: int = 5) -> list[Experience]:
        return self.repo.get_recent_experiences(limit)

    def store_reflection(self, content: str, insight_type: str,
                         related_ids: list[int],
                         significance: float = 0.5) -> int:
        return self.repo.insert_reflection(content, insight_type,
                                           related_ids, significance)

    def get_recent_reflections(self, limit: int = 3) -> list[Reflection]:
        return self.repo.get_recent_reflections(limit)

    def get_relationship(self) -> dict[str, float]:
        return self.repo.get_all_relationships()

    def update_relationship(self, dimension: str, value: float) -> None:
        self.repo.upsert_relationship(dimension, value)

    def build_context(self, query: str = "") -> MemoryContext:
        facts = self.search_facts(query, limit=10)
        keywords = [w for w in query.split() if len(w) > 1] if query else []
        experiences = self.search_experiences(keywords, limit=5)
        if not experiences:
            experiences = self.get_recent_experiences(limit=3)
        reflections = self.get_recent_reflections(limit=3)
        relationship = self.get_relationship()
        return MemoryContext(
            facts=facts,
            experiences=experiences,
            reflections=reflections,
            relationship=relationship,
        )
