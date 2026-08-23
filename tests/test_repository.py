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

    def test_upsert_raw_records_preserves_rich_fields_when_refresh_is_sparse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/1",
                        title="A test paper",
                        authors="Alice Example; Bob Example",
                        abstract="Complete abstract",
                        published_at="2026-07-01",
                        doi="10.1000/example",
                        collector_kind="html",
                        metadata={"keywords": ["Synthetic biology"]},
                    )
                ]
            )
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/1",
                        title="A test paper",
                        collector_kind="html",
                        metadata={
                            "keywords": [],
                            "enrichment_status": "failed",
                            "enrichment_error": "detail page blocked",
                        },
                    )
                ]
            )

            stored = repository.fetch_raw_records()[0]

            self.assertEqual(stored.authors, "Alice Example; Bob Example")
            self.assertEqual(stored.abstract, "Complete abstract")
            self.assertEqual(stored.published_at, "2026-07-01")
            self.assertEqual(stored.doi, "10.1000/example")
            self.assertEqual(stored.metadata["keywords"], ["Synthetic biology"])
            self.assertEqual(stored.metadata["enrichment_status"], "failed")
            self.assertIn("detail page blocked", stored.metadata["enrichment_error"])

    def test_non_material_metadata_does_not_change_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            base_record = RawRecord(
                source_name="Test Journal",
                journal_name="Test Journal",
                listing_url="https://example.com/articles",
                article_url="https://example.com/article/1",
                title="A test paper",
                abstract="Complete abstract",
                collector_kind="html",
                metadata={"request_id": "first"},
            )
            repository.upsert_raw_records([base_record])
            first_hash = repository.fetch_raw_records()[0].content_hash

            base_record.metadata = {"request_id": "second"}
            repository.upsert_raw_records([base_record])
            second_hash = repository.fetch_raw_records()[0].content_hash

            self.assertEqual(first_hash, second_hash)

    def test_run_health_exposes_latest_status_and_error(self) -> None:
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
                        incremental_url="https://example.com/feed",
                        collector_kind="rss",
                    )
                ]
            )
            crawl_run = repository.start_crawl_run("Test Journal")
            repository.finish_crawl_run(
                crawl_run,
                status="partial",
                item_count=3,
                error_message="one detail page failed",
            )
            process_run = repository.start_process_run()
            repository.finish_process_run(
                process_run,
                status="success",
                item_count=3,
            )

            source_health = repository.fetch_source_health()
            pipeline_health = repository.fetch_pipeline_health()

            self.assertEqual(source_health[0]["last_run_status"], "partial")
            self.assertEqual(source_health[0]["item_count"], 3)
            self.assertIn("detail page failed", source_health[0]["error_message"])
            self.assertEqual(pipeline_health[0]["stage"], "process")
            self.assertEqual(pipeline_health[0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
