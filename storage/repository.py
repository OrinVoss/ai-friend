import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from models.memory import UserFact, Experience, Reflection
from storage.database import Database
from core.async_utils import run_async

logger = logging.getLogger(__name__)


class Repository:
    def __init__(self, db: Database):
        self.db = db
        self.session_id: str = "default"  # #40: override per session

    # ── Sync wrappers ──
    def insert_turn_sync(self, *a, **kw): return run_async(self.insert_turn(*a, **kw))
    def get_recent_turns_sync(self, *a, **kw): return run_async(self.get_recent_turns(*a, **kw))

    # ── User Facts ──

    async def upsert_fact(self, category: str, key: str, value: str,
                          confidence: float = 1.0, source_turn: Optional[int] = None,
                          importance: float = 0.5,
                          fact_type: str = "user_fact",
                          embedding: Optional[bytes] = None) -> int:
        logger.info(f"[db] upsert_fact: {category}/{key} confidence={confidence:.2f} imp={importance:.2f} type={fact_type}")
        async with self.db.cursor() as c:
            if embedding is not None:
                await c.execute("""
                    INSERT INTO user_facts (category, fact_key, fact_value, fact_type, confidence, importance,
                                           source_turn, embedding, embedding_version, session_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(category, fact_key) DO UPDATE SET
                        fact_value = CASE WHEN excluded.confidence >= user_facts.confidence
                                         THEN excluded.fact_value ELSE user_facts.fact_value END,
                        confidence = MAX(user_facts.confidence, excluded.confidence),
                        importance = MAX(user_facts.importance, excluded.importance),
                        recall_count = user_facts.recall_count + 1,
                        embedding = excluded.embedding,
                        embedding_version = 1,
                        updated_at = CURRENT_TIMESTAMP
                """, (category, key, value, fact_type, confidence, importance, source_turn, embedding, self.session_id))
            else:
                await c.execute("""
                    INSERT INTO user_facts (category, fact_key, fact_value, fact_type, confidence, importance,
                                           source_turn, session_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(category, fact_key) DO UPDATE SET
                        fact_value = CASE WHEN excluded.confidence >= user_facts.confidence
                                         THEN excluded.fact_value ELSE user_facts.fact_value END,
                        confidence = MAX(user_facts.confidence, excluded.confidence),
                        importance = MAX(user_facts.importance, excluded.importance),
                        recall_count = user_facts.recall_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """, (category, key, value, fact_type, confidence, importance, source_turn, self.session_id))
            await self.db.commit()
            return c.lastrowid

    async def search_facts(self, query: str = "", limit: int = 30) -> list[UserFact]:
        logger.debug(f"[db] search_facts: query='{query[:40]}' limit={limit}")
        async with self.db.cursor() as c:
            if query:
                await c.execute("""
                    SELECT * FROM user_facts
                    WHERE is_active = 1
                      AND confidence >= 0.2
                      AND fact_type = 'user_fact'
                      AND session_id = ?
                      AND (fact_key LIKE ? OR fact_value LIKE ? OR category LIKE ?)
                    ORDER BY composite_score DESC, recall_count DESC
                    LIMIT ?
                """, (self.session_id, f"%{query}%", f"%{query}%", f"%{query}%", limit))
            else:
                await c.execute("""
                    SELECT * FROM user_facts
                    WHERE is_active = 1
                      AND confidence >= 0.2
                      AND fact_type = 'user_fact'
                      AND session_id = ?
                    ORDER BY composite_score DESC, recall_count DESC
                    LIMIT ?
                """, (self.session_id, limit))
            return [self._row_to_fact(r) for r in await c.fetchall()]

    async def get_active_facts(self, limit: int = 50) -> list[UserFact]:
        logger.debug(f"[db] get_active_facts: limit={limit}")
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM user_facts
                WHERE is_active = 1
                  AND confidence >= 0.2
                  AND fact_type = 'user_fact'
                  AND session_id = ?
                ORDER BY composite_score DESC, recall_count DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_fact(r) for r in await c.fetchall()]

    async def update_fact_score(self, fact_id: int, score: float) -> None:
        async with self.db.cursor() as c:
            await c.execute("UPDATE user_facts SET composite_score = ? WHERE id = ?",
                            (score, fact_id))
            await self.db.commit()

    async def increment_fact_recall(self, fact_id: int) -> None:
        async with self.db.cursor() as c:
            await c.execute("UPDATE user_facts SET recall_count = recall_count + 1 WHERE id = ?",
                            (fact_id,))
            await self.db.commit()

    async def deactivate_fact(self, fact_id: int) -> None:
        """Soft-delete a fact (set is_active=0). Used when a fact is contradicted."""
        logger.info(f"[db] deactivate_fact id={fact_id}")
        async with self.db.cursor() as c:
            await c.execute(
                "UPDATE user_facts SET is_active = 0, composite_score = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (fact_id,))
            await self.db.commit()

    async def update_fact_confidence(self, fact_id: int, new_confidence: float) -> None:
        """Lower a fact's confidence (unlike upsert which only takes MAX)."""
        logger.info(f"[db] update_fact_confidence id={fact_id} confidence={new_confidence:.2f}")
        async with self.db.cursor() as c:
            await c.execute(
                "UPDATE user_facts SET confidence = ?, composite_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_confidence, new_confidence * 0.7, fact_id))
            await self.db.commit()

    async def get_similar_facts(self, category: str, key: str, limit: int = 5) -> list[UserFact]:
        """Find facts with similar category or key for contradiction checking."""
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM user_facts
                WHERE is_active = 1
                  AND (category = ? OR fact_key LIKE ?)
                ORDER BY composite_score DESC
                LIMIT ?
            """, (category, f"%{key}%", limit))
            return [self._row_to_fact(r) for r in await c.fetchall()]

    # ── Experiences ──

    async def insert_experience(self, summary: str, tone: str, significance: float,
                                tags: list[str], turn_start: Optional[int] = None,
                                turn_end: Optional[int] = None,
                                importance: float = 0.5,
                                embedding: Optional[bytes] = None) -> int:
        logger.info(f"[db] insert_exp: {summary[:60]} tone={tone} sig={significance:.2f} imp={importance:.2f}")
        async with self.db.cursor() as c:
            await c.execute("""
                INSERT INTO experiences (summary, emotional_tone, significance, importance, tags,
                                         turn_range_start, turn_range_end, embedding, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (summary, tone, significance, importance, json.dumps(tags, ensure_ascii=False),
                  turn_start, turn_end, embedding))
            await self.db.commit()
            return c.lastrowid

    async def search_experiences(self, keywords: list[str] | None = None,
                                 limit: int = 10) -> list[Experience]:
        async with self.db.cursor() as c:
            if keywords:
                conditions = " OR ".join("(summary LIKE ? OR tags LIKE ?)" for _ in keywords)
                params = []
                for kw in keywords:
                    params.extend([f"%{kw}%", f"%{kw}%"])
                await c.execute(f"""
                    SELECT * FROM experiences
                    WHERE is_archived = 0 AND ({conditions})
                    ORDER BY composite_score DESC, created_at DESC
                    LIMIT ?
                """, params + [limit])
            else:
                await c.execute("""
                    SELECT * FROM experiences
                    WHERE is_archived = 0
                    ORDER BY composite_score DESC, created_at DESC
                    LIMIT ?
                """, (limit,))
            return [self._row_to_experience(r) for r in await c.fetchall()]

    async def get_recent_experiences(self, limit: int = 5) -> list[Experience]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM experiences
                WHERE is_archived = 0
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [self._row_to_experience(r) for r in await c.fetchall()]

    async def update_experience_score(self, exp_id: int, score: float) -> None:
        async with self.db.cursor() as c:
            await c.execute("UPDATE experiences SET composite_score = ? WHERE id = ?",
                            (score, exp_id))
            await self.db.commit()

    # ── Reflections ──

    async def insert_reflection(self, content: str, insight_type: str,
                                related_ids: list[int], significance: float,
                                embedding: Optional[bytes] = None) -> int:
        logger.info(f"[db] insert_ref: type={insight_type} sig={significance:.2f} content={content[:60]}")
        async with self.db.cursor() as c:
            await c.execute("""
                INSERT INTO reflections (content, insight_type, related_experience_ids, significance,
                                         embedding, embedding_version)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (content, insight_type, json.dumps(related_ids), significance, embedding))
            await self.db.commit()
            return c.lastrowid

    async def get_recent_reflections(self, limit: int = 5) -> list[Reflection]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM reflections WHERE is_active = 1
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [self._row_to_reflection(r) for r in await c.fetchall()]

    async def bulk_update_embeddings(self, table: str, updates: list[tuple[int, bytes]]):
        if not updates:
            return
        async with self.db.cursor() as c:
            await c.executemany(
                f"UPDATE {table} SET embedding = ?, embedding_version = 1 WHERE id = ?",
                [(emb, rid) for rid, emb in updates],
            )
            logger.debug(f"[db] bulk_embed: updated {len(updates)} rows in {table}")

    # ── Relationship ──

    async def get_all_relationships(self) -> dict[str, float]:
        async with self.db.cursor() as c:
            await c.execute("SELECT dimension, value FROM relationship_metrics")
            return {r["dimension"]: r["value"] for r in await c.fetchall()}

    async def upsert_relationship(self, dimension: str, value: float) -> None:
        logger.info(f"[db] upsert_rel: {dimension}={value:.2f}")
        async with self.db.cursor() as c:
            await c.execute("BEGIN")
            await c.execute("""
                INSERT INTO relationship_metrics (dimension, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(dimension) DO UPDATE SET
                    value = ?, updated_at = CURRENT_TIMESTAMP
            """, (dimension, value, value))
            # #132: insert snapshot for time-series tracking
            await c.execute("""
                INSERT INTO relationship_snapshots (dimension, value)
                VALUES (?, ?)
            """, (dimension, value))
            await self.db.commit()

    async def get_relationship_history(self, days: int = 30) -> list[dict]:
        """Get relationship metric time-series for the last N days. (#132)"""
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT dimension, value, created_at
                FROM relationship_snapshots
                WHERE created_at >= datetime('now', ?)
                ORDER BY created_at ASC
            """, (f'-{days} days',))
            return [{"dimension": r["dimension"], "value": r["value"],
                     "created_at": r["created_at"]} for r in await c.fetchall()]

    # ── Conversation Turns ──

    async def insert_turn(self, turn_number: int, role: str, content: str,
                          emotional_state: Optional[str] = None,
                          is_tool_claim: bool = False) -> int:  # #130
        logger.info(f"[db] insert_turn: turn={turn_number} role={role} len={len(content)} claim={is_tool_claim}")
        async with self.db.cursor() as c:
            await c.execute("""
                INSERT INTO conversation_turns (turn_number, role, content, emotional_state, is_tool_claim, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (turn_number, role, content, emotional_state, int(is_tool_claim), self.session_id))
            await self.db.commit()
            return c.lastrowid

    async def get_recent_turns(self, limit: int = 30, session_id: str | None = None) -> list[dict]:
        async with self.db.cursor() as c:
            sid = session_id or self.session_id
            await c.execute("""
                SELECT role, content FROM conversation_turns
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
            """, (sid, limit))
            rows = await c.fetchall()
        rows = list(rows)
        rows.reverse()
        return [{"role": r[0], "content": r[1]} for r in rows]

    # ── Pruning ──

    async def prune_facts(self, max_count: int) -> int:
        async with self.db.cursor() as c:
            await c.execute("SELECT COUNT(*) FROM user_facts WHERE is_active = 1")
            row = await c.fetchone()
            count = row[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            logger.info(f"[db] prune_facts: degrading {excess} of {count}")
            # #135: degrade score instead of deactivating — pruned facts can still be found
            await c.execute("""
                UPDATE user_facts SET composite_score = composite_score * 0.1
                WHERE id IN (
                    SELECT id FROM user_facts WHERE is_active = 1
                    ORDER BY composite_score ASC, recall_count ASC
                    LIMIT ?
                )
            """, (excess,))
            await self.db.commit()
            return c.rowcount

    async def prune_experiences(self, max_count: int) -> int:
        async with self.db.cursor() as c:
            await c.execute("SELECT COUNT(*) FROM experiences WHERE is_archived = 0")
            row = await c.fetchone()
            count = row[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            logger.info(f"[db] prune_exps: pruning {excess} of {count}")
            await self.db.commit()
            await c.execute("""
                UPDATE experiences SET is_archived = 1
                WHERE id IN (
                    SELECT id FROM experiences WHERE is_archived = 0
                    ORDER BY composite_score ASC, created_at ASC
                    LIMIT ?
                )
            """, (excess,))
            await self.db.commit()
            return c.rowcount

    async def prune_reflections(self, max_count: int) -> int:
        async with self.db.cursor() as c:
            await c.execute("SELECT COUNT(*) FROM reflections WHERE is_active = 1")
            row = await c.fetchone()
            count = row[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            logger.info(f"[db] prune_refl: pruning {excess} of {count}")
            await c.execute("""
                UPDATE reflections SET is_active = 0 WHERE id IN (
                    SELECT id FROM reflections WHERE is_active = 1
                    ORDER BY significance ASC, created_at ASC
                    LIMIT ?
                )
            """, (excess,))
            await self.db.commit()
            return c.rowcount

    # ── Helpers ──

    def _row_to_fact(self, r) -> UserFact:
        return UserFact(
            id=r["id"], category=r["category"], fact_key=r["fact_key"],
            fact_value=r["fact_value"],
            fact_type=r["fact_type"] if "fact_type" in r.keys() else "user_fact",
            confidence=r["confidence"],
            importance=r["importance"],
            source_turn=r["source_turn"], created_at=r["created_at"],
            updated_at=r["updated_at"], recall_count=r["recall_count"],
            is_active=bool(r["is_active"]), composite_score=r["composite_score"],
            embedding=r["embedding"] if "embedding" in r.keys() else None,
            embedding_version=r["embedding_version"] if "embedding_version" in r.keys() else 0,
        )

    def _row_to_experience(self, r) -> Experience:
        return Experience(
            id=r["id"], summary=r["summary"], emotional_tone=r["emotional_tone"],
            significance=r["significance"],
            importance=r["importance"],
            tags=json.loads(r["tags"]) if r["tags"] else [],
            turn_range_start=r["turn_range_start"],
            turn_range_end=r["turn_range_end"],
            created_at=r["created_at"], recall_count=r["recall_count"],
            is_archived=bool(r["is_archived"]), composite_score=r["composite_score"],
        )

    def _row_to_reflection(self, r) -> Reflection:
        return Reflection(
            id=r["id"], content=r["content"], insight_type=r["insight_type"],
            related_experience_ids=json.loads(r["related_experience_ids"])
            if r["related_experience_ids"] else [],
            significance=r["significance"], created_at=r["created_at"],
        )
