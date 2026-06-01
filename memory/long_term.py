import asyncio
import logging
import re
from typing import Optional

from models.memory import UserFact, Experience, Reflection
from storage.repository import Repository
from models.conversation import MemoryContext
from core.async_utils import run_async

logger = logging.getLogger(__name__)


class LongTermMemory:
    def __init__(self, repo: Repository):
        self.repo = repo

    # ── Async methods ──

    async def _store_fact(self, category: str, key: str, value: str,
                         confidence: float = 1.0,
                         source_turn: Optional[int] = None,
                         importance: float = 0.5,
                         fact_type: str = "user_fact",
                         embedding: Optional[bytes] = None) -> int:
        logger.debug(f"[mem] store_fact: {category}/{key} type={fact_type}")
        return await self.repo.upsert_fact(category, key, value, confidence, source_turn,
                                          importance, fact_type, embedding)

    async def _search_facts(self, query: str = "", limit: int = 30) -> list[UserFact]:
        return await self.repo.search_facts(query, limit)

    async def _get_all_active_facts(self, limit: int = 50) -> list[UserFact]:
        return await self.repo.get_active_facts(limit)

    async def _store_experience(self, summary: str, tone: str, significance: float,
                               tags: list[str], turn_start: Optional[int] = None,
                               turn_end: Optional[int] = None,
                               importance: float = 0.5,
                               embedding: Optional[bytes] = None) -> int:
        logger.debug(f"[mem] store_exp: {summary[:50]} significance={significance:.2f}")
        return await self.repo.insert_experience(summary, tone, significance,
                                                 tags, turn_start, turn_end, importance,
                                                 embedding)

    async def _search_experiences(self, keywords: list[str] | None = None,
                                 limit: int = 10) -> list[Experience]:
        return await self.repo.search_experiences(keywords, limit)

    async def _get_recent_experiences(self, limit: int = 5) -> list[Experience]:
        return await self.repo.get_recent_experiences(limit)

    async def _store_reflection(self, content: str, insight_type: str,
                               related_ids: list[int],
                               significance: float = 0.5,
                               embedding: Optional[bytes] = None) -> int:
        return await self.repo.insert_reflection(content, insight_type,
                                                 related_ids, significance, embedding)

    async def _get_recent_reflections(self, limit: int = 3) -> list[Reflection]:
        return await self.repo.get_recent_reflections(limit)

    async def _get_relationship(self) -> dict[str, float]:
        return await self.repo.get_all_relationships()

    async def _update_relationship(self, dimension: str, value: float) -> None:
        await self.repo.upsert_relationship(dimension, value)

    async def _deactivate_fact(self, fact_id: int) -> None:
        await self.repo.deactivate_fact(fact_id)

    async def _update_fact_confidence(self, fact_id: int, new_confidence: float) -> None:
        await self.repo.update_fact_confidence(fact_id, new_confidence)

    async def _correct_fact(self, category: str, key: str, value: str,
                           old_fact_id: Optional[int] = None) -> int:
        """User-corrected fact: deactivate old version, store new with confidence=1.0."""
        logger.info(f"[mem] correct_fact: {category}/{key} = {value} (old_id={old_fact_id})")
        if old_fact_id:
            await self.repo.deactivate_fact(old_fact_id)
        return await self.repo.upsert_fact(
            category, key, value,
            confidence=1.0, importance=0.9,
        )

    async def _build_context(self, query: str = "") -> MemoryContext:
        facts = await self._search_facts(query, limit=10)
        keywords = re.findall(r'[\w一-鿿]+', query.lower())
        keywords = [w for w in keywords if len(w) > 1] if query else []
        experiences = await self._search_experiences(keywords, limit=5)
        # #194: don't fall back to recent experiences — they may be irrelevant
        reflections = await self._get_recent_reflections(limit=3)
        relationship = await self._get_relationship()
        logger.debug(f"[mem] context built: facts={len(facts)} exps={len(experiences)} refl={len(reflections)}")
        return MemoryContext(
            facts=facts, experiences=experiences,
            reflections=reflections, relationship=relationship,
        )

    # ── Sync wrappers ──

    def store_fact(self, *a, **kw): return run_async(self._store_fact(*a, **kw))  # #193: single definition
    def search_facts(self, *a, **kw): return run_async(self._search_facts(*a, **kw))
    def get_all_active_facts(self, *a, **kw): return run_async(self._get_all_active_facts(*a, **kw))
    def store_experience(self, *a, **kw): return run_async(self._store_experience(*a, **kw))
    def search_experiences(self, *a, **kw): return run_async(self._search_experiences(*a, **kw))
    def get_recent_experiences(self, *a, **kw): return run_async(self._get_recent_experiences(*a, **kw))
    def store_reflection(self, *a, **kw): return run_async(self._store_reflection(*a, **kw))
    def get_recent_reflections(self, *a, **kw): return run_async(self._get_recent_reflections(*a, **kw))
    def get_relationship(self): return run_async(self._get_relationship())
    def update_relationship(self, *a, **kw): return run_async(self._update_relationship(*a, **kw))
    def build_context(self, *a, **kw): return run_async(self._build_context(*a, **kw))
    def deactivate_fact(self, *a, **kw): return run_async(self._deactivate_fact(*a, **kw))
    def update_fact_confidence(self, *a, **kw): return run_async(self._update_fact_confidence(*a, **kw))
    def correct_fact(self, *a, **kw): return run_async(self._correct_fact(*a, **kw))
    def get_similar_facts(self, category: str, key: str, limit: int = 5):  # #195: explicit params
        return run_async(self.repo.get_similar_facts(category, key, limit))
    def get_relationship_history(self, days: int = 30):  # #195: explicit params
        return run_async(self.repo.get_relationship_history(days))
