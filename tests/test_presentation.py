from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.models import StoredPaper, StoredPaperChange
from literature_tracker.presentation import (
    build_filter_options,
    build_filtered_snapshot,
    build_new_paper_batch_rows,
    build_new_paper_rows,
    build_snapshot,
    rows_to_csv_bytes,
)
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import (
    run_change_detection,
    run_insight_build,
    run_process_stage,
)


class PresentationTests(unittest.TestCase):
    def test_build_filtered_snapshot_applies_filters_and_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Source A",
                        journal_name="Source A",
                        listing_url="https://example.com/a/articles",
                        article_url="https://example.com/a/1",
                        title="CRISPR synthetic biology advance",
                        abstract="A synthetic biology article using CRISPR tools.",
                        doi="10.1000/a1",
                        collector_kind="html",
                    ),
                    RawRecord(
                        source_name="Source B",
                        journal_name="Source B",
                        listing_url="https://example.com/b/articles",
                        article_url="https://example.com/b/1",
                        title="Retraction Note: CRISPR synthetic biology vesicle delivery study",
                        authors="Jay Keasling; Other Author",
                        abstract="This retracted synthetic biology article uses CRISPR tools.",
                        doi="10.1000/b1",
                        collector_kind="html",
                    ),
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)
            run_insight_build(db_path=db_path)

            snapshot = build_snapshot(repository)
            filtered = build_filtered_snapshot(
                snapshot,
                query="retraction",
                tracking_statuses=["review"],
                change_types=["retraction_notice"],
                sort_by="title_asc",
            )

            self.assertEqual(filtered["metrics"]["papers"], 1)
            self.assertEqual(filtered["metrics"]["changes"], 1)
            self.assertEqual(
                filtered["focus_cards"][0]["title"],
                "Retraction Note: CRISPR synthetic biology vesicle delivery study",
            )
            self.assertEqual(
                filtered["focus_cards"][0]["abstract"],
                "This retracted synthetic biology article uses CRISPR tools.",
            )
            self.assertEqual(filtered["focus_cards"][0]["tracking_status"], "review")

    def test_build_filter_options_collects_current_snapshot_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Source A",
                        journal_name="Source A",
                        listing_url="https://example.com/a/articles",
                        article_url="https://example.com/a/1",
                        title="CRISPR synthetic biology advance",
                        abstract="A synthetic biology article using CRISPR tools.",
                        doi="10.1000/a1",
                        collector_kind="html",
                    ),
                    RawRecord(
                        source_name="Source B",
                        journal_name="Source B",
                        listing_url="https://example.com/b/articles",
                        article_url="https://example.com/b/1",
                        title="Retraction Note: CRISPR synthetic biology vesicle delivery study",
                        authors="Jay Keasling; Other Author",
                        abstract="This retracted synthetic biology article uses CRISPR tools.",
                        doi="10.1000/b1",
                        collector_kind="html",
                    ),
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)
            run_insight_build(db_path=db_path)

            snapshot = build_snapshot(repository)
            options = build_filter_options(snapshot)

            self.assertIn("watchlist", options["tracking_statuses"])
            self.assertIn("review", options["tracking_statuses"])
            self.assertNotIn("priority", options["tracking_statuses"])
            self.assertNotIn("score_labels", options)
            self.assertIn("new_paper", options["change_types"])
            self.assertIn("retraction_notice", options["change_types"])
            self.assertIn("crispr", options["themes"])
            self.assertIn("synthetic_biology", options["themes"])

    def test_rows_to_csv_bytes_serializes_lists_and_dicts(self) -> None:
        payload = rows_to_csv_bytes(
            [
                {
                    "title": "Example",
                    "themes": ["crispr", "synthetic_biology"],
                    "metadata": {"source": "Source A"},
                }
            ]
        ).decode("utf-8-sig")

        self.assertIn("title,themes,metadata", payload)
        self.assertIn("crispr, synthetic_biology", payload)
        self.assertIn("Source A", payload)

    def test_new_paper_batches_group_by_detected_date_and_dedupe_papers(self) -> None:
        snapshot = {
            "papers": [
                StoredPaper(
                    id=1,
                    raw_record_id=1,
                    paper_key="old",
                    source_name="Source A",
                    journal_name="Source A",
                    article_url="https://example.com/old",
                    doi="10.1000/old",
                    canonical_title="Existing Paper",
                    normalized_authors="",
                    published_at="2026-04-20",
                    created_at="2026-04-27T09:00:00",
                    updated_at="2026-04-27T09:00:00",
                ),
                StoredPaper(
                    id=2,
                    raw_record_id=2,
                    paper_key="new-a",
                    source_name="Source A",
                    journal_name="Source A",
                    article_url="https://example.com/a",
                    doi="10.1000/a",
                    canonical_title="New Paper A",
                    normalized_authors="",
                    published_at="2026-04-28",
                    created_at="2026-04-28T10:00:00",
                    updated_at="2026-04-28T10:00:00",
                ),
            ],
            "changes": [
                StoredPaperChange(
                    id=1,
                    change_key="new-a",
                    paper_id=2,
                    source_name="Source A",
                    change_type="new_paper",
                    summary="New Paper A",
                    detected_at="2026-04-28T10:00:00",
                ),
                StoredPaperChange(
                    id=2,
                    change_key="new-a-duplicate",
                    paper_id=2,
                    source_name="Source A",
                    change_type="new_paper",
                    summary="New Paper A duplicate crawl",
                    detected_at="2026-04-28T18:00:00",
                ),
            ],
            "insights": [],
            "tracking_items": [],
        }

        rows = build_new_paper_rows(snapshot, batch_date="2026-04-28")
        batches = build_new_paper_batch_rows(snapshot)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "New Paper A")
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["batch_date"], "2026-04-28")
        self.assertEqual(batches[0]["new_papers"], 1)
        self.assertEqual(batches[0]["existing_papers_before_batch"], 1)


if __name__ == "__main__":
    unittest.main()
