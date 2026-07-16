"""Tests for storage/database.py — pre-migration backup (P0-3)."""
import asyncio
import os
import tempfile
import unittest

import aiosqlite

from storage.database import Database


class TestDatabaseBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "ai_friend.db")
        self.backups_dir = os.path.join(self.tmp.name, "backups")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_old_db(self):
        """Create a minimal pre-schema_version db file (treated as version 0)."""
        async def _mk():
            conn = await aiosqlite.connect(self.db_path)
            await conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
            await conn.execute("INSERT INTO dummy VALUES (1)")
            await conn.commit()
            await conn.close()
        asyncio.run(_mk())

    def _listdir(self, path):
        return os.listdir(path) if os.path.exists(path) else []

    def test_backup_created_when_version_behind(self):
        """Old-schema db file triggers a pre-migration backup on open."""
        self._make_old_db()
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        backups = self._listdir(self.backups_dir)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].startswith("ai_friend."))
        self.assertTrue(backups[0].endswith(".db"))

    def test_backup_is_pre_migration_snapshot(self):
        """Backup contains the old schema (dummy table), not migrated tables."""
        self._make_old_db()
        db = Database(self.db_path)
        asyncio.run(db.open())
        asyncio.run(db.close())

        backups = self._listdir(self.backups_dir)
        backup_path = os.path.join(self.backups_dir, backups[0])

        async def _check():
            conn = await aiosqlite.connect(backup_path)
            try:
                cur = await conn.execute("SELECT id FROM dummy")
                row = await cur.fetchone()
                return row[0] if row else None
            finally:
                await conn.close()
        self.assertEqual(asyncio.run(_check()), 1)

    def test_no_backup_when_version_current(self):
        """Up-to-date db opens without creating a backup."""
        db = Database(self.db_path)  # fresh db — nothing to back up
        asyncio.run(db.open())
        asyncio.run(db.close())
        db2 = Database(self.db_path)  # schema_version now current — skip
        asyncio.run(db2.open())
        asyncio.run(db2.close())

        self.assertEqual(self._listdir(self.backups_dir), [])

    def test_backup_disabled(self):
        self._make_old_db()
        db = Database(self.db_path, backup_enabled=False)
        asyncio.run(db.open())
        asyncio.run(db.close())

        self.assertEqual(self._listdir(self.backups_dir), [])

    def test_memory_db_no_backup(self):
        """In-memory databases never trigger backups and open cleanly."""
        db = Database(":memory:")
        asyncio.run(db.open())
        asyncio.run(db.close())

    def test_rotation_keeps_newest_n(self):
        """Repeated backups keep only the newest backup_keep files."""
        db = Database(self.db_path, backup_keep=2)
        asyncio.run(db.open())  # fresh db — no auto backup
        for _ in range(4):
            path = asyncio.run(db.backup())
            self.assertIsNotNone(path)
        asyncio.run(db.close())

        backups = self._listdir(self.backups_dir)
        self.assertEqual(len(backups), 2)


if __name__ == "__main__":
    unittest.main()
