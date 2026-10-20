from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_process_stage
from literature_tracker.tasks.repair_metadata import BAD_DOI, BAD_OPENALEX_ID, repair_editorial_metadata


class MetadataRepairTests(unittest.TestCase):
    def test_repair_backs_up_and_splits_only_confirmed_bad_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records([RawRecord(
                source_name="Metabolic Engineering", journal_name="Metabolic Engineering",
                listing_url="https://rss.sciencedirect.com/feed", article_url=f"https://example.com/{i}",
                title="Editorial Board", doi=BAD_DOI,
                metadata={"openalex_id": BAD_OPENALEX_ID, "keywords": ["Computer science"], "external_metadata_source": "openalex"},
            ) for i in (1, 2)])
            run_process_stage(db_path=db_path)
            self.assertEqual(len(repository.fetch_papers()), 1)
            self.assertFalse(repair_editorial_metadata(db_path)["applied"])
            result = repair_editorial_metadata(db_path, apply=True)
            backup_path = Path(result["backup_path"])
            self.assertTrue(backup_path.is_file())
            with closing(sqlite3.connect(backup_path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_records WHERE doi = ?", (BAD_DOI,)).fetchone()[0], 2)
            run_process_stage(db_path=db_path)
            papers = repository.fetch_papers()
            self.assertEqual(len(papers), 2)
            self.assertTrue(all(p.doi is None for p in papers))
            self.assertTrue(all("openalex_id" not in p.metadata for p in papers))
            self.assertFalse(repair_editorial_metadata(db_path, apply=True)["applied"])


if __name__ == "__main__":
    unittest.main()
