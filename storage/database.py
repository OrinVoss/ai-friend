import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.initialize()
        logger.info(f"[db] opened: {db_path}")

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        with self._lock:
            c = self.conn.cursor()
            try:
                yield c
                self.conn.commit()
            except sqlite3.Error:
                self.conn.rollback()
                raise
            finally:
                c.close()

    def initialize(self) -> None:
        with self.cursor() as c:
            c.executescript("""
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
            """)

            # Schema migration: add columns only if they don't exist
            for table, column, col_type, default_val in [
                ("user_facts", "importance", "REAL", "0.5"),
                ("experiences", "importance", "REAL", "0.5"),
                ("reflections", "is_active", "INTEGER", "1"),
                # Semantic embedding columns (nullable blob for float32 vectors)
                ("user_facts", "embedding", "BLOB", "NULL"),
                ("user_facts", "embedding_version", "INTEGER", "0"),
                ("experiences", "embedding", "BLOB", "NULL"),
                ("experiences", "embedding_version", "INTEGER", "0"),
                ("reflections", "embedding", "BLOB", "NULL"),
                ("reflections", "embedding_version", "INTEGER", "0"),
            ]:
                c.execute(f"PRAGMA table_info({table})")
                columns = [row[1] for row in c.fetchall()]
                if column not in columns:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default_val}")
                    logger.info(f"Schema migration: added {table}.{column}")

    def close(self) -> None:
        logger.info(f"[db] closed: {self.db_path}")
        self.conn.close()
