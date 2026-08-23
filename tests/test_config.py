from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.config import (
    load_author_watchlist,
    load_sources,
    load_theme_watchlist,
    strip_tracking_params,
)
from literature_tracker.paths import SOURCES_CSV, THEME_WATCHLIST_CSV


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
        self.assertEqual(len(sources), 42)
        self.assertEqual(sources[0].source_name, "合成生物学")
        self.assertEqual(sources[1].platform, "springer")
        self.assertEqual(
            [source.source_name for source in sources].count("Journal of Eukaryotic Microbiology"),
            1,
        )
        self.assertIn("sciencedirect", {source.platform for source in sources})
        self.assertIn("science", {source.platform for source in sources})
        self.assertIn("wiley", {source.platform for source in sources})
        self.assertEqual(sum(source.status == "active" for source in sources), 33)
        self.assertEqual(sum(source.status == "blocked" for source in sources), 9)
        self.assertEqual(
            {source.source_name for source in sources if source.platform == "science"},
            {
                "Science",
                "Science Advances",
                "Science Translational Medicine",
                "Science Signaling",
                "Science Immunology",
            },
        )

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

    def test_load_existing_theme_watchlist(self) -> None:
        themes = load_theme_watchlist(THEME_WATCHLIST_CSV)

        self.assertGreaterEqual(len(themes), 10)
        self.assertIn("crispr", {entry["theme_name"] for entry in themes})
        self.assertTrue(all(float(entry["score_weight"]) > 0 for entry in themes))

    def test_rule_loaders_support_weights_and_disabled_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            theme_path = Path(temp_dir) / "themes.csv"
            theme_path.write_text(
                "theme_name,keywords,score_weight,enabled\n"
                "active_theme,alpha|beta,0.2,true\n"
                "disabled_theme,gamma,0.3,false\n",
                encoding="utf-8",
            )
            author_path = Path(temp_dir) / "authors.csv"
            author_path.write_text(
                "author_name,aliases,field_hint,score_weight,enabled\n"
                "Alice Example,A. Example,synthetic_biology,0.25,true\n"
                "Bob Example,,bioprocess,0.4,false\n",
                encoding="utf-8",
            )

            themes = load_theme_watchlist(theme_path)
            authors = load_author_watchlist(author_path)

            self.assertEqual([entry["theme_name"] for entry in themes], ["active_theme"])
            self.assertEqual(themes[0]["score_weight"], 0.2)
            self.assertEqual([entry["author_name"] for entry in authors], ["Alice Example"])
            self.assertEqual(authors[0]["field_hint"], "synthetic_biology")
            self.assertEqual(authors[0]["score_weight"], 0.25)


if __name__ == "__main__":
    unittest.main()
