"""Tests for schema v4 migration (2026-07-18, Layer 1 完整上线):
user_facts 数据迁入 facts_v2，旧表改名 user_facts_archive 归档。

覆盖：
- 只迁 fact_type='user_fact' 的行；is_active 映射为 active/obsolete
- 与 facts_v2 既有数据冲突时跳过（INSERT OR IGNORE，既有数据更新鲜）
- 幂等：二次 open 不重复迁移、不报错
"""
import asyncio
import os
import tempfile
import unittest

import aiosqlite

from storage.database import Database


_V3_DDL = """
    CREATE TABLE schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO schema_version (version) VALUES (3);
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
    CREATE TABLE facts_v2 (
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
"""


class TestFactsV2V4Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "ai_friend.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_v3_db(self, extra_sql: str = ""):
        """Create a schema v3 database (user_facts + facts_v2 双写期形态）。"""
        async def _mk():
            conn = await aiosqlite.connect(self.db_path)
            await conn.executescript(_V3_DDL + extra_sql)
            await conn.commit()
            await conn.close()
        asyncio.run(_mk())

    def _query(self, sql, params=()):
        async def _q():
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            try:
                cur = await conn.execute(sql, params)
                return [dict(r) for r in await cur.fetchall()]
            finally:
                await conn.close()
        return asyncio.run(_q())

    def _table_exists(self, name) -> bool:
        return bool(self._query(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))

    def test_only_user_fact_type_migrated_and_status_mapped(self):
        """只迁 fact_type='user_fact'；is_active=1→active，is_active=0→obsolete。"""
        self._make_v3_db("""
            INSERT INTO user_facts (category, fact_key, fact_value, confidence,
                                    importance, is_active, fact_type, session_id)
                VALUES ('preference', '最爱食物', '披萨', 0.9, 0.8, 1, 'user_fact', 'default');
            INSERT INTO user_facts (category, fact_key, fact_value, confidence,
                                    is_active, fact_type, session_id)
                VALUES ('event', '旧事件', '已过期', 0.6, 0, 'user_fact', 'default');
            INSERT INTO user_facts (category, fact_key, fact_value, confidence,
                                    fact_type, session_id)
                VALUES ('agent', '自我设定', '活泼', 0.9, 'agent_fact', 'default');
        """)
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        rows = self._query("SELECT fact_key, status, importance, created_by FROM facts_v2")
        by_key = {r["fact_key"]: r for r in rows}
        self.assertEqual(set(by_key), {"最爱食物", "旧事件"})
        self.assertEqual(by_key["最爱食物"]["status"], "active")
        self.assertAlmostEqual(by_key["最爱食物"]["importance"], 0.8)
        self.assertEqual(by_key["最爱食物"]["created_by"], "migration")
        self.assertEqual(by_key["旧事件"]["status"], "obsolete")
        # v6（A8）：归档表已被物理删除，数据只在 facts_v2
        self.assertFalse(self._table_exists("user_facts"))
        self.assertFalse(self._table_exists("user_facts_archive"))

    def test_conflict_with_existing_facts_v2_skipped(self):
        """UNIQUE(session_id, category, fact_key) 冲突时跳过——facts_v2
        双写期间的数据更新鲜，不被旧表覆盖。"""
        # 注：用 sess_a 而非 default —— #SR-002 会把 default session 的数据
        # 迁往角色 session（原根目录 personality.json name=小星），干扰冲突构造
        self._make_v3_db("""
            INSERT INTO user_facts (category, fact_key, fact_value, confidence,
                                    fact_type, session_id)
                VALUES ('preference', '最爱食物', '旧表披萨', 0.9, 'user_fact', 'sess_a');
            INSERT INTO facts_v2 (category, fact_key, fact_value, confidence,
                                  created_by, session_id)
                VALUES ('preference', '最爱食物', '新表寿司', 0.8, 'consolidation', 'sess_a');
            INSERT INTO user_facts (category, fact_key, fact_value, confidence,
                                    fact_type, session_id)
                VALUES ('identity', '名字', '小明', 1.0, 'user_fact', 'sess_a');
        """)
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        rows = self._query("SELECT fact_key, fact_value, created_by FROM facts_v2")
        by_key = {r["fact_key"]: r for r in rows}
        # 冲突行保留 facts_v2 既有值
        self.assertEqual(by_key["最爱食物"]["fact_value"], "新表寿司")
        self.assertEqual(by_key["最爱食物"]["created_by"], "consolidation")
        # 非冲突行正常迁入
        self.assertEqual(by_key["名字"]["fact_value"], "小明")
        self.assertEqual(by_key["名字"]["created_by"], "migration")

    def test_migration_idempotent_second_open(self):
        """幂等：二次 open 不重复迁移、不报错、数据不变。"""
        self._make_v3_db("""
            INSERT INTO user_facts (category, fact_key, fact_value, confidence,
                                    fact_type, session_id)
                VALUES ('preference', '最爱食物', '披萨', 0.9, 'user_fact', 'default');
        """)
        for _ in range(2):
            db = Database(self.db_path)
            asyncio.run(db.open())
            asyncio.run(db.close())

        rows = self._query("SELECT fact_key, fact_value FROM facts_v2")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fact_value"], "披萨")
        self.assertFalse(self._table_exists("user_facts"))
        self.assertFalse(self._table_exists("user_facts_archive"))
        ver = self._query("SELECT MAX(version) AS v FROM schema_version")
        # schema v6（2026-07-21，A8 删除归档表）后版本号随库升级到 6
        self.assertEqual(ver[0]["v"], 6)


if __name__ == "__main__":
    unittest.main()
