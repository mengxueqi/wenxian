from __future__ import annotations

import tempfile
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_process_stage


class ProcessTaskTests(unittest.TestCase):
    def test_doi_promotion_merges_both_rows_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            records = [
                RawRecord(
                    source_name="Test Journal", journal_name="Test Journal",
                    listing_url="https://example.com/feed", article_url=f"https://example.com/{i}",
                    title="A distinctive metabolic engineering study",
                    doi="10.1000/same" if i == 1 else None,
                ) for i in (1, 2)
            ]
            repository.upsert_raw_records(records)
            run_process_stage(db_path=db_path)
            before = repository.fetch_papers()
            keep = next(p for p in before if p.doi)
            duplicate = next(p for p in before if not p.doi)
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    "INSERT INTO paper_changes (change_key,paper_id,source_name,change_type,summary,detected_at) VALUES (?,?,?,?,?,?)",
                    ("original-change", duplicate.id, "Test Journal", "new_paper", "Existing history", "2026-01-01"),
                )
                connection.execute(
                    "INSERT INTO paper_insights (insight_key,paper_id,source_name,created_at,updated_at) VALUES (?,?,?,?,?)",
                    ("original-insight", duplicate.id, "Test Journal", "2026-01-01", "2026-01-01"),
                )
                for paper in before:
                    connection.execute(
                        "INSERT INTO tracking_items (tracking_key,paper_id,source_name,note,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                        (f"track-{paper.id}", paper.id, "Test Journal", f"Note {paper.id}", "2026-01-01", "2026-01-01"),
                    )
                connection.commit()
            records[1].doi = "10.1000/same"
            repository.upsert_raw_records([records[1]])
            run_process_stage(db_path=db_path)
            run_process_stage(db_path=db_path)
            papers = repository.fetch_papers()
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].id, keep.id)
            self.assertEqual(len(papers[0].metadata["observed_raw_record_ids"]), 2)
            self.assertEqual(papers[0].metadata["merged_tracking_items"][0]["note"], f"Note {duplicate.id}")
            with closing(sqlite3.connect(db_path)) as connection:
                self.assertEqual(connection.execute("SELECT paper_id FROM paper_changes").fetchone()[0], keep.id)
                self.assertEqual(connection.execute("SELECT paper_id FROM paper_insights").fetchone()[0], keep.id)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_conflicting_generic_title_is_kept_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            records = [RawRecord(
                source_name="Test Journal", journal_name="Test Journal",
                listing_url="https://example.com/feed", article_url=f"https://example.com/{i}",
                title="Editorial Board", doi="10.1000/old" if i == 1 else None,
            ) for i in (1, 2)]
            repository.upsert_raw_records(records)
            run_process_stage(db_path=db_path)
            records[1].doi = "10.1000/old"
            repository.upsert_raw_records([records[1]])
            for _ in range(2):
                run_process_stage(db_path=db_path)
            papers = repository.fetch_papers()
            self.assertEqual(len(papers), 2)
            guarded = next(p for p in papers if p.article_url.endswith("/2"))
            self.assertIsNone(guarded.doi)
            self.assertIn("identity_conflict", guarded.metadata)

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
