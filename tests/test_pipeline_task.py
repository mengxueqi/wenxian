from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from literature_tracker.cli import build_parser
from literature_tracker.tasks import run_full_pipeline


class PipelineTaskTests(unittest.TestCase):
    def test_cli_exposes_run_all(self) -> None:
        args = build_parser().parse_args(["run-all", "--limit", "5"])

        self.assertEqual(args.command, "run-all")
        self.assertEqual(args.limit, 5)

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
                summary = run_full_pipeline(db_path=db_path, output_dir=report_dir)

        self.assertEqual(summary["status"], "partial")
        self.assertIn("build_report", summary["stages"])

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


if __name__ == "__main__":
    unittest.main()
