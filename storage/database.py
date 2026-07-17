import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime

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
    # Current schema target; bump when adding migrations. initialize() stamps
    # it into schema_version, and open() uses it to decide whether a
    # pre-migration backup is needed (version behind => migrations will run).
    # v2: observations / facts_v2 (ML-001). v3: user_facts session-scoped
    # UNIQUE(session_id, category, fact_key) (#UK-001).
    CURRENT_SCHEMA_VERSION = 3

    def __init__(self, db_path: str, backup_enabled: bool = True, backup_keep: int = 5):
        self.db_path = db_path
        self.backup_enabled = backup_enabled
        self.backup_keep = backup_keep
        # H-03: 单个进程级 threading.Lock。run_async 每次调用都新建事件循环，
        # 按 loop id 缓存的 asyncio.Lock 会被反复重建，4 个 worker 线程间零互斥。
        self._lock = threading.Lock()
        self.conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        # Check for a pre-existing non-empty file BEFORE connect — aiosqlite
        # creates the file on connect, which would make a fresh database look
        # like an existing one worth backing up.
        pre_existing = (os.path.exists(self.db_path)
                        and os.path.getsize(self.db_path) > 0)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA wal_autocheckpoint=1000")  # #247: auto-checkpoint every 1000 pages
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")  # #154
        await self._backup_before_migration(pre_existing)
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
        # H-03: threading.Lock 跨 await 持有，保证 execute..commit 序列在
        # run_async 的 4 个 worker 线程间互斥。约束：同一事件循环内禁止两个
        # 协程并发进入 cursor()（阻塞 acquire 会卡住整个 loop）；并发访问请
        # 走 run_async 桥接（每协程独占 worker 线程跑到底，阻塞的是自己的线程）。
        self._lock.acquire()
        try:
            c = await self.conn.cursor()
            try:
                yield c
            except aiosqlite.Error:
                # 注意：rollback 作用于共享连接，任何绕过本锁直接操作连接的
                # 未提交写入也会被一并回滚
                await self.conn.rollback()
                raise
            finally:
                await c.close()
        finally:
            self._lock.release()

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
                    fact_type TEXT DEFAULT 'user_fact',
                    embedding BLOB,
                    embedding_version INTEGER DEFAULT 0,
                    session_id TEXT DEFAULT 'default',
                    UNIQUE(session_id, category, fact_key)
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

                -- Layer 1 Memory lifecycle: raw observations (#ML-001)
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    episode_turn_start INTEGER,
                    episode_turn_end INTEGER,
                    source_turn INTEGER,
                    created_by TEXT NOT NULL DEFAULT 'consolidation',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    embedding BLOB,
                    embedding_version INTEGER DEFAULT 0,
                    is_archived INTEGER DEFAULT 0
                );

                -- Layer 1 Memory lifecycle: verified facts (#ML-001)
                CREATE TABLE IF NOT EXISTS facts_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    stability REAL DEFAULT 0.5,
                    freshness REAL DEFAULT 1.0,
                    importance REAL DEFAULT 0.5,
                    status TEXT DEFAULT 'active',
                    source_observation_ids TEXT DEFAULT '[]',
                    verification_count INTEGER DEFAULT 0,
                    last_verified_at TIMESTAMP,
                    created_by TEXT NOT NULL DEFAULT 'consolidation',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    embedding BLOB,
                    embedding_version INTEGER DEFAULT 0,
                    UNIQUE(session_id, category, fact_key)
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

            # #UK-001: migrate user_facts UNIQUE constraint from global
            # (category, fact_key) to session-scoped (session_id, category,
            # fact_key). The old constraint made two sessions sharing a key
            # overwrite each other's row via ON CONFLICT. SQLite cannot alter
            # constraints, so the table is rebuilt; existing data cannot hold
            # cross-session duplicates (the old constraint forbade them), so
            # the copy is always safe.
            await c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='user_facts'")
            row = await c.fetchone()
            facts_sql = row[0] if row else ""
            if facts_sql and "UNIQUE(category, fact_key)" in facts_sql:
                logger.warning("[db] migrating user_facts to UNIQUE(session_id, category, fact_key)")
                await c.executescript("""
                    ALTER TABLE user_facts RENAME TO _old_user_facts;
                    CREATE TABLE user_facts (
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
                        fact_type TEXT DEFAULT 'user_fact',
                        embedding BLOB,
                        embedding_version INTEGER DEFAULT 0,
                        session_id TEXT DEFAULT 'default',
                        UNIQUE(session_id, category, fact_key)
                    );
                    INSERT INTO user_facts (id, category, fact_key, fact_value,
                                            confidence, importance, source_turn,
                                            created_at, updated_at, recall_count,
                                            is_active, composite_score, fact_type,
                                            embedding, embedding_version, session_id)
                        SELECT id, category, fact_key, fact_value,
                               confidence, importance, source_turn,
                               created_at, updated_at, recall_count,
                               is_active, composite_score, fact_type,
                               embedding, embedding_version,
                               COALESCE(session_id, 'default')
                        FROM _old_user_facts;
                    DROP TABLE _old_user_facts;
                """)

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
            # current schema version so subsequent initialize() runs can detect/
            # version-gate new migrations.
            # ML-001: version 2 adds observations / facts_v2 tables.
            if current_version < self.CURRENT_SCHEMA_VERSION:
                await c.execute(
                    "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                    (self.CURRENT_SCHEMA_VERSION,),
                )
                logger.info(f"[db] schema migrated from {current_version} to {self.CURRENT_SCHEMA_VERSION}")

            # #157: create indexes for frequently-queried columns
            await c.executescript("""
                CREATE INDEX IF NOT EXISTS idx_user_facts_session ON user_facts(session_id, is_active, composite_score);
                CREATE INDEX IF NOT EXISTS idx_experiences_session ON experiences(session_id, is_archived, composite_score);
                CREATE INDEX IF NOT EXISTS idx_reflections_session ON reflections(session_id, is_active);
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_session ON conversation_turns(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_relationship_session ON relationship_metrics(session_id);
                CREATE INDEX IF NOT EXISTS idx_relationship_snapshots_session ON relationship_snapshots(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_session_roles_role ON session_roles(role_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id, is_archived, created_at);
                CREATE INDEX IF NOT EXISTS idx_facts_v2_session ON facts_v2(session_id, status, confidence);
            """)
            logger.info("[db] indexes created/verified")
        await self.commit()

    async def prune_old_turns(self, keep_max: int = 1000,
                              session_id: str | None = None) -> int:
        """Delete oldest conversation turns beyond keep_max per session. (#178)

        M-03: 实现与 docstring 对齐 — 每个 session 各保留最新 keep_max 条，
        活跃角色不再挤掉其他角色的记录；传入 session_id 时只修剪该 session。
        （当前零调用方，session_id 为新增可选参数，旧调用方式仍兼容。）
        """
        async with self.cursor() as c:
            if session_id is not None:
                await c.execute("""
                    DELETE FROM conversation_turns
                    WHERE session_id = ? AND id NOT IN (
                        SELECT id FROM conversation_turns
                        WHERE session_id = ?
                        ORDER BY id DESC LIMIT ?
                    )
                """, (session_id, session_id, keep_max))
            else:
                await c.execute("""
                    DELETE FROM conversation_turns WHERE id IN (
                        SELECT id FROM (
                            SELECT id, ROW_NUMBER() OVER (
                                PARTITION BY session_id ORDER BY id DESC
                            ) AS rn
                            FROM conversation_turns
                        ) WHERE rn > ?
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

    # ── Backup (P0-3: snapshot before destructive migrations) ──

    async def _backup_before_migration(self, pre_existing: bool) -> None:
        """Snapshot the DB before initialize() applies schema migrations.

        A backup is taken only when all of these hold:
        - backups are enabled and this is a file-backed database
        - `pre_existing`: the file existed and was non-empty before connect
          (a fresh DB has nothing to lose)
        - schema_version is behind CURRENT_SCHEMA_VERSION, meaning
          initialize() is about to run migrations — some of which (#SR-002)
          are destructive. Up-to-date databases open without a backup.
        """
        if not self.backup_enabled or self.db_path == ":memory:":
            return
        if not pre_existing:
            return
        version = 0
        try:
            async with self.cursor() as c:
                await c.execute("SELECT MAX(version) FROM schema_version")
                row = await c.fetchone()
                version = row[0] if row and row[0] else 0
        except aiosqlite.Error:
            version = 0  # pre-schema_version database — migrations will run
        if version >= self.CURRENT_SCHEMA_VERSION:
            return
        await self.backup()

    async def backup(self) -> str | None:
        """Create a consistent snapshot in <db_dir>/backups/ via VACUUM INTO.

        VACUUM INTO yields a self-contained, compacted copy, so the snapshot
        doubles as space reclamation. Keeps the newest `backup_keep` files.
        Returns the backup path, or None when skipped/failed.
        """
        if self.conn is None or self.db_path == ":memory:":
            return None
        db_dir = os.path.dirname(self.db_path) or "."
        backups_dir = os.path.join(db_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(self.db_path))[0]
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = os.path.join(backups_dir, f"{stem}.{ts}.db")
        # Same-second collision guard (e.g. rapid successive opens in tests)
        n = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(backups_dir, f"{stem}.{ts}-{n}.db")
            n += 1
        try:
            await self.commit()  # flush pending writes before the snapshot
            escaped = backup_path.replace("'", "''")
            async with self.cursor() as c:
                await c.execute(f"VACUUM INTO '{escaped}'")
            size_kb = os.path.getsize(backup_path) // 1024
            logger.info(f"[db] backup created: {backup_path} ({size_kb} KB)")
        except aiosqlite.Error as e:
            logger.warning(f"[db] backup failed: {e}")
            return None
        self._rotate_backups(backups_dir, stem)
        return backup_path

    def _rotate_backups(self, backups_dir: str, stem: str) -> None:
        """Delete oldest snapshots beyond backup_keep.

        Sorted by mtime rather than name: same-second collision suffixes
        (`-1`, `-2`, ...) do not sort lexically after the plain timestamp.
        """
        try:
            names = [
                f for f in os.listdir(backups_dir)
                if f.startswith(stem + ".") and f.endswith(".db")
            ]
            names.sort(key=lambda f: os.path.getmtime(os.path.join(backups_dir, f)))
        except OSError:
            return
        excess = len(names) - self.backup_keep
        for name in names[:max(excess, 0)]:
            try:
                os.remove(os.path.join(backups_dir, name))
                logger.info(f"[db] backup rotated out: {name}")
            except OSError as e:
                logger.warning(f"[db] failed to delete old backup {name}: {e}")
