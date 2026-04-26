from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord, SourceConfig
from literature_tracker.storage import SQLiteRepository


class RepositoryTests(unittest.TestCase):
    def test_initialize_and_upsert_raw_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.sync_sources(
                [
                    SourceConfig(
                        source_name="Test Journal",
                        canonical_url="https://example.com",
                        platform="web",
                        incremental_url="https://example.com/articles",
                        collector_kind="html",
                    )
                ]
            )
            stored = repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/1",
                        title="A test paper",
                        abstract="Example abstract",
                        doi="10.1000/example",
                        collector_kind="html",
                    )
                ]
            )
            self.assertEqual(stored, 1)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT COUNT(*), MAX(doi) FROM raw_records"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], "10.1000/example")


if __name__ == "__main__":
    unittest.main()
