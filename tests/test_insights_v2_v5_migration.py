"""Tests for schema v5 migration (2026-07-20, Layer 1 二期):
reflections 数据迁入 insights_v2，旧表改名 reflections_archive 归档。

覆盖：
- 字段映射：content→hypothesis、significance→confidence、is_active→status；
  evidence_fact_ids 一律 '[]'（旧数据无证据链，有损迁移）、needs_more_evidence=1
- 旧表改名 reflections_archive 归档，数据保留
- 幂等：二次 open 不重复迁移、不报错
- 全新库：不再创建 reflections，创建 insights_v2
"""
import asyncio
import os
import tempfile
import unittest

import aiosqlite

from storage.database import Database


_V4_DDL = """
    CREATE TABLE schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO schema_version (version) VALUES (4);
    CREATE TABLE reflections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        insight_type TEXT,
        related_experience_ids TEXT DEFAULT '[]',
        significance REAL DEFAULT 0.5,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        session_id TEXT DEFAULT 'default',
        embedding BLOB,
        embedding_version INTEGER DEFAULT 0
    );
"""


class TestInsightsV2V5Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "ai_friend.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_v4_db(self, extra_sql: str = ""):
        """Create a schema v4 database（reflections 表仍在使用的形态）。"""
        async def _mk():
            conn = await aiosqlite.connect(self.db_path)
            await conn.executescript(_V4_DDL + extra_sql)
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

    def test_field_mapping_and_archive(self):
        """content→hypothesis、significance→confidence、is_active→status；
        evidence 一律空、needs_more_evidence=1、created_by='migration'。"""
        # 注：用 sess_a 而非 default —— #SR-002 会把 default session 的数据
        # 迁往角色 session（原根目录 personality.json），干扰断言
        self._make_v4_db("""
            INSERT INTO reflections (content, insight_type, significance, is_active,
                                     session_id, created_at)
                VALUES ('用户可能偏好独处', 'pattern', 0.8, 1, 'sess_a',
                        '2026-07-01 10:00:00');
            INSERT INTO reflections (content, insight_type, significance, is_active,
                                     session_id)
                VALUES ('已失效的旧反思', 'emotion', 0.6, 0, 'sess_a');
        """)
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        rows = self._query(
            "SELECT hypothesis, insight_type, confidence, status, evidence_fact_ids,"
            " needs_more_evidence, expires_at, created_by, created_at, session_id"
            " FROM insights_v2 ORDER BY id")
        self.assertEqual(len(rows), 2)
        active, expired = rows
        self.assertEqual(active["hypothesis"], "用户可能偏好独处")
        self.assertEqual(active["insight_type"], "pattern")
        self.assertAlmostEqual(active["confidence"], 0.8)
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["evidence_fact_ids"], "[]")
        self.assertEqual(active["needs_more_evidence"], 1)
        self.assertIsNone(active["expires_at"])
        self.assertEqual(active["created_by"], "migration")
        self.assertEqual(active["created_at"], "2026-07-01 10:00:00")
        self.assertEqual(active["session_id"], "sess_a")
        self.assertEqual(expired["hypothesis"], "已失效的旧反思")
        self.assertEqual(expired["status"], "expired")

        # 旧表改名归档，数据保留
        self.assertFalse(self._table_exists("reflections"))
        self.assertTrue(self._table_exists("reflections_archive"))
        self.assertEqual(
            len(self._query("SELECT 1 FROM reflections_archive")), 2)

    def test_migration_idempotent_second_open(self):
        """幂等：二次 open 不重复迁移、不报错、数据不变。"""
        self._make_v4_db("""
            INSERT INTO reflections (content, insight_type, significance, is_active,
                                     session_id)
                VALUES ('用户喜欢深夜聊天', 'pattern', 0.7, 1, 'sess_a');
        """)
        for _ in range(2):
            db = Database(self.db_path)
            asyncio.run(db.open())
            asyncio.run(db.close())

        rows = self._query("SELECT hypothesis FROM insights_v2")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hypothesis"], "用户喜欢深夜聊天")
        self.assertFalse(self._table_exists("reflections"))
        self.assertTrue(self._table_exists("reflections_archive"))
        ver = self._query("SELECT MAX(version) AS v FROM schema_version")
        self.assertEqual(ver[0]["v"], 5)

    def test_fresh_db_has_insights_v2_without_reflections(self):
        """全新库：创建 insights_v2，不再创建 reflections / reflections_archive。"""
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        self.assertTrue(self._table_exists("insights_v2"))
        self.assertFalse(self._table_exists("reflections"))
        self.assertFalse(self._table_exists("reflections_archive"))
        ver = self._query("SELECT MAX(version) AS v FROM schema_version")
        self.assertEqual(ver[0]["v"], 5)


if __name__ == "__main__":
    unittest.main()
