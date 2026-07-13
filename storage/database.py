import asyncio
import logging
import os
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger(__name__)

# DB-001: whitelist of allowable table/column alterations — prevents SQL injection in DDL
ALLOWED_ALTERATIONS = {
    ("user_facts", "importance"),
    ("experiences", "importance"),
    ("reflections", "is_active"),
    ("user_facts", "embedding"),
    ("user_facts", "embedding_version"),
    ("experiences", "embedding"),
    ("experiences", "embedding_version"),
    ("reflections", "embedding"),
    ("reflections", "embedding_version"),
    ("user_facts", "fact_type"),
    ("conversation_turns", "is_tool_claim"),
    ("user_facts", "session_id"),
    ("experiences", "session_id"),
    ("reflections", "session_id"),
    ("conversation_turns", "session_id"),
    ("relationship_metrics", "session_id"),
    ("relationship_snapshots", "session_id"),
}


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock_init: asyncio.Lock | None = None
        self._lock_loop_id: int = 0
        self.conn: aiosqlite.Connection | None = None

    async def _get_lock(self) -> asyncio.Lock:
        """Return an asyncio.Lock bound to the current event loop."""
        current_loop_id = id(asyncio.get_running_loop())
        if self._lock_init is None or self._lock_loop_id != current_loop_id:
            self._lock_init = asyncio.Lock()
            self._lock_loop_id = current_loop_id
        return self._lock_init

    async def open(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA wal_autocheckpoint=1000")  # #247: auto-checkpoint every 1000 pages
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")  # #154
        await self.initialize()
        try:
            result = await self.conn.execute("PRAGMA integrity_check")
            row = await result.fetchone()
            if row and row[0] != "ok":
                logger.warning(f"[db] integrity check failed: {row[0]}")
        except Exception as e:
            logger.warning(f"[db] integrity check error: {e}")
        logger.info(f"[db] opened: {self.db_path}")

    @asynccontextmanager
    async def cursor(self):
        if self.conn is None:
            raise RuntimeError("Database not opened. Call await db.open() first.")
        lock = await self._get_lock()
        async with lock:
            c = await self.conn.cursor()
            try:
                yield c
            except aiosqlite.Error:
                await self.conn.rollback()
                raise
            finally:
                await c.close()

    async def commit(self) -> None:
        """Explicit commit for write operations. (#142)"""
        if self.conn:
            await self.conn.commit()

    def get_connection(self):
        """Return connection for direct use (bulk operations). Caller must manage locking."""
        logger.warning("[db] get_connection() is deprecated — use cursor() instead")
        if self.conn is None:
            raise RuntimeError("Database not opened.")
        return self.conn

    async def initialize(self) -> None:
        async with self.cursor() as c:
            await c.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    importance REAL DEFAULT 0.5,
                    source_turn INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    recall_count INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    composite_score REAL DEFAULT 1.0,
                    UNIQUE(category, fact_key)
                );

                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary TEXT NOT NULL,
                    emotional_tone TEXT,
                    significance REAL DEFAULT 0.5,
                    importance REAL DEFAULT 0.5,
                    tags TEXT DEFAULT '[]',
                    turn_range_start INTEGER,
                    turn_range_end INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    recall_count INTEGER DEFAULT 0,
                    is_archived INTEGER DEFAULT 0,
                    composite_score REAL DEFAULT 0.5
                );

                CREATE TABLE IF NOT EXISTS reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    insight_type TEXT,
                    related_experience_ids TEXT DEFAULT '[]',
                    significance REAL DEFAULT 0.5,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS relationship_metrics (
                    dimension TEXT NOT NULL,
                    value REAL DEFAULT 0.3,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT DEFAULT 'default',
                    PRIMARY KEY (session_id, dimension)
                );

                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_number INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    emotional_state TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT DEFAULT 'default'
                );

                INSERT OR IGNORE INTO relationship_metrics (dimension, value, session_id) VALUES
                    ('trust', 0.3, 'default'),
                    ('familiarity', 0.3, 'default'),
                    ('intimacy', 0.3, 'default'),
                    ('playfulness', 0.3, 'default');

                CREATE TABLE IF NOT EXISTS relationship_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dimension TEXT NOT NULL,
                    value REAL DEFAULT 0.3,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT DEFAULT 'default'
                );

                CREATE TABLE IF NOT EXISTS session_roles (
                    session_id TEXT PRIMARY KEY,
                    role_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # #215: read current schema version to skip already-applied migrations
            await c.execute("SELECT MAX(version) FROM schema_version")
            row = await c.fetchone()
            current_version = row[0] if row and row[0] else 0
            logger.info(f"[db] schema version: {current_version}")

            alterations = [
                ("user_facts", "importance", "REAL", "0.5"),
                ("experiences", "importance", "REAL", "0.5"),
                ("reflections", "is_active", "INTEGER", "1"),
                ("user_facts", "embedding", "BLOB", "NULL"),
                ("user_facts", "embedding_version", "INTEGER", "0"),
                ("experiences", "embedding", "BLOB", "NULL"),
                ("experiences", "embedding_version", "INTEGER", "0"),
                ("reflections", "embedding", "BLOB", "NULL"),
                ("reflections", "embedding_version", "INTEGER", "0"),
                ("user_facts", "fact_type", "TEXT", "'user_fact'"),   # #127
                ("conversation_turns", "is_tool_claim", "INTEGER", "0"),  # #130
                ("user_facts", "session_id", "TEXT", "'default'"),          # #40
                ("experiences", "session_id", "TEXT", "'default'"),         # #40
                ("reflections", "session_id", "TEXT", "'default'"),         # #40
                ("conversation_turns", "session_id", "TEXT", "'default'"),  # #40
                ("relationship_metrics", "session_id", "TEXT", "'default'"),# #40
                ("relationship_snapshots", "session_id", "TEXT", "'default'"),# #132
            ]
            for table, column, col_type, default_val in alterations:
                # #215: whitelist validation — reject unknown alterations
                if (table, column) not in ALLOWED_ALTERATIONS:
                    raise ValueError(f"Unauthorized schema alteration: {table}.{column}")
                await c.execute(f"PRAGMA table_info({table})")
                rows = await c.fetchall()
                columns = [row[1] for row in rows]
                if column not in columns:
                    await c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default_val}")
                    logger.info(f"Schema migration: added {table}.{column}")

            # #RM-001: migrate relationship_metrics from the old single-column
            # primary key (dimension) to composite (session_id, dimension).
            await c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='relationship_metrics'")
            row = await c.fetchone()
            metrics_sql = row[0] if row else ""
            if metrics_sql and "dimension TEXT PRIMARY KEY" in metrics_sql:
                logger.warning("[db] migrating relationship_metrics to composite PK (session_id, dimension)")
                await c.executescript("""
                    ALTER TABLE relationship_metrics RENAME TO _old_relationship_metrics;
                    CREATE TABLE relationship_metrics (
                        dimension TEXT NOT NULL,
                        value REAL DEFAULT 0.3,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        session_id TEXT DEFAULT 'default',
                        PRIMARY KEY (session_id, dimension)
                    );
                    INSERT INTO relationship_metrics (dimension, value, updated_at, session_id)
                        SELECT dimension, value, updated_at, COALESCE(session_id, 'default')
                        FROM _old_relationship_metrics;
                    DROP TABLE _old_relationship_metrics;
                """)

            # #SR-001: one-time migration — map the pre-existing default session
            # to the role name found in the legacy personality.json.
            await c.execute("SELECT COUNT(*) FROM session_roles")
            if (await c.fetchone())[0] == 0:
                legacy_role = "default"
                try:
                    import json, os
                    if os.path.exists("personality.json"):
                        with open("personality.json", encoding="utf-8") as f:
                            legacy_role = json.load(f).get("personality", {}).get("name", "default") or "default"
                except Exception:
                    pass
                await c.execute(
                    "INSERT OR IGNORE INTO session_roles (session_id, role_id) VALUES (?, ?)",
                    ("default", legacy_role),
                )
                logger.info(f"[db] migrated default session to role={legacy_role}")

            # #SR-002: enforce one role = one session. For each role, keep the
            # old session with the most conversation turns as the canonical data
            # and move it to session_id = role_id; discard data from stale sessions.
            async def _move_session_data(old_sid: str, rid: str) -> None:
                tables = [
                    "user_facts", "experiences", "reflections",
                    "conversation_turns", "relationship_snapshots",
                ]
                for table in tables:
                    await c.execute(f"UPDATE {table} SET session_id = ? WHERE session_id = ?", (rid, old_sid))
                # relationship_metrics has a composite PK (session_id, dimension);
                # delete any pre-existing target rows before merging to avoid conflict.
                await c.execute("DELETE FROM relationship_metrics WHERE session_id = ?", (rid,))
                await c.execute("UPDATE relationship_metrics SET session_id = ? WHERE session_id = ?", (rid, old_sid))

            await c.execute("SELECT session_id, role_id FROM session_roles WHERE session_id != role_id")
            rows = await c.fetchall()
            from collections import defaultdict
            by_role: dict[str, list[str]] = defaultdict(list)
            for old_sid, rid in rows:
                by_role[rid].append(old_sid)

            for rid, old_sids in by_role.items():
                # Prefer an old session whose id already equals the role id.
                if rid in old_sids:
                    canonical = rid
                    others = [s for s in old_sids if s != rid]
                else:
                    counts = {}
                    for s in old_sids:
                        await c.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id = ?", (s,))
                        counts[s] = (await c.fetchone())[0]
                    canonical = max(counts, key=counts.get)
                    others = [s for s in old_sids if s != canonical]

                logger.warning(f"[db] merging canonical session {canonical} into role session {rid}")
                await _move_session_data(canonical, rid)
                # Update or insert the canonical session_roles row.
                await c.execute("SELECT 1 FROM session_roles WHERE session_id = ?", (rid,))
                if await c.fetchone():
                    await c.execute("DELETE FROM session_roles WHERE session_id = ?", (canonical,))
                else:
                    await c.execute(
                        "UPDATE session_roles SET session_id = ? WHERE session_id = ?",
                        (rid, canonical),
                    )
                # Drop stale sessions for the same role.
                for stale in others:
                    logger.warning(f"[db] dropping stale session {stale} for role {rid}")
                    for table in ["user_facts", "experiences", "reflections", "conversation_turns", "relationship_snapshots"]:
                        await c.execute(f"DELETE FROM {table} WHERE session_id = ?", (stale,))
                    await c.execute("DELETE FROM relationship_metrics WHERE session_id = ?", (stale,))
                    await c.execute("DELETE FROM session_roles WHERE session_id = ?", (stale,))

            # S-006: schema_version table existed but was never populated, so it
            # couldn't tell future migrations what state the DB was in. Stamp the
            # current schema version (1 = baseline with session_id columns) so
            # subsequent initialize() runs can detect/version-gate new migrations.
            await c.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (1)"
            )

            # #157: create indexes for frequently-queried columns
            await c.executescript("""
                CREATE INDEX IF NOT EXISTS idx_user_facts_session ON user_facts(session_id, is_active, composite_score);
                CREATE INDEX IF NOT EXISTS idx_experiences_session ON experiences(session_id, is_archived, composite_score);
                CREATE INDEX IF NOT EXISTS idx_reflections_session ON reflections(session_id, is_active);
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_session ON conversation_turns(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_relationship_session ON relationship_metrics(session_id);
                CREATE INDEX IF NOT EXISTS idx_relationship_snapshots_session ON relationship_snapshots(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_session_roles_role ON session_roles(role_id, created_at);
            """)
            logger.info("[db] indexes created/verified")
        await self.commit()

    async def prune_old_turns(self, keep_max: int = 1000) -> int:
        """Delete oldest conversation turns beyond keep_max per session. (#178)"""
        async with self.cursor() as c:
            await c.execute("""
                DELETE FROM conversation_turns WHERE id IN (
                    SELECT id FROM conversation_turns
                    WHERE id NOT IN (
                        SELECT id FROM conversation_turns
                        ORDER BY id DESC LIMIT ?
                    )
                )
            """, (keep_max,))
            deleted = c.rowcount
            if deleted:
                await self.commit()
                logger.info(f"[db] pruned {deleted} old conversation turns")
            return deleted

    async def close(self) -> None:
        if self.conn:
            try:
                await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            logger.info(f"[db] closed: {self.db_path}")
            await self.conn.close()
            self.conn = None
