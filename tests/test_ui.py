from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from literature_tracker.models import RawRecord
from literature_tracker.storage import SQLiteRepository
from literature_tracker.tasks import run_change_detection, run_insight_build, run_process_stage


class ArticleUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "articles.db"
        repository = SQLiteRepository(self.db_path)
        repository.initialize()
        repository.upsert_raw_records([
            RawRecord(
                source_name="Test Journal", journal_name="Test Journal",
                listing_url="https://example.com/list", article_url=f"https://example.com/{index}",
                title=f"CRISPR article {index}", authors="Frances Arnold",
                abstract="Distinctive method marker" if index == 0 else "General editing approach.",
                doi=f"10.1000/{index}", published_at="2026-10-01",
            )
            for index in range(60)
        ])
        run_process_stage(db_path=self.db_path)
        run_change_detection(db_path=self.db_path)
        run_insight_build(db_path=self.db_path)
        # AppTest does not yet serialize the new tab widget on later reruns.
        # Keep the selected tab fixed while exercising the actual search widgets.
        self.app = AppTest.from_string(
            "from pathlib import Path\nimport streamlit as st\n"
            "from literature_tracker.ui.app import render_app\n"
            "st.session_state['main_view'] = st.session_state.get('test_view', '推荐')\n"
            f"render_app(Path({str(self.db_path)!r}))",
            default_timeout=20,
        )

    def test_recommendation_page_has_only_main_views_and_bounded_cards(self) -> None:
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual([tab.label for tab in self.app.tabs], ["推荐", "搜索", "数据源"])
        self.assertEqual(len(self.app.get("link_button")), 10)
        self.assertEqual(len(self.app.metric), 0)
        self.assertIn("关注作者：Frances Arnold", " ".join(c.value for c in self.app.caption))

    def test_search_paginates_and_resets_page_after_abstract_query(self) -> None:
        self.app.session_state["test_view"] = "搜索"
        self.app.run()
        self.assertEqual(len(self.app.get("link_button")), 25)
        self.app.number_input(key="search_page").set_value(2).run()
        self.assertIn("第 2/3 页", " ".join(c.value for c in self.app.caption))
        self.app.text_input(key="article_query").set_value("Distinctive").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.get("link_button")), 1)
        self.assertEqual(self.app.number_input(key="search_page").value, 1)
        self.assertEqual(len(self.app.get("download_button")), 1)

    def test_sources_page_contains_only_status_and_source_summary(self) -> None:
        self.app.session_state["test_view"] = "数据源"
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual([m.value for m in self.app.markdown], ["#### 数据源状态", "#### Source Summary"])
        self.assertEqual(len(self.app.dataframe), 2)
        self.assertEqual(list(self.app.dataframe[0].value.columns), ["数据源", "状态", "网址"])
        self.assertEqual(len(self.app.dataframe[0].value), 131)
        self.assertIn("Microbial Biotechnology", set(self.app.dataframe[0].value["数据源"]))
        self.assertIn("IMA Fungus", set(self.app.dataframe[0].value["数据源"]))
        self.assertEqual(list(self.app.dataframe[1].value.columns), ["数据源", "文章数", "最近入库"])

    def test_source_status_is_reread_and_resorted_after_a_new_run(self) -> None:
        self.app.session_state["test_view"] = "数据源"
        self.app.run()
        repository = SQLiteRepository(self.db_path)
        failed = repository.start_crawl_run("Nature")
        repository.finish_crawl_run(failed, status="failed", item_count=0, error_message="temporary")
        self.app.run()
        self.assertEqual(self.app.dataframe[0].value.iloc[-1]["数据源"], "Nature")
        success = repository.start_crawl_run("Nature")
        repository.finish_crawl_run(success, status="success", item_count=3)
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value.iloc[0]["数据源"], "Nature")
        self.assertEqual(self.app.dataframe[0].value.iloc[0]["状态"], "正常")


if __name__ == "__main__":
    unittest.main()
