from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from literature_tracker.models import RawRecord, SourceConfig
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import crawl_sources


class _WarningCollector:
    def collect(
        self,
        source: SourceConfig,
        *,
        limit: int | None = None,
    ) -> list[RawRecord]:
        return [
            RawRecord(
                source_name=source.source_name,
                journal_name=source.source_name,
                listing_url=source.incremental_url,
                article_url="https://example.com/article/1",
                title="Example paper",
                collector_kind=source.collector_kind,
                metadata={
                    "enrichment_status": "failed",
                    "enrichment_error": "detail page blocked",
                },
            )
        ]


class CrawlTaskTests(unittest.TestCase):
    def test_crawl_marks_detail_enrichment_warnings_as_partial(self) -> None:
        source = SourceConfig(
            source_name="Test Journal",
            canonical_url="https://example.com",
            platform="web",
            incremental_url="https://example.com/feed",
            collector_kind="rss+html_detail",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            with (
                patch("literature_tracker.tasks.crawl.load_sources", return_value=[source]),
                patch(
                    "literature_tracker.tasks.crawl.get_collector",
                    return_value=_WarningCollector(),
                ),
            ):
                summary = crawl_sources(db_path=db_path)
            health = SQLiteRepository(db_path).fetch_source_health()

        self.assertEqual(summary["partial_count"], 1)
        self.assertEqual(summary["enrichment_failure_count"], 1)
        self.assertEqual(health[0]["last_run_status"], "partial")


if __name__ == "__main__":
    unittest.main()
