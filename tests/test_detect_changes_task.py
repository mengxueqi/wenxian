from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_change_detection, run_process_stage


class DetectChangesTaskTests(unittest.TestCase):
    def test_detect_changes_creates_new_paper_once(self) -> None:
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
                        title="Example Paper",
                        abstract="Abstract text",
                        doi="10.1000/example",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)

            first_summary = run_change_detection(db_path=db_path)
            second_summary = run_change_detection(db_path=db_path)
            changes = repository.fetch_paper_changes()

            self.assertEqual(first_summary["detected_changes"], 1)
            self.assertEqual(second_summary["detected_changes"], 0)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].change_type, "new_paper")

    def test_detect_changes_creates_content_updated_after_hash_change(self) -> None:
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
                        title="Example Paper",
                        abstract="Abstract text",
                        doi="10.1000/example",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/1",
                        title="Example Paper",
                        abstract="Abstract text updated",
                        doi="10.1000/example",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            summary = run_change_detection(db_path=db_path)
            changes = repository.fetch_paper_changes()

            self.assertEqual(summary["detected_changes"], 1)
            self.assertEqual(len(changes), 2)
            self.assertEqual(changes[0].change_type, "content_updated")
            self.assertIn("previous_content_hash", changes[0].metadata)

    def test_detect_changes_detects_retraction_signal(self) -> None:
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
                        article_url="https://example.com/article/2",
                        title="Retraction Note: Example Paper",
                        abstract="This article has been retracted.",
                        doi="10.1000/retracted",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)

            summary = run_change_detection(db_path=db_path)
            changes = repository.fetch_paper_changes()
            change_types = [change.change_type for change in changes]

            self.assertEqual(summary["detected_changes"], 2)
            self.assertIn("new_paper", change_types)
            self.assertIn("retraction_notice", change_types)


if __name__ == "__main__":
    unittest.main()
