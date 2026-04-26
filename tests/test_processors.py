from __future__ import annotations

import unittest

from literature_tracker.models import StoredRawRecord
from literature_tracker.processors import normalize_raw_record


class ProcessorTests(unittest.TestCase):
    def test_normalize_raw_record(self) -> None:
        paper = normalize_raw_record(
            StoredRawRecord(
                id=1,
                source_name="合成生物学",
                journal_name=" 合成生物学 ",
                listing_url="https://example.com/list",
                article_url="https://example.com/article/1",
                title="  以 合成生物学 创新 赋能未来农业发展  ",
                authors="黄如平, 孙文钊，金娟, 黄如平",
                abstract="  摘要   内容 ",
                published_at="2026/04/16",
                doi="10.12211/2096-8280.2025-097",
                language="zh-CN",
                collector_kind="rss+html_detail",
                content_hash="hash123",
                metadata={"pdf_url": "https://example.com/file.pdf"},
                first_seen_at="2026-04-01T09:00:00",
                last_seen_at="2026-04-02T09:00:00",
                seen_count=2,
            )
        )

        self.assertEqual(paper.paper_key, "doi:10.12211/2096-8280.2025-097")
        self.assertEqual(paper.canonical_title, "以 合成生物学 创新 赋能未来农业发展")
        self.assertEqual(paper.normalized_authors, "黄如平; 孙文钊; 金娟")
        self.assertEqual(paper.published_at, "2026-04-16")
        self.assertEqual(paper.language, "zh")
        self.assertEqual(paper.metadata["raw_record_id"], 1)
        self.assertEqual(paper.metadata["seen_count"], 2)

    def test_normalize_raw_record_without_doi_uses_url_key(self) -> None:
        paper = normalize_raw_record(
            StoredRawRecord(
                id=2,
                source_name="Test Journal",
                journal_name="Test Journal",
                listing_url="https://example.com/list",
                article_url="https://example.com/article/2",
                title="A test paper",
            )
        )
        self.assertEqual(
            paper.paper_key,
            "url:test journal::https://example.com/article/2",
        )


if __name__ == "__main__":
    unittest.main()

