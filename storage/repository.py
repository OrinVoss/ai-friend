import json
import sqlite3
from datetime import datetime
from typing import Optional

from models.memory import UserFact, Experience, Reflection
from storage.database import Database


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ── User Facts ──

    def upsert_fact(self, category: str, key: str, value: str,
                    confidence: float = 1.0, source_turn: Optional[int] = None,
                    importance: float = 0.5) -> int:
        with self.db.cursor() as c:
            c.execute("""
                INSERT INTO user_facts (category, fact_key, fact_value, confidence, importance, source_turn, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(category, fact_key) DO UPDATE SET
                    fact_value = CASE WHEN excluded.confidence >= user_facts.confidence
                                     THEN excluded.fact_value ELSE user_facts.fact_value END,
                    confidence = MAX(user_facts.confidence, excluded.confidence),
                    importance = MAX(user_facts.importance, excluded.importance),
                    recall_count = user_facts.recall_count + 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (category, key, value, confidence, importance, source_turn))
            return c.lastrowid

    def search_facts(self, query: str = "", limit: int = 30) -> list[UserFact]:
        with self.db.cursor() as c:
            if query:
                c.execute("""
                    SELECT * FROM user_facts
                    WHERE is_active = 1
                      AND (fact_key LIKE ? OR fact_value LIKE ? OR category LIKE ?)
                    ORDER BY composite_score DESC, recall_count DESC
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
            else:
                c.execute("""
                    SELECT * FROM user_facts
                    WHERE is_active = 1
                    ORDER BY composite_score DESC, recall_count DESC
                    LIMIT ?
                """, (limit,))
            return [self._row_to_fact(r) for r in c.fetchall()]

    def get_active_facts(self, limit: int = 50) -> list[UserFact]:
        with self.db.cursor() as c:
            c.execute("""
                SELECT * FROM user_facts
                WHERE is_active = 1
                ORDER BY composite_score DESC, recall_count DESC
                LIMIT ?
            """, (limit,))
            return [self._row_to_fact(r) for r in c.fetchall()]

    def update_fact_score(self, fact_id: int, score: float) -> None:
        with self.db.cursor() as c:
            c.execute("UPDATE user_facts SET composite_score = ? WHERE id = ?",
                      (score, fact_id))

    def increment_fact_recall(self, fact_id: int) -> None:
        with self.db.cursor() as c:
            c.execute("UPDATE user_facts SET recall_count = recall_count + 1 WHERE id = ?",
                      (fact_id,))

    # ── Experiences ──

    def insert_experience(self, summary: str, tone: str, significance: float,
                          tags: list[str], turn_start: Optional[int] = None,
                          turn_end: Optional[int] = None,
                          importance: float = 0.5) -> int:
        with self.db.cursor() as c:
            c.execute("""
                INSERT INTO experiences (summary, emotional_tone, significance, importance, tags,
                                         turn_range_start, turn_range_end)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (summary, tone, significance, importance, json.dumps(tags, ensure_ascii=False),
                  turn_start, turn_end))
            return c.lastrowid

    def search_experiences(self, keywords: list[str] | None = None,
                           limit: int = 10) -> list[Experience]:
        with self.db.cursor() as c:
            if keywords:
                conditions = " OR ".join(
                    "(summary LIKE ? OR tags LIKE ?)" for _ in keywords
                )
                params = []
                for kw in keywords:
                    params.extend([f"%{kw}%", f"%{kw}%"])
                c.execute(f"""
                    SELECT * FROM experiences
                    WHERE is_archived = 0 AND ({conditions})
                    ORDER BY composite_score DESC, created_at DESC
                    LIMIT ?
                """, params + [limit])
            else:
                c.execute("""
                    SELECT * FROM experiences
                    WHERE is_archived = 0
                    ORDER BY composite_score DESC, created_at DESC
                    LIMIT ?
                """, (limit,))
            return [self._row_to_experience(r) for r in c.fetchall()]

    def get_recent_experiences(self, limit: int = 5) -> list[Experience]:
        with self.db.cursor() as c:
            c.execute("""
                SELECT * FROM experiences
                WHERE is_archived = 0
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [self._row_to_experience(r) for r in c.fetchall()]

    def update_experience_score(self, exp_id: int, score: float) -> None:
        with self.db.cursor() as c:
            c.execute("UPDATE experiences SET composite_score = ? WHERE id = ?",
                      (score, exp_id))

    # ── Reflections ──

    def insert_reflection(self, content: str, insight_type: str,
                          related_ids: list[int], significance: float) -> int:
        with self.db.cursor() as c:
            c.execute("""
                INSERT INTO reflections (content, insight_type, related_experience_ids, significance)
                VALUES (?, ?, ?, ?)
            """, (content, insight_type, json.dumps(related_ids), significance))
            return c.lastrowid

    def get_recent_reflections(self, limit: int = 5) -> list[Reflection]:
        with self.db.cursor() as c:
            c.execute("""
                SELECT * FROM reflections WHERE is_active = 1
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [self._row_to_reflection(r) for r in c.fetchall()]

    # ── Relationship ──

    def get_all_relationships(self) -> dict[str, float]:
        with self.db.cursor() as c:
            c.execute("SELECT dimension, value FROM relationship_metrics")
            return {r["dimension"]: r["value"] for r in c.fetchall()}

    def upsert_relationship(self, dimension: str, value: float) -> None:
        with self.db.cursor() as c:
            c.execute("""
                INSERT INTO relationship_metrics (dimension, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(dimension) DO UPDATE SET
                    value = ?, updated_at = CURRENT_TIMESTAMP
            """, (dimension, value, value))

    # ── Conversation Turns ──

    def insert_turn(self, turn_number: int, role: str, content: str,
                    emotional_state: Optional[str] = None) -> int:
        with self.db.cursor() as c:
            c.execute("""
                INSERT INTO conversation_turns (turn_number, role, content, emotional_state)
                VALUES (?, ?, ?, ?)
            """, (turn_number, role, content, emotional_state))
            return c.lastrowid

    # ── Pruning ──

    def prune_facts(self, max_count: int) -> int:
        """Keep top N by composite_score, archive the rest. Returns pruned count."""
        with self.db.cursor() as c:
            c.execute("SELECT COUNT(*) FROM user_facts WHERE is_active = 1")
            count = c.fetchone()[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            c.execute("""
                UPDATE user_facts SET is_active = 0, composite_score = 0
                WHERE id IN (
                    SELECT id FROM user_facts WHERE is_active = 1
                    ORDER BY composite_score ASC, recall_count ASC
                    LIMIT ?
                )
            """, (excess,))
            return c.rowcount

    def prune_experiences(self, max_count: int) -> int:
        with self.db.cursor() as c:
            c.execute("SELECT COUNT(*) FROM experiences WHERE is_archived = 0")
            count = c.fetchone()[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            c.execute("""
                UPDATE experiences SET is_archived = 1
                WHERE id IN (
                    SELECT id FROM experiences WHERE is_archived = 0
                    ORDER BY composite_score ASC, created_at ASC
                    LIMIT ?
                )
            """, (excess,))
            return c.rowcount

    def prune_reflections(self, max_count: int) -> int:
        with self.db.cursor() as c:
            c.execute("SELECT COUNT(*) FROM reflections WHERE is_active = 1")
            count = c.fetchone()[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            c.execute("""
                UPDATE reflections SET is_active = 0 WHERE id IN (
                    SELECT id FROM reflections WHERE is_active = 1
                    ORDER BY significance ASC, created_at ASC
                    LIMIT ?
                )
            """, (excess,))
            return c.rowcount

    # ── Helpers ──

    def _row_to_fact(self, r: sqlite3.Row) -> UserFact:
        return UserFact(
            id=r["id"], category=r["category"], fact_key=r["fact_key"],
            fact_value=r["fact_value"], confidence=r["confidence"],
            importance=r["importance"],
            source_turn=r["source_turn"], created_at=r["created_at"],
            updated_at=r["updated_at"], recall_count=r["recall_count"],
            is_active=bool(r["is_active"]), composite_score=r["composite_score"],
        )

    def _row_to_experience(self, r: sqlite3.Row) -> Experience:
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

    def _row_to_reflection(self, r: sqlite3.Row) -> Reflection:
        return Reflection(
            id=r["id"], content=r["content"], insight_type=r["insight_type"],
            related_experience_ids=json.loads(r["related_experience_ids"])
            if r["related_experience_ids"] else [],
            significance=r["significance"], created_at=r["created_at"],
        )
