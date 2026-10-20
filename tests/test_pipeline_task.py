from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from literature_tracker.catalog import build_catalog, select_articles
from literature_tracker.cli import build_parser
from literature_tracker.models import RawRecord, SourceConfig
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_full_pipeline


class PipelineTaskTests(unittest.TestCase):
    def test_cli_exposes_run_all(self) -> None:
        args = build_parser().parse_args(["run-all", "--limit", "5"])

        self.assertEqual(args.command, "run-all")
        self.assertEqual(args.limit, 5)
        self.assertFalse(args.report)
        self.assertTrue(build_parser().parse_args(["run-all", "--report"]).report)

    def test_run_full_pipeline_reports_partial_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            report_dir = Path(temp_dir) / "reports"
            with (
                patch(
                    "literature_tracker.tasks.pipeline.crawl_sources",
                    return_value={"failure_count": 1, "partial_count": 0},
                ),
                patch(
                    "literature_tracker.tasks.pipeline.run_process_stage",
                    return_value={"status": "success"},
                ),
                patch(
                    "literature_tracker.tasks.pipeline.run_change_detection",
                    return_value={"status": "success"},
                ),
                patch(
                    "literature_tracker.tasks.pipeline.run_insight_build",
                    return_value={"status": "success"},
                ),
                patch(
                    "literature_tracker.tasks.pipeline.build_report",
                    return_value={"status": "success"},
                ),
            ):
                summary = run_full_pipeline(db_path=db_path, output_dir=report_dir, generate_report=True)

        self.assertEqual(summary["status"], "partial")
        self.assertIn("build_report", summary["stages"])

    def test_default_update_skips_optional_report(self) -> None:
        with (
            patch("literature_tracker.tasks.pipeline.crawl_sources", return_value={"failure_count": 0}),
            patch("literature_tracker.tasks.pipeline.run_process_stage", return_value={"status": "success"}),
            patch("literature_tracker.tasks.pipeline.run_change_detection", return_value={"status": "success"}),
            patch("literature_tracker.tasks.pipeline.run_insight_build", return_value={"status": "success"}),
            patch("literature_tracker.tasks.pipeline.build_report") as report,
        ):
            result = run_full_pipeline()
        self.assertEqual(result["status"], "success")
        self.assertNotIn("build_report", result["stages"])
        report.assert_not_called()

    def test_run_full_pipeline_identifies_failed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            with (
                patch(
                    "literature_tracker.tasks.pipeline.crawl_sources",
                    return_value={"failure_count": 0, "partial_count": 0},
                ),
                patch(
                    "literature_tracker.tasks.pipeline.run_process_stage",
                    side_effect=RuntimeError("process failed"),
                ),
            ):
                summary = run_full_pipeline(db_path=db_path)

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failed_stage"], "process")
        self.assertIn("process failed", summary["error"])

    def test_source_update_remains_deduplicated_searchable_and_recommended(self) -> None:
        source = SourceConfig("Test Journal", "https://example.com", "test", "https://example.com/feed", "rss")
        record = RawRecord(
            source_name=source.source_name, journal_name=source.source_name,
            listing_url=source.incremental_url, article_url="https://example.com/1",
            title="CRISPR research", authors="Frances Arnold", abstract="An improved editing method.",
            doi="10.1000/pipeline", published_at="2026-10-01",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.db"
            with (
                patch("literature_tracker.tasks.crawl.load_sources", return_value=[source]),
                patch("literature_tracker.tasks.crawl.get_collector") as collector,
            ):
                collector.return_value.collect.return_value = [record]
                first = run_full_pipeline(db_path=db_path)
                record.abstract = "Revised ketoreductase experiment."
                second = run_full_pipeline(db_path=db_path)
            repository = SQLiteRepository(db_path)
            cards = build_catalog(repository)
            self.assertEqual(first["status"], "success")
            self.assertEqual(second["status"], "success")
            self.assertEqual(len(cards), 1)
            self.assertEqual(select_articles(cards, query="Arnold ketoreductase")[0]["doi"], record.doi)
            self.assertEqual(len(select_articles(cards, recommended_only=True)), 1)
            self.assertEqual({c.change_type for c in repository.fetch_paper_changes()}, {"new_paper", "content_updated"})


if __name__ == "__main__":
    unittest.main()
