"""Layer 1 Memory lifecycle manager: Observation -> Fact.

ML-001: provides explicit lifecycle stages for memory so that raw observations
are not immediately treated as permanent facts. Insights (Reflections) are left
for Layer 2 and are not managed here.
"""

import logging
from datetime import datetime
from typing import Optional

from memory.embeddings import EmbeddingEngine
from memory.long_term import LongTermMemory
from models.memory import FactV2, Observation

logger = logging.getLogger(__name__)


class MemoryLifecycleManager:
    """Manages Observation -> Fact promotion, verification, decay and GC."""

    def __init__(self, ltm: LongTermMemory, config=None, embedding_engine=None):
        self.ltm = ltm
        self.config = config or {}
        self._embed = embedding_engine
        self._decay_threshold = getattr(config, "fact_decay_threshold", 0.2)
        self._archive_days = getattr(config, "observation_archive_days", 30)

    async def observe(
        self,
        content: str,
        source_turn: Optional[int] = None,
        episode_turn_start: Optional[int] = None,
        episode_turn_end: Optional[int] = None,
        created_by: str = "consolidation",
    ) -> Observation:
        """Create a raw observation from a conversation turn."""
        embedding = await self._embed_text(content)
        obs_id = await self.ltm.repo.insert_observation(
            content=content,
            source_turn=source_turn,
            episode_turn_start=episode_turn_start,
            episode_turn_end=episode_turn_end,
            created_by=created_by,
            embedding=embedding,
        )
        logger.info(f"[lifecycle] observation created: id={obs_id} "
                    f"len={len(content)} by={created_by}")
        return Observation(
            id=obs_id,
            content=content,
            source_turn=source_turn,
            episode_turn_start=episode_turn_start,
            episode_turn_end=episode_turn_end,
            created_by=created_by,
            session_id=self.ltm.repo.session_id,
        )

    async def find_similar_observations(
        self, content: str, limit: int = 5
    ) -> list[Observation]:
        """Find observations that may support or contradict the given content.

        Phase 1 uses simple keyword search. Future iterations can switch to
        embedding similarity once observation embeddings are populated.
        """
        keywords = [w for w in content.split() if len(w) > 1]
        if keywords:
            return await self.ltm.repo.search_observations(keywords[0], limit)
        return await self.ltm.repo.get_recent_observations(limit)

    async def promote_fact(
        self,
        observation_ids: list[int],
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
        stability: float = 0.5,
        freshness: float = 1.0,
        importance: float = 0.5,
        created_by: str = "consolidation",
    ) -> FactV2:
        """Promote one or more observations into a verified fact."""
        text = f"{category} {key} {value}"
        embedding = await self._embed_text(text)
        fact_id = await self.ltm.repo.upsert_fact_v2(
            category=category,
            key=key,
            value=value,
            confidence=confidence,
            stability=stability,
            freshness=freshness,
            importance=importance,
            source_observation_ids=observation_ids,
            created_by=created_by,
            embedding=embedding,
        )
        logger.info(f"[lifecycle] fact promoted: {category}/{key} "
                    f"confidence={confidence:.2f} obs={observation_ids}")
        return FactV2(
            id=fact_id,
            category=category,
            fact_key=key,
            fact_value=value,
            confidence=confidence,
            stability=stability,
            freshness=freshness,
            importance=importance,
            source_observation_ids=list(observation_ids),
            created_by=created_by,
            session_id=self.ltm.repo.session_id,
        )

    async def verify_fact(self, fact_id: int) -> None:
        """Record additional evidence for an existing fact."""
        await self.ltm.repo.verify_fact_v2(fact_id)

    async def contradict_fact(self, fact_id: int, reason: str = "") -> None:
        """Mark a fact as contradicted by new evidence."""
        logger.info(f"[lifecycle] contradict_fact id={fact_id} reason={reason}")
        await self.ltm.repo.update_fact_v2_status(fact_id, "contradicted")

    async def decay(self, now: Optional[datetime] = None) -> None:
        """Decay freshness and confidence of active facts over time."""
        now = now or datetime.utcnow()
        facts = await self.ltm.repo.get_active_facts_v2(limit=1000)
        for fact in facts:
            days_since_verified = 0
            if fact.last_verified_at:
                try:
                    verified = datetime.fromisoformat(
                        fact.last_verified_at.replace("Z", "+00:00")
                    )
                    days_since_verified = (now - verified).days
                except Exception:
                    pass

            # Compound decay: at least 1 day to avoid division by zero surprises.
            decay_factor = 0.99 ** max(days_since_verified, 1)
            await self.ltm.repo.decay_fact_v2(fact.id, decay_factor)

            projected_freshness = fact.freshness * decay_factor
            if projected_freshness < self._decay_threshold:
                await self.ltm.repo.update_fact_v2_status(fact.id, "decayed")
                logger.info(f"[lifecycle] fact {fact.id} decayed")

    async def merge_duplicates(self) -> None:
        """Placeholder for semantic duplicate merging.

        SQLite UNIQUE(session_id, category, fact_key) already prevents exact
        duplicates. Future work can merge near-duplicate keys/values here.
        """
        pass

    async def archive_old_observations(self, max_age_days: int = 30) -> None:
        """Archive observations older than max_age_days."""
        logger.info(f"[lifecycle] archive_old_observations max_age_days={max_age_days}")
        async with self.ltm.repo.db.cursor() as c:
            await c.execute(
                "UPDATE observations SET is_archived = 1 "
                "WHERE session_id = ? AND is_archived = 0 "
                "AND created_at < datetime('now', ?)",
                (self.ltm.repo.session_id, f"-{max_age_days} days"),
            )
            await self.ltm.repo.db.commit()

    async def garbage_collect(self) -> None:
        """Run the full lifecycle GC pass."""
        logger.info("[lifecycle] garbage_collect started")
        await self.decay()
        await self.merge_duplicates()
        await self.archive_old_observations(self._archive_days)
        logger.info("[lifecycle] garbage_collect completed")

    async def _embed_text(self, text: str) -> Optional[bytes]:
        if not self._embed or not self._embed.health_check():
            return None
        try:
            vec = self._embed.encode([text])[0]
            return EmbeddingEngine.vec_to_bytes(vec)
        except Exception as e:
            logger.debug(f"[lifecycle] embedding failed: {e}")
            return None
