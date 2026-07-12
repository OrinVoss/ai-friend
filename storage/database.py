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
            await self.conn.execute("PRAGMA integrity_check")
        except Exception as e:
            logger.warning(f"[db] integrity check failed: {e}")
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
                    dimension TEXT PRIMARY KEY,
                    value REAL DEFAULT 0.3,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_number INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    emotional_state TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                INSERT OR IGNORE INTO relationship_metrics (dimension, value) VALUES
                    ('trust', 0.3),
                    ('familiarity', 0.3),
                    ('intimacy', 0.3),
                    ('playfulness', 0.3);

                CREATE TABLE IF NOT EXISTS relationship_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dimension TEXT NOT NULL,
                    value REAL DEFAULT 0.3,
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

            # S-006: schema_version table existed but was never populated, so it
            # couldn't tell future migrations what state the DB was in. Stamp the
            # current schema version (1 = baseline with session_id columns) so
            # subsequent initialize() runs can detect/version-gate new migrations.
            await c.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (1)"
            )
        await self.commit()

    async def close(self) -> None:
        if self.conn:
            try:
                await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            logger.info(f"[db] closed: {self.db_path}")
            await self.conn.close()
            self.conn = None
