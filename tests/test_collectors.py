from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from literature_tracker.collectors.base import BaseCollector, CollectorError
from literature_tracker.models import RawRecord, SourceConfig


class DummyCollector(BaseCollector):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.html = html

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        return []

    def fetch_soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.html, "html.parser")


class CollectorHelperTests(unittest.TestCase):
    def test_detects_springer_client_challenge(self) -> None:
        html = """
        <html>
          <head><title>Client Challenge</title></head>
          <body>JavaScript is disabled in your browser.</body>
        </html>
        """
        with self.assertRaises(CollectorError):
            BaseCollector.raise_for_known_blockers(html, "https://link.springer.com/journal/13036")

    def test_extracts_citation_meta_values(self) -> None:
        html = """
        <html>
          <head>
            <meta name="citation_title" content="以合成生物学创新，赋能未来农业发展" />
            <meta name="citation_doi" content="10.12211/2096-8280.2025-097" />
            <meta name="Description" content="摘要内容" />
          </head>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(
            BaseCollector.meta_contents(soup, "citation_title"),
            ["以合成生物学创新，赋能未来农业发展"],
        )
        self.assertEqual(
            BaseCollector.meta_contents(soup, "citation_doi"),
            ["10.12211/2096-8280.2025-097"],
        )
        self.assertEqual(BaseCollector.meta_contents(soup, "description"), ["摘要内容"])

    def test_extracts_doi_from_url(self) -> None:
        value = "https://synbioj.cip.com.cn/CN/10.12211/2096-8280.2025-097"
        self.assertEqual(
            BaseCollector.extract_doi(value),
            "10.12211/2096-8280.2025-097",
        )

    def test_enrich_with_citation_meta_reads_multiple_citation_author_values(self) -> None:
        html = """
        <html>
          <head>
            <meta name="citation_title" content="Example Springer Paper" />
            <meta name="citation_author" content="Alice Example" />
            <meta name="citation_author" content="Bob Example" />
            <meta name="citation_doi" content="10.1007/example" />
          </head>
        </html>
        """
        collector = DummyCollector(html)
        record = RawRecord(
            source_name="Springer Source",
            journal_name="Springer Source",
            listing_url="https://example.com/articles",
            article_url="https://example.com/article/1",
            title="Placeholder",
            collector_kind="html",
        )

        enriched = collector.enrich_with_citation_meta(record)

        self.assertEqual(enriched.title, "Example Springer Paper")
        self.assertEqual(enriched.authors, "Alice Example; Bob Example")
        self.assertEqual(enriched.doi, "10.1007/example")


if __name__ == "__main__":
    unittest.main()
