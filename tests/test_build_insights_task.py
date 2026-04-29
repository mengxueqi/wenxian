from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import (
    run_change_detection,
    run_insight_build,
    run_process_stage,
)


class BuildInsightsTaskTests(unittest.TestCase):
    def test_build_insights_creates_insight_and_tracking_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/1",
                        title="CRISPR delivery for synthetic biology",
                        abstract="A synthetic biology paper about CRISPR delivery.",
                        doi="10.1000/example",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            summary = run_insight_build(db_path=db_path)
            insights = repository.fetch_paper_insights()
            tracking_items = repository.fetch_tracking_items()

            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["upserted_insights"], 1)
            self.assertEqual(summary["upserted_tracking_items"], 1)
            self.assertEqual(len(insights), 1)
            self.assertEqual(len(tracking_items), 1)
            self.assertIn("新增文献", insights[0]["summary"])
            self.assertEqual(insights[0]["score_label"], "low")
            self.assertEqual(tracking_items[0]["tracking_status"], "watchlist")

    def test_build_insights_does_not_mark_retraction_alone_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/2",
                        title="Retraction Note: Example Paper",
                        abstract="This article has been retracted.",
                        doi="10.1000/retracted",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            insights = repository.fetch_paper_insights()
            tracking_items = repository.fetch_tracking_items()

            self.assertEqual(insights[0]["score_label"], "low")
            self.assertEqual(tracking_items[0]["tracking_status"], "watchlist")
            self.assertEqual(insights[0]["metadata"]["score_factors"]["change_type"], 0.2)

    def test_build_insights_marks_author_and_theme_match_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/8",
                        title="CRISPR synthetic biology platform paper",
                        authors="Jay Keasling; Other Author",
                        abstract="A synthetic biology paper about CRISPR delivery.",
                        doi="10.1000/review-priority",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            insights = repository.fetch_paper_insights()
            tracking_items = repository.fetch_tracking_items()

            self.assertEqual(insights[0]["score_label"], "high")
            self.assertEqual(tracking_items[0]["tracking_status"], "review")
            self.assertGreaterEqual(insights[0]["metadata"]["score_factors"]["theme_hits"], 0.2)
            self.assertEqual(insights[0]["metadata"]["score_factors"]["author_hits"], 0.4)

    def test_build_insights_boosts_watchlisted_author(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/4",
                        title="Biomanufacturing platform paper",
                        authors="Jay Keasling; Other Author",
                        abstract="A platform paper.",
                        doi="10.1000/watchlisted-author",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            insights = repository.fetch_paper_insights()
            tracking_items = repository.fetch_tracking_items()

            self.assertEqual(insights[0]["metadata"]["author_hits"], ["Jay Keasling"])
            self.assertGreaterEqual(insights[0]["score"], 0.6)
            self.assertEqual(tracking_items[0]["metadata"]["author_hits"], ["Jay Keasling"])

    def test_build_insights_extracts_biomanufacturing_themes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/5",
                        title="Cytochrome P450 and KRED cascade for γ-lactone fragrances",
                        abstract="The pathway produces benzyl alcohol and 2-phenylethanol with carbonyl reductase and P450bsβ.",
                        doi="10.1000/theme-paper",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            insights = repository.fetch_paper_insights()
            themes = insights[0]["metadata"]["themes"]

            self.assertIn("p450_enzyme", themes)
            self.assertIn("kred", themes)
            self.assertIn("gamma_lactone", themes)
            self.assertIn("flavors_and_fragrances", themes)
            self.assertIn("benzyl_alcohol", themes)
            self.assertIn("phenethyl_alcohol", themes)
            self.assertIn("carbonyl_reductase", themes)
            self.assertIn("p450bs_beta", themes)

    def test_build_insights_extracts_delta_lactone_greek_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/6",
                        title="Engineered pathway for δ-lactone biosynthesis",
                        abstract="A delta lactone pathway in microbial biomanufacturing.",
                        doi="10.1000/delta-lactone",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            themes = repository.fetch_paper_insights()[0]["metadata"]["themes"]

            self.assertIn("delta_lactone", themes)

    def test_build_insights_extracts_common_theme_synonyms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/7",
                        title="CYP152A1 and keto-reductases enable flavour compound synthesis",
                        abstract="The process converts phenylmethanol to phenylethanol and delta-decalactone in a microbial cell factory.",
                        doi="10.1000/theme-synonyms",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            themes = repository.fetch_paper_insights()[0]["metadata"]["themes"]

            self.assertIn("synthetic_biology", themes)
            self.assertIn("kred", themes)
            self.assertIn("flavors_and_fragrances", themes)
            self.assertIn("benzyl_alcohol", themes)
            self.assertIn("phenethyl_alcohol", themes)
            self.assertIn("p450bs_beta", themes)
            self.assertIn("delta_lactone", themes)

    def test_build_insights_is_idempotent_on_row_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            repository = SQLiteRepository(db_path)
            repository.initialize()
            repository.upsert_raw_records(
                [
                    RawRecord(
                        source_name="Test Journal",
                        journal_name="Test Journal",
                        listing_url="https://example.com/articles",
                        article_url="https://example.com/article/3",
                        title="Example Paper",
                        abstract="Abstract text",
                        doi="10.1000/example-3",
                        collector_kind="html",
                    )
                ]
            )
            run_process_stage(db_path=db_path)
            run_change_detection(db_path=db_path)

            run_insight_build(db_path=db_path)
            first_counts = (
                len(repository.fetch_paper_insights()),
                len(repository.fetch_tracking_items()),
            )
            run_insight_build(db_path=db_path)
            second_counts = (
                len(repository.fetch_paper_insights()),
                len(repository.fetch_tracking_items()),
            )

            self.assertEqual(first_counts, second_counts)


if __name__ == "__main__":
    unittest.main()
