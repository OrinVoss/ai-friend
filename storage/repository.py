import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from models.memory import UserFact, Experience, Reflection, Observation, FactV2, InsightV2, EMBEDDING_VERSION
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
    # Layer 1 完整上线（2026-07-18，schema v4）：以下方法保留旧签名与 UserFact
    # 返回形状（retrieval/tools/prompts/long_term 零改动），SQL 全部重定向到
    # facts_v2。旧表 user_facts 已归档为 user_facts_archive，不再读写。
    # UserFact 适配映射：
    #   composite_score = 0.5*confidence + 0.3*importance + 0.2*freshness（SQL 计算）
    #   recall_count = verification_count；is_active = (status=='active')；
    #   fact_type 固定 'user_fact'；source_turn 无对应列，返回 None。

    # facts_v2 行 → UserFact 兼容视图用的计算列（排序语义同旧 composite 降序）
    _FACT_COMPOSITE_SQL = (
        "ROUND(0.5 * confidence + 0.3 * importance + 0.2 * freshness, 4)"
    )

    async def upsert_fact(self, category: str, key: str, value: str,
                          confidence: float = 1.0, source_turn: Optional[int] = None,
                          importance: float = 0.5,
                          fact_type: str = "user_fact",
                          embedding: Optional[bytes] = None) -> int:
        # 适配器：转 upsert_fact_v2 语义（stability=0.5, freshness=1.0）。
        # fact_type / source_turn 在 facts_v2 无对应列，保留参数仅为兼容签名。
        logger.info(f"[db] upsert_fact: {category}/{key} confidence={confidence:.2f} imp={importance:.2f}")
        return await self.upsert_fact_v2(
            category, key, value, confidence=confidence, stability=0.5,
            freshness=1.0, importance=importance,
            created_by="consolidation", embedding=embedding)

    async def store_facts_bulk(self, facts: list[dict]) -> int:
        """#161: 单 cursor 单事务批量 upsert（末尾一次 commit）。
        Layer 1 完整上线：目标表改为 facts_v2，SQL 与 upsert_fact_v2 非
        embedding 分支一致（含 #217 复活语义 status='active'）。consolidation
        新提取的事实不带向量，embedding 由 _embed_new_items 统一回写。
        facts 元素键：category/key/value 必填，confidence/importance/fact_type/source_turn 可选
        （fact_type/source_turn 无对应列，忽略）。"""
        if not facts:
            return 0
        logger.info(f"[db] store_facts_bulk: {len(facts)} facts")
        async with self.db.cursor() as c:
            for f in facts:
                await c.execute("""
                    INSERT INTO facts_v2 (category, fact_key, fact_value, confidence, stability,
                                          freshness, importance, verification_count,
                                          last_verified_at, created_by, session_id)
                    VALUES (?, ?, ?, ?, 0.5, 1.0, ?, 1, CURRENT_TIMESTAMP, 'consolidation', ?)
                    ON CONFLICT(session_id, category, fact_key) DO UPDATE SET
                        fact_value = CASE WHEN excluded.confidence >= facts_v2.confidence
                                          THEN excluded.fact_value ELSE facts_v2.fact_value END,
                        confidence = MAX(facts_v2.confidence, excluded.confidence),
                        stability = MAX(facts_v2.stability, excluded.stability),
                        freshness = excluded.freshness,
                        importance = MAX(facts_v2.importance, excluded.importance),
                        status = 'active',
                        verification_count = facts_v2.verification_count + 1,
                        last_verified_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                """, (f["category"], f["key"], f["value"],
                      f.get("confidence", 1.0), f.get("importance", 0.5),
                      self.session_id))
            await self.db.commit()
            return len(facts)

    async def search_facts(self, query: str = "", limit: int = 30) -> list[UserFact]:
        logger.debug(f"[db] search_facts: query='{query[:40]}' limit={limit}")
        async with self.db.cursor() as c:
            if query:
                await c.execute(f"""
                    SELECT *, {self._FACT_COMPOSITE_SQL} AS composite_score FROM facts_v2
                    WHERE status = 'active'
                      AND confidence >= 0.2
                      AND session_id = ?
                      AND (fact_key LIKE ? OR fact_value LIKE ? OR category LIKE ?)
                    ORDER BY composite_score DESC, verification_count DESC
                    LIMIT ?
                """, (self.session_id, f"%{query}%", f"%{query}%", f"%{query}%", limit))
            else:
                await c.execute(f"""
                    SELECT *, {self._FACT_COMPOSITE_SQL} AS composite_score FROM facts_v2
                    WHERE status = 'active'
                      AND confidence >= 0.2
                      AND session_id = ?
                    ORDER BY composite_score DESC, verification_count DESC
                    LIMIT ?
                """, (self.session_id, limit))
            return [self._row_to_fact(r) for r in await c.fetchall()]

    async def get_active_facts(self, limit: int = 50) -> list[UserFact]:
        logger.debug(f"[db] get_active_facts: limit={limit}")
        async with self.db.cursor() as c:
            await c.execute(f"""
                SELECT *, {self._FACT_COMPOSITE_SQL} AS composite_score FROM facts_v2
                WHERE status = 'active'
                  AND confidence >= 0.2
                  AND session_id = ?
                ORDER BY composite_score DESC, verification_count DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_fact(r) for r in await c.fetchall()]

    async def update_fact_score(self, fact_id: int, score: float) -> None:
        """Layer 1 完整上线：facts_v2 无 composite_score 列。把目标分映射为
        相对当前 composite 的衰减系数走 decay_fact_v2（freshness/confidence
        等比缩放）——旧调用语义均为降级/衰减，比例映射最接近原语义。
        当前 composite 为 0 时无法按比例映射，直接跳过。"""
        logger.debug(f"[db] update_fact_score: id={fact_id} score={score:.2f}")
        fact = await self.get_fact_v2_by_id(fact_id)
        if fact is None:
            logger.warning(f"[db] update_fact_score id={fact_id}: no matching row in session "
                           f"'{self.session_id}' (missing or cross-session)")
            return
        current = 0.5 * fact.confidence + 0.3 * fact.importance + 0.2 * fact.freshness
        if current <= 0:
            return
        factor = max(0.0, min(1.0, score / current))
        await self.decay_fact_v2(fact_id, factor)

    async def increment_fact_recall(self, fact_id: int) -> None:
        """recall_count 映射为 facts_v2.verification_count，复用 verify_fact_v2。"""
        logger.debug(f"[db] increment_fact_recall: id={fact_id}")
        await self.verify_fact_v2(fact_id)

    async def deactivate_fact(self, fact_id: int) -> None:
        """Soft-delete a fact. Used when a fact is contradicted.
        Layer 1 完整上线：映射为 facts_v2 status='contradicted'（FactChecker
        软删语义；#217 复活由 upsert ON CONFLICT 的 status='active' 保证）。
        Session-scoped: an id belonging to another session is a no-op."""
        logger.info(f"[db] deactivate_fact id={fact_id}")
        await self.update_fact_v2_status(fact_id, "contradicted")

    async def update_fact_confidence(self, fact_id: int, new_confidence: float) -> None:
        """Lower a fact's confidence (unlike upsert which only takes MAX).
        facts_v2 的 composite 是读取时计算的，无需像旧表一样同步写回。
        Session-scoped like every other by-id write in this class."""
        logger.info(f"[db] update_fact_confidence id={fact_id} confidence={new_confidence:.2f}")
        async with self.db.cursor() as c:
            await c.execute(
                "UPDATE facts_v2 SET confidence = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND session_id = ?",
                (new_confidence, fact_id, self.session_id))
            if c.rowcount == 0:
                logger.warning(f"[db] update_fact_confidence id={fact_id}: no matching row in session "
                               f"'{self.session_id}' (missing or cross-session)")
            await self.db.commit()

    async def get_similar_facts(self, category: str, key: str, limit: int = 5) -> list[UserFact]:
        """Find facts with similar category or key for contradiction checking.
        Session-scoped like every other query in this class."""
        async with self.db.cursor() as c:
            await c.execute(f"""
                SELECT *, {self._FACT_COMPOSITE_SQL} AS composite_score FROM facts_v2
                WHERE status = 'active'
                  AND session_id = ?
                  AND (category = ? OR fact_key LIKE ?)
                ORDER BY composite_score DESC
                LIMIT ?
            """, (self.session_id, category, f"%{key}%", limit))
            return [self._row_to_fact(r) for r in await c.fetchall()]

    # ── Experiences ──

    async def insert_experience(self, summary: str, tone: str, significance: float,
                                tags: list[str], turn_start: Optional[int] = None,
                                turn_end: Optional[int] = None,
                                importance: float = 0.5,
                                embedding: Optional[bytes] = None) -> int:
        logger.info(f"[db] insert_exp: {summary[:60]} tone={tone} sig={significance:.2f} imp={importance:.2f}")
        async with self.db.cursor() as c:
            await c.execute(f"""
                INSERT INTO experiences (summary, emotional_tone, significance, importance, tags,
                                         turn_range_start, turn_range_end, embedding, embedding_version,
                                         session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, {EMBEDDING_VERSION}, ?)
            """, (summary, tone, significance, importance, json.dumps(tags, ensure_ascii=False),
                  turn_start, turn_end, embedding, self.session_id))
            await self.db.commit()
            return c.lastrowid

    async def search_experiences(self, keywords: list[str] | None = None,
                                 limit: int = 10) -> list[Experience]:
        logger.debug(f"[db] search_experiences: keywords={keywords} limit={limit}")
        async with self.db.cursor() as c:
            if keywords:
                conditions = " OR ".join("(summary LIKE ? OR tags LIKE ?)" for _ in keywords)
                params = []
                for kw in keywords:
                    params.extend([f"%{kw}%", f"%{kw}%"])
                await c.execute(f"""
                    SELECT * FROM experiences
                    WHERE is_archived = 0 AND session_id = ? AND ({conditions})
                    ORDER BY composite_score DESC, created_at DESC
                    LIMIT ?
                """, [self.session_id] + params + [limit])
            else:
                await c.execute("""
                    SELECT * FROM experiences
                    WHERE is_archived = 0 AND session_id = ?
                    ORDER BY composite_score DESC, created_at DESC
                    LIMIT ?
                """, (self.session_id, limit))
            return [self._row_to_experience(r) for r in await c.fetchall()]

    async def get_recent_experiences(self, limit: int = 5) -> list[Experience]:
        logger.debug(f"[db] get_recent_experiences: limit={limit}")
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM experiences
                WHERE is_archived = 0 AND session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_experience(r) for r in await c.fetchall()]

    async def update_experience_score(self, exp_id: int, score: float) -> None:
        logger.debug(f"[db] update_experience_score: id={exp_id} score={score:.2f}")
        async with self.db.cursor() as c:
            # M-01: 按 id 更新也要带 session 过滤，避免串改其他会话的行
            await c.execute(
                "UPDATE experiences SET composite_score = ? WHERE id = ? AND session_id = ?",
                (score, exp_id, self.session_id))
            await self.db.commit()

    # ── Reflections ──
    # Layer 1 二期（2026-07-20，schema v5）：以下方法保留旧签名与 Reflection
    # 返回形状（retrieval/long_term/tools/prompts 零改动），SQL 全部重定向到
    # insights_v2。旧表 reflections 已归档为 reflections_archive，不再读写。
    # Reflection 适配映射：
    #   content = hypothesis；significance = confidence；
    #   related_experience_ids = []（insights_v2 的 evidence 是 fact id，
    #   旧字段是 experience id，语义不同，不回填）；is_active = (status=='active')。

    async def insert_reflection(self, content: str, insight_type: str,
                                related_ids: list[int], significance: float,
                                embedding: Optional[bytes] = None) -> int:
        # 适配器：转 insert_insight 语义。related_ids（experience id）在
        # insights_v2 无对应列，保留参数仅为兼容签名。
        logger.info(f"[db] insert_ref: type={insight_type} sig={significance:.2f} content={content[:60]}")
        return await self.insert_insight(
            hypothesis=content, insight_type=insight_type,
            confidence=significance, created_by="consolidation",
            embedding=embedding)

    async def get_recent_reflections(self, limit: int = 5) -> list[Reflection]:
        logger.debug(f"[db] get_recent_reflections: limit={limit}")
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM insights_v2 WHERE status = 'active' AND session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_reflection(r) for r in await c.fetchall()]

    async def bulk_update_embeddings(self, table: str, updates: list[tuple[int, bytes]]):
        if not updates:
            return
        async with self.db.cursor() as c:
            # H-08: 按 session 隔离批量回写，避免串改其他会话的行
            await c.executemany(
                f"UPDATE {table} SET embedding = ?, embedding_version = {EMBEDDING_VERSION}"
                " WHERE id = ? AND session_id = ?",
                [(emb, rid, self.session_id) for rid, emb in updates],
            )
            # H-02: executemany 不会自动提交，显式 commit（与同文件其他写方法一致）
            await self.db.commit()
            logger.debug(f"[db] bulk_embed: updated {len(updates)} rows in {table}")

    # ── Observations (Layer 1 Memory lifecycle) ──

    async def insert_observation(self, content: str,
                                 source_turn: Optional[int] = None,
                                 episode_turn_start: Optional[int] = None,
                                 episode_turn_end: Optional[int] = None,
                                 created_by: str = "consolidation",
                                 embedding: Optional[bytes] = None) -> int:
        logger.info(f"[db] insert_observation: turn={source_turn} len={len(content)} by={created_by}")
        async with self.db.cursor() as c:
            await c.execute("""
                INSERT INTO observations (content, source_turn, episode_turn_start, episode_turn_end,
                                          created_by, session_id, embedding, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (content, source_turn, episode_turn_start, episode_turn_end,
                  created_by, self.session_id, embedding, EMBEDDING_VERSION if embedding else 0))
            await self.db.commit()
            return c.lastrowid

    async def search_observations(self, query: str = "", limit: int = 10) -> list[Observation]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM observations
                WHERE is_archived = 0 AND session_id = ?
                  AND (content LIKE ? OR ? = '')
                ORDER BY created_at DESC
                LIMIT ?
            """, (self.session_id, f"%{query}%", query, limit))
            return [self._row_to_observation(r) for r in await c.fetchall()]

    async def get_recent_observations(self, limit: int = 10, archived: bool = False) -> list[Observation]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM observations
                WHERE is_archived = ? AND session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (int(archived), self.session_id, limit))
            return [self._row_to_observation(r) for r in await c.fetchall()]

    async def archive_observation(self, obs_id: int) -> None:
        logger.info(f"[db] archive_observation: id={obs_id}")
        async with self.db.cursor() as c:
            # M-02: 按 id 归档也要带 session 过滤，避免串改其他会话的行
            await c.execute(
                "UPDATE observations SET is_archived = 1 WHERE id = ? AND session_id = ?",
                (obs_id, self.session_id)
            )
            await self.db.commit()

    # ── Facts v2 (Layer 1 Memory lifecycle) ──

    async def upsert_fact_v2(self, category: str, key: str, value: str,
                             confidence: float = 0.5, stability: float = 0.5,
                             freshness: float = 1.0, importance: float = 0.5,
                             source_observation_ids: Optional[list[int]] = None,
                             created_by: str = "consolidation",
                             embedding: Optional[bytes] = None) -> int:
        # #217: ON CONFLICT 里的 status='active' 即复活语义——被软删
        # （contradicted/decayed）的同名事实在用户重述时恢复可见。
        logger.info(f"[db] upsert_fact_v2: {category}/{key} confidence={confidence:.2f}")
        source_ids = json.dumps(source_observation_ids or [])
        async with self.db.cursor() as c:
            if embedding is not None:
                await c.execute(f"""
                    INSERT INTO facts_v2 (category, fact_key, fact_value, confidence, stability,
                                          freshness, importance, source_observation_ids,
                                          verification_count, last_verified_at, created_by,
                                          session_id, embedding, embedding_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?, ?, ?, {EMBEDDING_VERSION})
                    ON CONFLICT(session_id, category, fact_key) DO UPDATE SET
                        fact_value = CASE WHEN excluded.confidence >= facts_v2.confidence
                                          THEN excluded.fact_value ELSE facts_v2.fact_value END,
                        confidence = MAX(facts_v2.confidence, excluded.confidence),
                        stability = MAX(facts_v2.stability, excluded.stability),
                        freshness = excluded.freshness,
                        importance = MAX(facts_v2.importance, excluded.importance),
                        verification_count = facts_v2.verification_count + 1,
                        last_verified_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        embedding = excluded.embedding,
                        embedding_version = {EMBEDDING_VERSION},
                        status = 'active'
                """, (category, key, value, confidence, stability, freshness, importance,
                      source_ids, created_by, self.session_id, embedding))
            else:
                await c.execute("""
                    INSERT INTO facts_v2 (category, fact_key, fact_value, confidence, stability,
                                          freshness, importance, source_observation_ids,
                                          verification_count, last_verified_at, created_by,
                                          session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?, ?)
                    ON CONFLICT(session_id, category, fact_key) DO UPDATE SET
                        fact_value = CASE WHEN excluded.confidence >= facts_v2.confidence
                                          THEN excluded.fact_value ELSE facts_v2.fact_value END,
                        confidence = MAX(facts_v2.confidence, excluded.confidence),
                        stability = MAX(facts_v2.stability, excluded.stability),
                        freshness = excluded.freshness,
                        importance = MAX(facts_v2.importance, excluded.importance),
                        verification_count = facts_v2.verification_count + 1,
                        last_verified_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        status = 'active'
                """, (category, key, value, confidence, stability, freshness, importance,
                      source_ids, created_by, self.session_id))
            await self.db.commit()
            return c.lastrowid

    async def get_active_facts_v2(self, limit: int = 50) -> list[FactV2]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM facts_v2
                WHERE status = 'active' AND session_id = ?
                ORDER BY confidence * importance DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_fact_v2(r) for r in await c.fetchall()]

    async def get_fact_v2_by_id(self, fact_id: int) -> Optional[FactV2]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM facts_v2 WHERE id = ? AND session_id = ?
            """, (fact_id, self.session_id))
            row = await c.fetchone()
            return self._row_to_fact_v2(row) if row else None

    async def update_fact_v2_status(self, fact_id: int, status: str) -> None:
        logger.info(f"[db] update_fact_v2_status: id={fact_id} status={status}")
        async with self.db.cursor() as c:
            await c.execute(
                "UPDATE facts_v2 SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND session_id = ?",
                (status, fact_id, self.session_id)
            )
            if c.rowcount == 0:
                logger.warning(f"[db] update_fact_v2_status id={fact_id}: no matching row in session "
                               f"'{self.session_id}' (missing or cross-session)")
            await self.db.commit()

    async def verify_fact_v2(self, fact_id: int) -> None:
        logger.info(f"[db] verify_fact_v2: id={fact_id}")
        async with self.db.cursor() as c:
            await c.execute("""
                UPDATE facts_v2
                SET verification_count = verification_count + 1,
                    last_verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND session_id = ?
            """, (fact_id, self.session_id))
            if c.rowcount == 0:
                logger.warning(f"[db] verify_fact_v2 id={fact_id}: no matching row in session "
                               f"'{self.session_id}' (missing or cross-session)")
            await self.db.commit()

    async def decay_fact_v2(self, fact_id: int, decay_factor: float) -> None:
        logger.info(f"[db] decay_fact_v2: id={fact_id} factor={decay_factor:.2f}")
        async with self.db.cursor() as c:
            await c.execute("""
                UPDATE facts_v2
                SET freshness = MAX(0.0, freshness * ?),
                    confidence = MAX(0.0, confidence * ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND session_id = ?
            """, (decay_factor, decay_factor, fact_id, self.session_id))
            if c.rowcount == 0:
                logger.warning(f"[db] decay_fact_v2 id={fact_id}: no matching row in session "
                               f"'{self.session_id}' (missing or cross-session)")
            await self.db.commit()

    async def search_facts_v2(self, query: str = "", limit: int = 30) -> list[FactV2]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM facts_v2
                WHERE status = 'active' AND session_id = ?
                  AND (fact_key LIKE ? OR fact_value LIKE ? OR category LIKE ? OR ? = '')
                ORDER BY confidence * importance DESC
                LIMIT ?
            """, (self.session_id, f"%{query}%", f"%{query}%", f"%{query}%", query, limit))
            return [self._row_to_fact_v2(r) for r in await c.fetchall()]

    # ── Insights v2 (Layer 1 二期，2026-07-20) ──

    async def insert_insight(self, hypothesis: str,
                             evidence_fact_ids: Optional[list[int]] = None,
                             insight_type: Optional[str] = None,
                             confidence: float = 0.5,
                             needs_more_evidence: bool = True,
                             expires_at: Optional[str] = None,
                             created_by: str = "consolidation",
                             embedding: Optional[bytes] = None) -> int:
        logger.info(f"[db] insert_insight: type={insight_type} confidence={confidence:.2f} "
                    f"hypothesis={hypothesis[:60]}")
        async with self.db.cursor() as c:
            await c.execute(f"""
                INSERT INTO insights_v2 (hypothesis, evidence_fact_ids, insight_type,
                                         confidence, needs_more_evidence, expires_at,
                                         created_by, session_id, embedding, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hypothesis, json.dumps(evidence_fact_ids or []), insight_type,
                  confidence, int(needs_more_evidence), expires_at,
                  created_by, self.session_id, embedding,
                  EMBEDDING_VERSION if embedding else 0))
            await self.db.commit()
            return c.lastrowid

    async def search_insights(self, query: str = "", limit: int = 10) -> list[InsightV2]:
        """关键词检索 active insight（按 confidence 排序）。
        #251 的语义+关键词混合评分在 retrieval.search_reflections 层做，
        这里只提供基础的 LIKE 候选查询。"""
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM insights_v2
                WHERE status = 'active' AND session_id = ?
                  AND (hypothesis LIKE ? OR ? = '')
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
            """, (self.session_id, f"%{query}%", query, limit))
            return [self._row_to_insight(r) for r in await c.fetchall()]

    async def get_active_insights(self, limit: int = 10) -> list[InsightV2]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM insights_v2
                WHERE status = 'active' AND session_id = ?
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_insight(r) for r in await c.fetchall()]

    async def get_recent_insights(self, limit: int = 10) -> list[InsightV2]:
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT * FROM insights_v2
                WHERE status = 'active' AND session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (self.session_id, limit))
            return [self._row_to_insight(r) for r in await c.fetchall()]

    async def verify_insight(self, insight_id: int) -> None:
        """证据坐实：confidence +0.1（封顶 1.0）、needs_more_evidence=0、
        status='verified'。"""
        logger.info(f"[db] verify_insight: id={insight_id}")
        async with self.db.cursor() as c:
            await c.execute("""
                UPDATE insights_v2
                SET confidence = MIN(1.0, confidence + 0.1),
                    needs_more_evidence = 0,
                    status = 'verified',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND session_id = ?
            """, (insight_id, self.session_id))
            if c.rowcount == 0:
                logger.warning(f"[db] verify_insight id={insight_id}: no matching row in session "
                               f"'{self.session_id}' (missing or cross-session)")
            await self.db.commit()

    async def expire_insight(self, insight_id: int) -> None:
        logger.info(f"[db] expire_insight: id={insight_id}")
        await self.update_insight_status(insight_id, "expired")

    async def update_insight_status(self, insight_id: int, status: str) -> None:
        logger.info(f"[db] update_insight_status: id={insight_id} status={status}")
        async with self.db.cursor() as c:
            await c.execute(
                "UPDATE insights_v2 SET status = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE id = ? AND session_id = ?",
                (status, insight_id, self.session_id)
            )
            if c.rowcount == 0:
                logger.warning(f"[db] update_insight_status id={insight_id}: no matching row in session "
                               f"'{self.session_id}' (missing or cross-session)")
            await self.db.commit()

    async def expire_due_insights(self) -> int:
        """GC：expires_at 已过的 active insight 置为 expired。返回过期条数。"""
        async with self.db.cursor() as c:
            await c.execute("""
                UPDATE insights_v2
                SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'active' AND session_id = ?
                  AND expires_at IS NOT NULL AND expires_at < datetime('now')
            """, (self.session_id,))
            await self.db.commit()
            if c.rowcount:
                logger.info(f"[db] expire_due_insights: expired {c.rowcount} rows")
            return c.rowcount

    # ── Relationship ──

    async def get_all_relationships(self) -> dict[str, float]:
        logger.debug(f"[db] get_relationships: session={self.session_id}")
        async with self.db.cursor() as c:
            await c.execute("SELECT dimension, value FROM relationship_metrics WHERE session_id = ?", (self.session_id,))
            return {r["dimension"]: r["value"] for r in await c.fetchall()}

    async def ensure_relationship_defaults(self) -> None:
        """Seed the four base relationship dimensions for the current session."""
        async with self.db.cursor() as c:
            await c.execute("SELECT dimension FROM relationship_metrics WHERE session_id = ?", (self.session_id,))
            existing = {r["dimension"] for r in await c.fetchall()}
            added = []
            for dim in ("trust", "familiarity", "intimacy", "playfulness"):
                if dim not in existing:
                    await c.execute("""
                        INSERT INTO relationship_metrics (dimension, value, updated_at, session_id)
                        VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                    """, (dim, 0.3, self.session_id))
                    added.append(dim)
            await self.db.commit()
            if added:
                logger.info(f"[db] seeded relationship defaults: {added} session={self.session_id}")

    async def upsert_relationship(self, dimension: str, value: float) -> None:
        logger.info(f"[db] upsert_rel: {dimension}={value:.2f}")
        async with self.db.cursor() as c:
            await c.execute("""
                INSERT INTO relationship_metrics (dimension, value, updated_at, session_id)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(session_id, dimension) DO UPDATE SET
                    value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """, (dimension, value, self.session_id))
            # #132: insert snapshot for time-series tracking
            await c.execute("""
                INSERT INTO relationship_snapshots (dimension, value, session_id)
                VALUES (?, ?, ?)
            """, (dimension, value, self.session_id))
            await self.db.commit()

    async def get_relationship_history(self, days: int = 30) -> list[dict]:
        """Get relationship metric time-series for the last N days. (#132)"""
        logger.debug(f"[db] get_relationship_history: session={self.session_id} days={days}")
        async with self.db.cursor() as c:
            await c.execute("""
                SELECT dimension, value, created_at
                FROM relationship_snapshots
                WHERE session_id = ? AND created_at >= datetime('now', ?)
                ORDER BY created_at ASC
            """, (self.session_id, f'-{days} days'))
            rows = await c.fetchall()
            logger.debug(f"[db] relationship_history: {len(rows)} rows")
            return [{"dimension": r["dimension"], "value": r["value"],
                     "created_at": r["created_at"]} for r in rows]

    # ── Session/Role mapping ──

    async def set_session_role(self, session_id: str, role_id: str) -> None:
        logger.info(f"[db] set_session_role: session={session_id} role={role_id}")
        async with self.db.cursor() as c:
            await c.execute("""
                INSERT INTO session_roles (session_id, role_id) VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET role_id = excluded.role_id
            """, (session_id, role_id))
            await self.db.commit()

    async def get_role_for_session(self, session_id: str) -> str | None:
        logger.debug(f"[db] get_role_for_session: session={session_id}")
        async with self.db.cursor() as c:
            await c.execute("SELECT role_id FROM session_roles WHERE session_id = ?", (session_id,))
            row = await c.fetchone()
            role = row["role_id"] if row else None
            logger.debug(f"[db] role_for_session: session={session_id} role={role}")
            return role

    async def get_sessions_by_role(self, role_id: str) -> list[str]:
        """一个角色只对应一个 session，session_id 即 role_id。"""
        logger.debug(f"[db] get_sessions_by_role: role={role_id}")
        return [role_id]

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

    async def get_max_turn_number(self, session_id: str | None = None) -> int:
        """Return the largest turn_number persisted for this session."""
        async with self.db.cursor() as c:
            sid = session_id or self.session_id
            await c.execute("""
                SELECT COALESCE(MAX(turn_number), 0) FROM conversation_turns
                WHERE session_id = ?
            """, (sid,))
            row = await c.fetchone()
            return row[0] if row else 0

    # ── Pruning ──

    async def prune_facts(self, max_count: int) -> int:
        # Layer 1 完整上线：COUNT 与溢出降级都改打 facts_v2。溢出行的
        # composite_score × 0.1 降级映射为 decay_fact_v2(id, 0.1) 语义
        # （freshness/confidence × 0.1），单条 UPDATE 一次完成，避免逐条 commit。
        async with self.db.cursor() as c:
            await c.execute("SELECT COUNT(*) FROM facts_v2 WHERE status = 'active' AND session_id = ?", (self.session_id,))
            row = await c.fetchone()
            count = row[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            logger.info(f"[db] prune_facts: degrading {excess} of {count}")
            await c.execute("""
                UPDATE facts_v2
                SET freshness = MAX(0.0, freshness * 0.1),
                    confidence = MAX(0.0, confidence * 0.1),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT id FROM facts_v2 WHERE status = 'active' AND session_id = ?
                    ORDER BY (0.5 * confidence + 0.3 * importance + 0.2 * freshness) ASC,
                             verification_count ASC
                    LIMIT ?
                )
            """, (self.session_id, excess))
            await self.db.commit()
            return c.rowcount

    async def prune_experiences(self, max_count: int) -> int:
        async with self.db.cursor() as c:
            await c.execute("SELECT COUNT(*) FROM experiences WHERE is_archived = 0 AND session_id = ?", (self.session_id,))
            row = await c.fetchone()
            count = row[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            logger.info(f"[db] prune_exps: pruning {excess} of {count}")
            await c.execute("""
                UPDATE experiences SET is_archived = 1
                WHERE id IN (
                    SELECT id FROM experiences WHERE is_archived = 0 AND session_id = ?
                    ORDER BY composite_score ASC, created_at ASC
                    LIMIT ?
                )
            """, (self.session_id, excess))
            await self.db.commit()
            return c.rowcount

    async def prune_reflections(self, max_count: int) -> int:
        # Layer 1 二期（2026-07-20）：目标表改为 insights_v2。旧「软删
        # is_active=0」语义映射为 status='expired'；溢出按 confidence 升序
        # （旧 significance 升序的对应列）。
        async with self.db.cursor() as c:
            await c.execute("SELECT COUNT(*) FROM insights_v2 WHERE status = 'active' AND session_id = ?", (self.session_id,))
            row = await c.fetchone()
            count = row[0]
            if count <= max_count:
                return 0
            excess = count - max_count
            logger.info(f"[db] prune_insights: expiring {excess} of {count}")
            await c.execute("""
                UPDATE insights_v2 SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT id FROM insights_v2 WHERE status = 'active' AND session_id = ?
                    ORDER BY confidence ASC, created_at ASC
                    LIMIT ?
                )
            """, (self.session_id, excess))
            await self.db.commit()
            return c.rowcount

    # ── Helpers ──

    def _row_to_fact(self, r) -> UserFact:
        """facts_v2 行 → UserFact 适配（Layer 1 完整上线）。调用方查询需带
        _FACT_COMPOSITE_SQL 计算的 composite_score 列；缺失时按公式现算。"""
        keys = r.keys()
        if "composite_score" in keys and r["composite_score"] is not None:
            composite = r["composite_score"]
        else:
            composite = round(0.5 * r["confidence"] + 0.3 * r["importance"]
                              + 0.2 * r["freshness"], 4)
        return UserFact(
            id=r["id"], category=r["category"], fact_key=r["fact_key"],
            fact_value=r["fact_value"],
            fact_type="user_fact",
            confidence=r["confidence"],
            importance=r["importance"],
            source_turn=None,
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            recall_count=r["verification_count"],
            is_active=(r["status"] == "active"),
            composite_score=composite,
            embedding=r["embedding"] if "embedding" in keys else None,
            embedding_version=r["embedding_version"] if "embedding_version" in keys else 0,
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
            embedding=r["embedding"] if "embedding" in r.keys() else None,
            embedding_version=r["embedding_version"] if "embedding_version" in r.keys() else 0,
        )

    def _row_to_reflection(self, r) -> Reflection:
        """insights_v2 行 → Reflection 适配（Layer 1 二期，2026-07-20）。
        content=hypothesis、significance=confidence；related_experience_ids
        无对应列（evidence 是 fact id 而非 experience id），返回空列表。"""
        return Reflection(
            id=r["id"], content=r["hypothesis"], insight_type=r["insight_type"],
            related_experience_ids=[],
            significance=r["confidence"], created_at=r["created_at"],
            embedding=r["embedding"] if "embedding" in r.keys() else None,
            embedding_version=r["embedding_version"] if "embedding_version" in r.keys() else 0,
        )

    def _row_to_insight(self, r) -> InsightV2:
        return InsightV2(
            id=r["id"], hypothesis=r["hypothesis"],
            evidence_fact_ids=json.loads(r["evidence_fact_ids"])
            if r["evidence_fact_ids"] else [],
            insight_type=r["insight_type"], confidence=r["confidence"],
            needs_more_evidence=bool(r["needs_more_evidence"]),
            expires_at=r["expires_at"], status=r["status"],
            created_by=r["created_by"], created_at=r["created_at"],
            updated_at=r["updated_at"], session_id=r["session_id"],
            embedding=r["embedding"] if "embedding" in r.keys() else None,
            embedding_version=r["embedding_version"] if "embedding_version" in r.keys() else 0,
        )

    def _row_to_observation(self, r) -> Observation:
        return Observation(
            id=r["id"], content=r["content"],
            episode_turn_start=r["episode_turn_start"],
            episode_turn_end=r["episode_turn_end"],
            source_turn=r["source_turn"],
            created_by=r["created_by"], created_at=r["created_at"],
            session_id=r["session_id"], embedding=r["embedding"],
            embedding_version=r["embedding_version"], is_archived=bool(r["is_archived"]),
        )

    def _row_to_fact_v2(self, r) -> FactV2:
        return FactV2(
            id=r["id"], category=r["category"], fact_key=r["fact_key"],
            fact_value=r["fact_value"], confidence=r["confidence"],
            stability=r["stability"], freshness=r["freshness"],
            importance=r["importance"], status=r["status"],
            source_observation_ids=json.loads(r["source_observation_ids"])
            if r["source_observation_ids"] else [],
            verification_count=r["verification_count"],
            last_verified_at=r["last_verified_at"],
            created_by=r["created_by"], created_at=r["created_at"],
            updated_at=r["updated_at"], session_id=r["session_id"],
            embedding=r["embedding"], embedding_version=r["embedding_version"],
        )
