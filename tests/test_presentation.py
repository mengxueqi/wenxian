from __future__ import annotations

from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from literature_tracker.presentation import build_run_health, build_source_status_rows, rows_to_csv_bytes
from literature_tracker.models import SourceConfig
from literature_tracker.storage import SQLiteRepository


class PresentationTests(unittest.TestCase):
    def test_build_run_health_marks_old_success_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            process_run = repository.start_process_run()
            repository.finish_process_run(
                process_run,
                status="success",
                item_count=1,
            )

            _, pipeline_health = build_run_health(
                repository,
                now=datetime(2100, 1, 1),
            )

            self.assertEqual(pipeline_health[0]["health_state"], "stale")
            self.assertEqual(pipeline_health[1]["health_state"], "never")

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

    def test_source_only_health_does_not_query_pipeline(self) -> None:
        repository = Mock(spec=SQLiteRepository)
        repository.fetch_source_health.return_value = [
            {"source_name": "Test", "source_status": "active", "last_run_status": "partial"},
        ]
        sources, pipeline = build_run_health(repository, include_pipeline=False)
        self.assertEqual(sources[0]["health_state"], "partial")
        self.assertEqual(pipeline, [])
        repository.fetch_pipeline_health.assert_not_called()

    def test_source_status_rows_put_failed_and_blocked_sources_at_the_end(self) -> None:
        states = ["failed", "healthy", "partial", "blocked", "running", "never", "stale"]
        sources = [SourceConfig(state, f"https://example.com/{state}", "test", "", "") for state in states]
        rows = build_source_status_rows([{"source_name": state, "health_state": state} for state in states], sources)
        self.assertEqual([r["数据源"] for r in rows], ["healthy", "running", "never", "stale", "partial", "failed", "blocked"])
        self.assertEqual(rows[0]["网址"], "https://example.com/healthy")


if __name__ == "__main__":
    unittest.main()
