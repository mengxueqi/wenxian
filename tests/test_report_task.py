from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import (
    build_report,
    run_change_detection,
    run_insight_build,
    run_process_stage,
)


class ReportTaskTests(unittest.TestCase):
    def test_build_report_writes_markdown_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            output_dir = Path(temp_dir) / "reports"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/1",
                        title="Synthetic biology report paper",
                        abstract="A synthetic biology abstract.",
                        doi="10.1000/report-paper",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)
            run_insight_build(db_path=db_path)

            summary = build_report(db_path=db_path, output_dir=output_dir)

            report_path = Path(summary["report_path"])
            latest_path = Path(summary["latest_report_path"])
            self.assertTrue(report_path.exists())
            self.assertTrue(latest_path.exists())
            content = latest_path.read_text(encoding="utf-8")
            self.assertIn("Literature Tracker Report", content)
            self.assertIn("Tracking Queue", content)
            self.assertIn("Synthetic biology report paper", content)


if __name__ == "__main__":
    unittest.main()
