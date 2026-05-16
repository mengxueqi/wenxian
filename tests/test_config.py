from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.config import load_sources, strip_tracking_params
from literature_tracker.paths import SOURCES_CSV


class ConfigTests(unittest.TestCase):
    def test_strip_tracking_params(self) -> None:
        url = (
            "https://link.springer.com/journal/44307"
            "?gad_source=1&_gl=1*abc*1&gclid=xyz&page=2"
        )
        self.assertEqual(
            strip_tracking_params(url),
            "https://link.springer.com/journal/44307?page=2",
        )

    def test_load_existing_sources(self) -> None:
        sources = load_sources(SOURCES_CSV)
        self.assertEqual(len(sources), 13)
        self.assertEqual(sources[0].source_name, "合成生物学")
        self.assertEqual(sources[1].platform, "springer")
        self.assertEqual(
            [source.source_name for source in sources].count("Journal of Eukaryotic Microbiology"),
            1,
        )
        self.assertIn("sciencedirect", {source.platform for source in sources})
        self.assertIn("wiley", {source.platform for source in sources})

    def test_load_sources_supports_utf8_sig(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sources.csv"
            csv_path.write_text(
                "\ufeffsource_name,canonical_url,platform,incremental_url,collector_kind,dedupe_key,lang,status,notes\n"
                "Test Source,https://example.com,web,https://example.com/feed,rss,doi,en,active,\n",
                encoding="utf-8",
            )
            sources = load_sources(csv_path)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].source_name, "Test Source")


if __name__ == "__main__":
    unittest.main()
