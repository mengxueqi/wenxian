from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.catalog import THEME_LABELS
from literature_tracker.config import load_author_watchlist, load_theme_watchlist
from literature_tracker.insights.build import _extract_author_hits, _extract_themes
from literature_tracker.models import RawRecord, StoredPaper
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_change_detection, run_insight_build, run_process_stage


NEW_THEMES = {
    'sclareol', 'macrocyclic_lactone', 'squalene', 'heme',
    'directed_evolution', 'lactone_product_extraction',
}
NEW_AUTHORS = {'王喜庆', '姜岷', '信丰学', '章文明'}


class WatchlistExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.themes = load_theme_watchlist()
        self.authors = load_author_watchlist()

    @staticmethod
    def paper(title='', abstract='', authors='', keywords=None) -> StoredPaper:
        return StoredPaper(
            id=1, raw_record_id=1, paper_key='test:watchlist',
            source_name='Test Journal', journal_name='Test Journal',
            article_url='https://example.com/watchlist', doi='10.1000/watchlist',
            canonical_title=title, normalized_authors=authors, abstract=abstract,
            published_at='2026-10-21', metadata={'keywords': keywords or []},
        )

    def test_config_has_18_themes_and_104_authors_with_existing_weights(self) -> None:
        self.assertEqual(len(self.themes), 18)
        self.assertEqual(len({rule['theme_name'] for rule in self.themes}), 18)
        self.assertEqual(len(self.authors), 104)
        self.assertEqual(len({rule['author_name'] for rule in self.authors}), 104)
        self.assertTrue(NEW_THEMES <= {rule['theme_name'] for rule in self.themes})
        self.assertTrue(NEW_AUTHORS <= {rule['author_name'] for rule in self.authors})
        self.assertTrue(all(rule['score_weight'] == 0.15 for rule in self.themes))
        self.assertTrue(all(rule['score_weight'] == 0.4 for rule in self.authors))
        self.assertTrue(NEW_THEMES <= THEME_LABELS.keys())

    def test_new_topics_match_chinese_and_english_in_each_searchable_field(self) -> None:
        cases = [
            ('Sclareol production', '香紫苏醇生物合成', 'sclareol'),
            ('Macrocyclic lactones and macrolides', '大环内酯发酵生产', 'macrocyclic_lactone'),
            ('Squalene biosynthesis', '角鲨烯合成', 'squalene'),
            ('Haem and hemin metabolism', '血红素生物合成', 'heme'),
            ('Directed evolution of enzymes', '酶的定向进化', 'directed_evolution'),
            ('Recovery of gamma-decalactone from broth', '内酯产物提取与回收', 'lactone_product_extraction'),
        ]
        for english, chinese, theme in cases:
            for paper in (self.paper(title=english), self.paper(abstract=chinese), self.paper(keywords=[english])):
                with self.subTest(topic=theme, title=paper.canonical_title, abstract=paper.abstract):
                    self.assertIn(theme, _extract_themes(paper, self.themes))

    def test_new_english_keywords_do_not_match_inside_unrelated_words(self) -> None:
        self.assertNotIn('heme', _extract_themes(self.paper(title='A scheme for fermentation'), self.themes))
        self.assertNotIn('heme', _extract_themes(self.paper(title='Hemerythrin characterization'), self.themes))
        self.assertNotIn('sclareol', _extract_themes(self.paper(title='Sclareolide production'), self.themes))
        self.assertIn('heme', _extract_themes(self.paper(title='HEME-dependent catalysis'), self.themes))
        self.assertIn('heme', _extract_themes(self.paper(title='血红素B生物合成'), self.themes))
        self.assertIn('sclareol', _extract_themes(self.paper(title='Sclareol-derived products'), self.themes))

    def test_lactone_extraction_requires_a_product_and_a_recovery_operation(self) -> None:
        for text in ('DNA extraction from yeast', 'Lactone biosynthesis in bacteria',
                     'Purification of lactonase', 'Macrolide biosynthesis'):
            with self.subTest(text=text):
                self.assertNotIn('lactone_product_extraction', _extract_themes(self.paper(title=text), self.themes))
        self.assertIn('lactone_product_extraction', _extract_themes(
            self.paper(title='Gamma-decalactone fermentation', abstract='In situ product recovery improves yield.'), self.themes,
        ))
        self.assertIn('lactone_product_extraction', _extract_themes(
            self.paper(title='Macrolide extraction from broth'), self.themes,
        ))

    def test_new_authors_match_full_names_order_and_hyphen_variants(self) -> None:
        cases = [
            ('王喜庆; 姜岷; 信丰学; 章文明', NEW_AUTHORS),
            ('Xiqing Wang; Min Jiang; Fengxue Xin; Wenming Zhang', NEW_AUTHORS),
            ('Xi-Qing Wang; Jiang Min; Feng-Xue Xin; Wen-Ming Zhang', NEW_AUTHORS),
            ('Wang Xiqing; Xin Fengxue; Zhang Wenming', {'王喜庆', '信丰学', '章文明'}),
            ('Wangxiqing', {'王喜庆'}),
        ]
        for names, expected in cases:
            with self.subTest(names=names):
                hits = set(_extract_author_hits(self.paper(authors=names), self.authors))
                self.assertEqual(hits & NEW_AUTHORS, expected)
        hits = _extract_author_hits(self.paper(authors='X. Wang; M. Jiang; F. Xin; W. Zhang; Qing Wang'), self.authors)
        self.assertFalse(NEW_AUTHORS.intersection(hits))

    def test_new_rules_flow_through_processing_and_recommendation_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'watchlist.db'
            repository = SQLiteRepository(db)
            repository.initialize()
            repository.upsert_raw_records([RawRecord(
                source_name='Test Journal', journal_name='Test Journal',
                listing_url='https://example.com/list', article_url='https://example.com/watchlist',
                title='Directed evolution for sclareol and squalene production',
                abstract='Heme biosynthesis and macrolactone extraction from fermentation broth.',
                authors='Xi-Qing Wang; Min Jiang; Feng-Xue Xin; Wenming Zhang', doi='10.1000/watchlist',
            )])
            run_process_stage(db_path=db)
            run_change_detection(db_path=db)
            run_insight_build(db_path=db)
            item = repository.fetch_tracking_items()[0]
            self.assertTrue(NEW_THEMES <= set(item['metadata']['themes']))
            self.assertEqual(set(item['metadata']['author_hits']) & NEW_AUTHORS, NEW_AUTHORS)
            self.assertEqual(item['metadata']['score_factors']['theme_hits'], 0.4)
            self.assertEqual(item['metadata']['score_factors']['author_hits'], 0.4)


if __name__ == '__main__':
    unittest.main()
