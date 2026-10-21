from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import Mock

from literature_tracker.catalog import article_export_rows, build_catalog, select_articles, source_summary
from literature_tracker.models import StoredPaper
from literature_tracker.storage import SQLiteRepository


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        repository = Mock(spec=SQLiteRepository)
        repository.fetch_papers.return_value = [
            self.paper(1, "Enzyme engineering", "January 2027", "2026-10-10T08:00:00",
                       authors="Frances Arnold", abstract="A new ketoreductase method.",
                       metadata={"keywords": ["Biocatalysis"], "observed_sources": ["Journal B"]}),
            self.paper(2, "Unrelated high score", "2026-10-15", "2026-10-12T08:00:00"),
            self.paper(3, "Older matching article", "2026-01-01", "2026-01-01T08:00:00"),
            self.paper(4, "Not yet scored", "2026-10-16", "2026-10-16T08:00:00"),
        ]
        repository.fetch_tracking_items.return_value = [
            {"paper_id": 1, "priority_score": 0.8, "metadata": {"themes": ["kred"], "author_hits": ["Frances Arnold"]}},
            {"paper_id": 2, "priority_score": 0.99, "metadata": {}},
            {"paper_id": 3, "priority_score": 0.9, "metadata": {"themes": ["kred"]}},
        ]
        self.cards = build_catalog(repository)
        repository.fetch_paper_changes.assert_not_called()
        repository.fetch_paper_insights.assert_not_called()

    @staticmethod
    def paper(paper_id, title, published, added, **extra) -> StoredPaper:
        authors = extra.pop("authors", "")
        return StoredPaper(
            id=paper_id, raw_record_id=paper_id, paper_key=f"paper:{paper_id}",
            source_name="Journal A", journal_name="Journal A", article_url=f"https://example.com/{paper_id}",
            doi=extra.pop("doi", f"10.1000/{paper_id}"), canonical_title=title, normalized_authors=authors,
            published_at=published, created_at=added, updated_at="2026-10-19T08:00:00", **extra,
        )

    @staticmethod
    def matched_cards(papers) -> list[dict]:
        repository = Mock(spec=SQLiteRepository)
        repository.fetch_papers.return_value = papers
        repository.fetch_tracking_items.return_value = [
            {"paper_id": paper.id, "priority_score": 0.9,
             "metadata": {"themes": ["p450_enzyme"]}}
            for paper in papers
        ]
        return build_catalog(repository)

    def test_search_covers_author_abstract_doi_keywords_and_combined_terms(self) -> None:
        for query in ("ARNOLD", "ketoreductase", "10.1000/1", "biocatalysis", "Arnold ketoreductase"):
            self.assertEqual([c["paper_id"] for c in select_articles(self.cards, query=query)], [1])
        self.assertEqual(select_articles(self.cards, query="Arnold nonexistent"), [])

    def test_recommendations_require_interest_match_and_recent_first_entry(self) -> None:
        result = select_articles(self.cards, recommended_only=True, days=30, now=date(2026, 10, 19), sort_by="priority_desc")
        self.assertEqual([c["paper_id"] for c in result], [1])
        self.assertIn("酮还原酶", result[0]["recommendation_reason"])
        self.assertIn("Frances Arnold", result[0]["recommendation_reason"])
        all_matches = select_articles(self.cards, recommended_only=True, sort_by="priority_desc")
        self.assertEqual([c["paper_id"] for c in all_matches], [3, 1])

    def test_search_includes_unscored_papers_and_merged_sources(self) -> None:
        self.assertEqual(len(select_articles(self.cards)), 4)
        self.assertEqual([c["paper_id"] for c in select_articles(self.cards, source_name="Journal B")], [1])
        counts = {r["数据源"]: r["文章数"] for r in source_summary(self.cards)}
        self.assertEqual(counts, {"Journal A": 4, "Journal B": 1})

    def test_olep_original_remains_recommended_when_corrigendum_scores_higher(self) -> None:
        title = (
            "Improved catalytic efficiency of P450 OleP for converting lithocholic acid "
            "into murideoxycholic and ursodeoxycholic acids through semi-rational and rational design"
        )
        cards = self.matched_cards([
            self.paper(10, title, "2027-01", "2026-10-19T15:23:09",
                       doi="10.1016/j.synbio.2026.05.015", metadata={"is_corrected": True}),
            self.paper(11, f"Corrigendum to “{title}” [Synth Syst Biotechnol 15 (2027) 94-104]",
                       "2027-04", "2026-10-19T15:23:09", doi="10.1016/j.synbio.2026.08.007"),
        ])
        cards[0]["priority_score"] = 0.65
        cards[1]["priority_score"] = 0.91
        recommended = select_articles(cards, recommended_only=True, days=30,
                                      now=date(2026, 10, 21), sort_by="priority_desc")
        self.assertEqual([card["doi"] for card in recommended], ["10.1016/j.synbio.2026.05.015"])
        self.assertEqual([card["paper_id"] for card in select_articles(cards, query="10.1016/j.synbio.2026.08.007")], [11])

    def test_notice_titles_are_excluded_without_matching_scientific_correction_terms(self) -> None:
        notices = [
            "Correction", "Correction: CRISPR engineering", "Correction to: Original study",
            "Correction for Smith et al., Original study", "Author Correction: Original study",
            "Publisher Correction: Original study", "Corrigendum to Original study",
            "Erratum for the Research Article Original study", "Retraction Note: Original study",
            'Retraction of the Research Article “Original study”', "Retraction notice to Original study",
            "Retraction of: Original study", 'Retraction of “Original study”',
            "Withdrawal notice: Original study", "WITHDRAWN: Original study",
            "WITHDRAWN BY AUTHOR: Original study", "RETRACTED: Original study",
            "Notice of Retraction: Original study", "Editorial Expression of Concern: Original study",
            "更正通知：《原论文》", "勘误：原论文", "撤稿声明：原论文",
            "关于《原论文》的更正声明", " [Correction] Original study",
            "<b>Author Correction:</b> Original study",
        ]
        research = [
            "Correction of pathogenic mutations by CRISPR",
            "Error correction improves DNA sequencing",
            "P450 engineering: correction of catalytic defects",
            "Withdrawal effects on microbial communities",
            "Retraction of growth cones during development",
            "更正基因突变的编辑方法",
        ]
        papers = [
            self.paper(index, title, "2026-10-20", "2026-10-20T08:00:00",
                       abstract="Correction and retraction are discussed in the study.")
            for index, title in enumerate([*notices, *research], start=1)
        ]
        cards = self.matched_cards(papers)
        recommended = select_articles(cards, recommended_only=True)
        self.assertEqual({card["title"] for card in recommended}, set(research))
        self.assertEqual(len(select_articles(cards)), len(papers))

    def test_known_retracted_original_is_not_recommended(self) -> None:
        cards = self.matched_cards([
            self.paper(index, "P450 enzyme engineering", "2026-10-20", "2026-10-20T08:00:00",
                       metadata={"is_retracted": flag})
            for index, flag in enumerate([True, "true", "1", False, "false"], start=1)
        ])
        self.assertEqual({card["paper_id"] for card in select_articles(cards, recommended_only=True)}, {4, 5})

    def test_published_sort_handles_month_names_and_iso_dates(self) -> None:
        self.assertEqual([c["paper_id"] for c in select_articles(self.cards)], [1, 4, 2, 3])

    def test_export_contains_source_information_and_full_abstract(self) -> None:
        rows = article_export_rows(select_articles(self.cards, query="Arnold"))
        self.assertEqual(rows[0]["作者"], "Frances Arnold")
        self.assertEqual(rows[0]["摘要"], "A new ketoreductase method.")
        self.assertNotIn("tracking_status", rows[0])


if __name__ == "__main__":
    unittest.main()
