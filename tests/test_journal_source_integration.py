from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from literature_tracker.collectors import get_collector
from literature_tracker.collectors.crossref import CrossrefCollector
from literature_tracker.config import load_sources
from literature_tracker.paths import PROJECT_ROOT


class JournalSourceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads(
            (PROJECT_ROOT / '期刊信息源_98本_20261019.json').read_text(encoding='utf-8')
        )['items']
        cls.sources = load_sources()
        cls.by_name = {source.source_name: source for source in cls.sources}

    def test_all_98_selected_journals_are_active_and_unique(self) -> None:
        self.assertEqual(len(self.catalog), 98)
        self.assertEqual(len(self.sources), 131)
        self.assertEqual(len(self.by_name), len(self.sources))
        self.assertEqual(sum(item['tier'] == 'core' for item in self.catalog), 71)
        self.assertEqual(sum(item['tier'] == 'cross_disciplinary' for item in self.catalog), 27)
        for item in self.catalog:
            with self.subTest(journal=item['journal']):
                source = self.by_name[item['journal']]
                self.assertTrue(source.is_active)
                self.assertEqual(source.canonical_url, item['homepage_url'])
                self.assertEqual(source.dedupe_key, 'doi')
                self.assertIsNotNone(get_collector(source))

    def test_89_new_sources_use_verified_issn_apis_without_publisher_pages(self) -> None:
        new_sources = [source for source in self.sources if source.notes.startswith('98-journal catalog 2026-10-19;')]
        self.assertEqual(len(new_sources), 89)
        catalog = {item['journal']: item for item in self.catalog}
        for source in new_sources:
            with self.subTest(journal=source.source_name):
                item = catalog[source.source_name]
                self.assertEqual(source.collector_kind, 'crossref_api+pubmed')
                self.assertIsInstance(get_collector(source), CrossrefCollector)
                self.assertEqual(source.incremental_url, item['crossref_api_url'])
                match = re.fullmatch(r'https://api\.crossref\.org/journals/(\d{4}-\d{3}[\dXx])/works', source.incremental_url)
                self.assertIsNotNone(match)
                self.assertIn(match[1], item['issns'])
                self.assertTrue(item['crossref_check']['journal_identity_confirmed'])

    def test_existing_collection_routes_and_non_catalog_sources_are_preserved(self) -> None:
        self.assertEqual(self.by_name['Nature Biotechnology'].collector_kind, 'crossref_api+pubmed')
        self.assertEqual(self.by_name['Metabolic Engineering'].collector_kind, 'rss')
        self.assertEqual(self.by_name['Journal of Biological Engineering'].collector_kind, 'crossref_api')
        self.assertIn('inpress.rss', self.by_name['Trends in Microbiology'].incremental_url)
        self.assertEqual(self.by_name['Microbiology'].incremental_url, 'https://api.crossref.org/journals/1465-2080/works')
        self.assertIn('合成生物学', self.by_name)
        self.assertIn('Scientific American', self.by_name)


if __name__ == '__main__':
    unittest.main()
