"""Tests for #UK-001: user_facts UNIQUE constraint migration to
UNIQUE(session_id, category, fact_key)."""
import asyncio
import os
import tempfile
import unittest

import aiosqlite

from storage.database import Database
from storage.repository import Repository


class TestUserFactsUniqueMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "ai_friend.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _table_sql(self):
        async def _q():
            conn = await aiosqlite.connect(self.db_path)
            try:
                cur = await conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='user_facts'")
                row = await cur.fetchone()
                return row[0] if row else ""
            finally:
                await conn.close()
        return asyncio.run(_q())

    def _make_v2_db(self):
        """Create a pre-#UK-001 database: old global UNIQUE, schema_version=2."""
        async def _mk():
            conn = await aiosqlite.connect(self.db_path)
            await conn.executescript("""
                CREATE TABLE schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO schema_version (version) VALUES (2);
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
                    UNIQUE(category, fact_key)
                );
                INSERT INTO user_facts (category, fact_key, fact_value, confidence, session_id)
                    VALUES ('preference', '最爱食物', '披萨', 0.9, 'sess_a');
                INSERT INTO user_facts (category, fact_key, fact_value, confidence, session_id)
                    VALUES ('identity', '名字', '小明', 1.0, 'sess_b');
            """)
            await conn.commit()
            await conn.close()
        asyncio.run(_mk())

    def test_fresh_db_has_session_scoped_constraint(self):
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        sql = self._table_sql()
        self.assertIn("UNIQUE(session_id, category, fact_key)", sql)

    def test_old_schema_migrated_data_preserved(self):
        self._make_v2_db()
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        sql = self._table_sql()
        self.assertIn("UNIQUE(session_id, category, fact_key)", sql)
        self.assertNotIn("UNIQUE(category, fact_key)", sql.replace(
            "UNIQUE(session_id, category, fact_key)", ""))

        repo = Repository(Database(self.db_path))
        # reuse one connection for readback
        async def _read():
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            try:
                cur = await conn.execute(
                    "SELECT fact_key, fact_value, session_id FROM user_facts ORDER BY fact_key")
                rows = await cur.fetchall()
                cur2 = await conn.execute("SELECT MAX(version) FROM schema_version")
                ver = (await cur2.fetchone())[0]
                return [dict(r) for r in rows], ver
            finally:
                await conn.close()
        rows, version = asyncio.run(_read())
        self.assertEqual(version, 3)
        by_key = {r["fact_key"]: r for r in rows}
        self.assertEqual(by_key["最爱食物"]["fact_value"], "披萨")
        self.assertEqual(by_key["最爱食物"]["session_id"], "sess_a")
        self.assertEqual(by_key["名字"]["fact_value"], "小明")

    def test_same_key_two_sessions_coexist(self):
        """The core bug: two sessions must hold the same fact_key independently."""
        db = Database(self.db_path)
        asyncio.run(db.open())
        repo_a = Repository(db)
        repo_a.session_id = "sess_a"
        repo_b = Repository(db)
        repo_b.session_id = "sess_b"

        asyncio.run(repo_a.upsert_fact("preference", "最爱食物", "披萨", confidence=0.9))
        asyncio.run(repo_b.upsert_fact("preference", "最爱食物", "寿司", confidence=0.8))

        facts_a = asyncio.run(repo_a.get_active_facts(limit=10))
        facts_b = asyncio.run(repo_b.get_active_facts(limit=10))
        self.assertEqual(len(facts_a), 1)
        self.assertEqual(facts_a[0].fact_value, "披萨")
        self.assertEqual(len(facts_b), 1)
        self.assertEqual(facts_b[0].fact_value, "寿司")

        # Session B lowers confidence of its own row — session A untouched
        asyncio.run(repo_b.update_fact_confidence(facts_b[0].id, 0.3))
        facts_a2 = asyncio.run(repo_a.get_active_facts(limit=10))
        self.assertEqual(facts_a2[0].confidence, 0.9)

        asyncio.run(db.close())


if __name__ == "__main__":
    unittest.main()
