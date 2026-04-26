from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_process_stage


class ProcessTaskTests(unittest.TestCase):
    def test_process_stage_upserts_papers(self) -> None:
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
                        title="  Example Paper  ",
                        authors="Alice, Bob",
                        abstract="Abstract text",
                        published_at="2026/04/16",
                        doi="10.1000/example",
                        language="en-US",
                        collector_kind="html",
                    )
                ]
            )

            summary = run_process_stage(db_path=db_path)
            papers = repository.fetch_papers()

            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["scanned_raw_records"], 1)
            self.assertEqual(summary["upserted_papers"], 1)
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].paper_key, "doi:10.1000/example")
            self.assertEqual(papers[0].canonical_title, "Example Paper")
            self.assertEqual(papers[0].normalized_authors, "Alice; Bob")
            self.assertEqual(papers[0].published_at, "2026-04-16")

    def test_process_stage_dedupes_papers_by_doi_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Source A",
                        journal_name="Source A",
                        listing_url="https://a.example.com/articles",
                        article_url="https://a.example.com/article/1",
                        title="Same DOI paper",
                        abstract="First source abstract",
                        doi="10.1000/same-doi",
                        collector_kind="html",
                    ),
                    RawRecord(
                        source_name="Source B",
                        journal_name="Source B",
                        listing_url="https://b.example.com/articles",
                        article_url="https://b.example.com/article/1",
                        title="Same DOI paper mirrored",
                        abstract="Second source abstract",
                        doi="10.1000/same-doi",
                        collector_kind="html",
                    ),
                ]
            )

            summary = run_process_stage(db_path=db_path)
            papers = repository.fetch_papers()

            self.assertEqual(summary["scanned_raw_records"], 2)
            self.assertEqual(summary["upserted_papers"], 2)
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].paper_key, "doi:10.1000/same-doi")
            self.assertEqual(
                papers[0].metadata["observed_sources"],
                ["Source A", "Source B"],
            )
            self.assertEqual(len(papers[0].metadata["observed_raw_record_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
