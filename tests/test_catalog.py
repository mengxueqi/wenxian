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
            doi=f"10.1000/{paper_id}", canonical_title=title, normalized_authors=authors,
            published_at=published, created_at=added, updated_at="2026-10-19T08:00:00", **extra,
        )

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

    def test_published_sort_handles_month_names_and_iso_dates(self) -> None:
        self.assertEqual([c["paper_id"] for c in select_articles(self.cards)], [1, 4, 2, 3])

    def test_export_contains_source_information_and_full_abstract(self) -> None:
        rows = article_export_rows(select_articles(self.cards, query="Arnold"))
        self.assertEqual(rows[0]["作者"], "Frances Arnold")
        self.assertEqual(rows[0]["摘要"], "A new ketoreductase method.")
        self.assertNotIn("tracking_status", rows[0])


if __name__ == "__main__":
    unittest.main()
