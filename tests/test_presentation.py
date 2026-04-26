from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.presentation import (
    build_filter_options,
    build_filtered_snapshot,
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
                        title="Retraction Note: Vesicle delivery study",
                        abstract="This article has been retracted.",
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
                tracking_statuses=["priority"],
                score_labels=["high"],
                change_types=["retraction_notice"],
                sort_by="title_asc",
            )

            self.assertEqual(filtered["metrics"]["papers"], 1)
            self.assertEqual(filtered["metrics"]["changes"], 1)
            self.assertEqual(filtered["focus_cards"][0]["title"], "Retraction Note: Vesicle delivery study")
            self.assertEqual(filtered["focus_cards"][0]["tracking_status"], "priority")

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
                        title="Retraction Note: Vesicle delivery study",
                        abstract="This article has been retracted.",
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
            self.assertIn("priority", options["tracking_statuses"])
            self.assertIn("low", options["score_labels"])
            self.assertIn("high", options["score_labels"])
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


if __name__ == "__main__":
    unittest.main()
