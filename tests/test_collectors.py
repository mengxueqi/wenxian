from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from literature_tracker.collectors import get_collector
from literature_tracker.collectors.base import BaseCollector, CollectorError
from literature_tracker.collectors.cip import CIPCollector
from literature_tracker.collectors.generic import GenericJournalCollector
from literature_tracker.collectors.springer import SpringerCollector
from literature_tracker.models import RawRecord, SourceConfig


class DummyCollector(BaseCollector):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.html = html

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        return []

    def fetch_soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.html, "html.parser")


class DummyGenericJournalCollector(GenericJournalCollector):
    def __init__(self, payloads: dict[str, bytes]) -> None:
        super().__init__()
        self.payloads = payloads

    def fetch_bytes(self, url: str) -> bytes:
        return self.payloads[url]

    def fetch_html(self, url: str) -> str:
        return self.payloads[url].decode("utf-8")

    def enrich_with_citation_meta(self, record: RawRecord) -> RawRecord:
        return record

    def _fetch_openalex_work(self, record: RawRecord) -> dict[str, object] | None:
        return None

    def _fetch_pubmed_record(self, record: RawRecord) -> dict[str, object] | None:
        return None


class DummyOpenAlexGenericJournalCollector(DummyGenericJournalCollector):
    def __init__(self, payloads: dict[str, bytes], work: dict[str, object]) -> None:
        super().__init__(payloads)
        self.work = work

    def _fetch_openalex_work(self, record: RawRecord) -> dict[str, object] | None:
        return self.work


class DummyPubMedGenericJournalCollector(DummyGenericJournalCollector):
    def __init__(self, payloads: dict[str, bytes], pubmed_record: dict[str, object]) -> None:
        super().__init__(payloads)
        self.pubmed_record = pubmed_record

    def _fetch_pubmed_record(self, record: RawRecord) -> dict[str, object] | None:
        return self.pubmed_record


class DummyFailingDetailCollector(DummyGenericJournalCollector):
    def enrich_with_citation_meta(self, record: RawRecord) -> RawRecord:
        raise CollectorError("detail page blocked")


class DummyCrossrefSpringerCollector(SpringerCollector):
    def __init__(self, items: list[dict[str, object]]) -> None:
        super().__init__()
        self.items = items

    def _fetch_crossref_items(
        self,
        url: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        return self.items[: limit or None]


class _FakeResponse:
    status_code = 200
    text = "<title>Client Challenge</title>JavaScript is disabled in your browser"
    content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def get(self, url: str, timeout: int) -> _FakeResponse:
        return _FakeResponse()


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

    def test_fetch_bytes_rejects_http_200_client_challenge(self) -> None:
        collector = DummyCollector("")
        collector.session = _FakeSession()

        with self.assertRaises(CollectorError):
            collector.fetch_bytes("https://www.nature.com/example.rss")

    def test_extracts_citation_meta_values(self) -> None:
        html = """
        <html>
          <head>
            <meta name="citation_title" content="以合成生物学创新，赋能未来农业发展" />
            <meta name="citation_doi" content="10.12211/2096-8280.2025-097" />
            <meta name="citation_keywords" content="CRISPR; synthetic biology" />
            <meta name="dc.keywords" content="genome editing, metabolic engineering" />
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
        self.assertEqual(
            BaseCollector.keyword_contents(soup),
            ["CRISPR", "synthetic biology", "genome editing", "metabolic engineering"],
        )

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
            <meta name="description" content="Short abstract." />
            <meta name="citation_abstract" content="A much longer abstract that should be preferred." />
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
        self.assertEqual(enriched.abstract, "A much longer abstract that should be preferred.")
        self.assertEqual(enriched.doi, "10.1007/example")

    def test_abstract_contents_extracts_body_abstract(self) -> None:
        html = """
        <html>
          <head>
            <meta name="description" content="Short abstract." />
          </head>
          <body>
            <section id="Abs1">
              <h2>Abstract</h2>
              <div id="Abs1-content" class="c-article-section__content">
                <p>This is the full abstract text with more detail than the metadata.</p>
              </div>
            </section>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")

        self.assertEqual(
            BaseCollector.abstract_contents(soup)[0],
            "This is the full abstract text with more detail than the metadata.",
        )

    def test_cip_abstract_contents_extracts_magtech_panel_abstract(self) -> None:
        html = """
        <html>
          <head>
            <meta name="Description" xml:lang="en" content="High-throughput genome editing is an effective approach to rapidly ana..." />
          </head>
          <body>
            <div id="collapseOne">
              <div class="panel-body line-height text-justify">
                <p><strong>摘要： </strong><p>高通量基因组编辑是快速分析大量基因突变功能和进行遗传育种的有效方法。本文主要介绍基于CRISPR系统的高通量基因组编辑方法。</p></p>
                <form>
                  <p><strong>关键词: </strong>CRISPR, 基因组编辑</p>
                </form>
              </div>
            </div>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")

        self.assertEqual(
            CIPCollector.abstract_contents(soup)[0],
            "高通量基因组编辑是快速分析大量基因突变功能和进行遗传育种的有效方法。本文主要介绍基于CRISPR系统的高通量基因组编辑方法。",
        )


class GenericJournalCollectorTests(unittest.TestCase):
    def test_rss_subdomain_is_recognized_as_feed(self) -> None:
        self.assertTrue(
            GenericJournalCollector._looks_like_feed_url(
                "https://rss.sciencedirect.com/publication/science/10967176"
            )
        )

    def test_feed_only_source_skips_detail_enrichment(self) -> None:
        feed_url = "https://example.com/feed.xml"
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Feed-only paper</title>
              <link>https://example.com/article/1</link>
              <description>Abstract from the feed.</description>
            </item>
          </channel>
        </rss>
        """
        source = SourceConfig(
            source_name="Science",
            canonical_url="https://example.com",
            platform="science",
            incremental_url=feed_url,
            collector_kind="rss",
        )
        collector = DummyFailingDetailCollector({feed_url: feed})

        records = collector.collect(source)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].abstract, "from the feed.")
        self.assertNotIn("enrichment_status", records[0].metadata)

    def test_detail_enrichment_failure_is_preserved_as_record_warning(self) -> None:
        feed_url = "https://example.com/feed.xml"
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Example paper</title>
              <link>https://example.com/article/1</link>
            </item>
          </channel>
        </rss>
        """
        source = SourceConfig(
            source_name="Test Journal",
            canonical_url="https://example.com",
            platform="nature",
            incremental_url=feed_url,
            collector_kind="rss+html_detail",
        )
        collector = DummyFailingDetailCollector({feed_url: feed})

        records = collector.collect(source)

        self.assertEqual(records[0].metadata["enrichment_status"], "failed")
        self.assertIn("detail page blocked", records[0].metadata["enrichment_error"])

    def test_collects_rss_entries_and_cleans_tracking_urls(self) -> None:
        feed_url = "https://rss.sciencedirect.com/publication/science/10967176"
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>ScienceDirect Publication: Metabolic Engineering</title>
            <item>
              <title><![CDATA[<em>De novo</em> biosynthesis]]></title>
              <link>https://www.sciencedirect.com/science/article/pii/S1096717626000601?dgcid=rss_sd_all</link>
              <description><![CDATA[
                <p>Publication date: July 2026</p>
                <p><b>Source:</b> Metabolic Engineering</p>
                <p>Author(s): Alice Example, Bob Example</p>
              ]]></description>
            </item>
          </channel>
        </rss>
        """
        source = SourceConfig(
            source_name="Metabolic Engineering",
            canonical_url="https://www.sciencedirect.com/journal/metabolic-engineering",
            platform="sciencedirect",
            incremental_url=feed_url,
            collector_kind="rss+html_detail",
        )
        collector = DummyGenericJournalCollector({feed_url: feed})

        records = collector.collect(source)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "De novo biosynthesis")
        self.assertEqual(
            records[0].article_url,
            "https://www.sciencedirect.com/science/article/pii/S1096717626000601",
        )
        self.assertEqual(records[0].authors, "Alice Example; Bob Example")
        self.assertEqual(records[0].published_at, "July 2026")
        self.assertEqual(records[0].abstract, "")

    def test_sciencedirect_records_can_be_enriched_from_openalex(self) -> None:
        feed_url = "https://rss.sciencedirect.com/publication/science/10967176"
        title = "Orthogonal quorum sensing circuits enable dynamic regulation in Escherichia coli"
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>{title}</title>
              <link>https://www.sciencedirect.com/science/article/pii/S1096717626000431?dgcid=rss_sd_all</link>
            </item>
          </channel>
        </rss>
        """.encode()
        work = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1016/j.ymben.2026.03.009",
            "display_name": title,
            "abstract_inverted_index": {
                "Orthogonal": [0],
                "circuits": [1],
                "improve": [2],
                "regulation.": [3],
            },
            "keywords": [
                {"display_name": "Quorum sensing", "score": 0.86},
                {"display_name": "Synthetic biology", "score": 0.35},
            ],
        }
        source = SourceConfig(
            source_name="Metabolic Engineering",
            canonical_url="https://www.sciencedirect.com/journal/metabolic-engineering",
            platform="sciencedirect",
            incremental_url=feed_url,
            collector_kind="rss+html_detail",
        )
        collector = DummyOpenAlexGenericJournalCollector({feed_url: feed}, work)

        records = collector.collect(source)

        self.assertEqual(records[0].doi, "10.1016/j.ymben.2026.03.009")
        self.assertEqual(
            records[0].metadata["keywords"],
            ["Quorum sensing", "Synthetic biology"],
        )
        self.assertEqual(records[0].abstract, "Orthogonal circuits improve regulation.")

    def test_sciencedirect_records_can_be_enriched_from_pubmed(self) -> None:
        feed_url = "https://rss.sciencedirect.com/publication/science/10967176"
        title = "Orthogonal quorum sensing circuits enable dynamic regulation in Escherichia coli"
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>{title}</title>
              <link>https://www.sciencedirect.com/science/article/pii/S1096717626000431?dgcid=rss_sd_all</link>
            </item>
          </channel>
        </rss>
        """.encode()
        pubmed_record = {
            "pmid": "41850580",
            "doi": "10.1016/j.ymben.2026.03.009",
            "title": f"{title}.",
            "abstract": "Engineers have effectively employed quorum sensing to regulate gene expression.",
            "keywords": [
                "CRISPRi",
                "Dynamic regulation",
                "Quorum sensing",
                "Synthetic biology",
            ],
        }
        source = SourceConfig(
            source_name="Metabolic Engineering",
            canonical_url="https://www.sciencedirect.com/journal/metabolic-engineering",
            platform="sciencedirect",
            incremental_url=feed_url,
            collector_kind="rss+html_detail",
        )
        collector = DummyPubMedGenericJournalCollector({feed_url: feed}, pubmed_record)

        records = collector.collect(source)

        self.assertEqual(records[0].doi, "10.1016/j.ymben.2026.03.009")
        self.assertEqual(
            records[0].metadata["keywords"],
            ["CRISPRi", "Dynamic regulation", "Quorum sensing", "Synthetic biology"],
        )
        self.assertEqual(
            records[0].abstract,
            "Engineers have effectively employed quorum sensing to regulate gene expression.",
        )
        self.assertEqual(records[0].metadata["pubmed_id"], "41850580")

    def test_collects_oup_rss_abstract_and_doi(self) -> None:
        feed_url = "https://academic.oup.com/rss/site_5419/advanceAccess_3280.xml"
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Synthetic Biology Advance Access</title>
            <item>
              <title>Off-target detection of CRISPR-Cas9 nuclease in vitro with CROFT-Seq</title>
              <link>https://academic.oup.com/synbio/advance-article/doi/10.1093/synbio/ysag006/8661338?rss=1</link>
              <pubDate>Thu, 23 Apr 2026 00:00:00 GMT</pubDate>
              <prism:doi xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">10.1093/synbio/ysag006</prism:doi>
              <description><![CDATA[
                <span class="paragraphSection"><div class="boxTitle">Abstract</div>Programmable nucleases need careful off-target detection.</span>
              ]]></description>
            </item>
          </channel>
        </rss>
        """
        source = SourceConfig(
            source_name="Synthetic Biology",
            canonical_url="https://academic.oup.com/synbio",
            platform="oup",
            incremental_url=feed_url,
            collector_kind="rss+rss_current_issue_fallback+html_detail",
        )
        collector = DummyGenericJournalCollector({feed_url: feed})

        records = collector.collect(source, limit=1)

        self.assertEqual(records[0].doi, "10.1093/synbio/ysag006")
        self.assertEqual(
            records[0].article_url,
            "https://academic.oup.com/synbio/advance-article/doi/10.1093/synbio/ysag006/8661338",
        )
        self.assertEqual(
            records[0].abstract,
            "Programmable nucleases need careful off-target detection.",
        )

    def test_filters_html_listing_by_platform(self) -> None:
        listing_url = "https://www.nature.com/nrmicro/articles"
        html = b"""
        <html>
          <body>
            <a href="/articles/s41579-026-01300-3">Bacterial allies against food anaphylaxis</a>
            <a href="/articles/not-a-paper">View all articles</a>
          </body>
        </html>
        """
        source = SourceConfig(
            source_name="Nature Reviews Microbiology",
            canonical_url="https://www.nature.com/nrmicro/",
            platform="nature",
            incremental_url=listing_url,
            collector_kind="html_articles",
        )
        collector = DummyGenericJournalCollector({listing_url: html})

        records = collector.collect(source)

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].article_url,
            "https://www.nature.com/articles/s41579-026-01300-3",
        )

    def test_cell_platform_accepts_fulltext_links_across_journals(self) -> None:
        source = SourceConfig(
            source_name="Molecular Cell",
            canonical_url="https://www.cell.com/molecular-cell/home",
            platform="cell",
            incremental_url="https://www.cell.com/molecular-cell/inpress.rss",
            collector_kind="rss+rss_current_fallback+html_detail",
        )

        self.assertTrue(
            GenericJournalCollector._is_article_href(
                source,
                "/molecular-cell/fulltext/S1097-2765(26)00001-2",
            )
        )

    def test_registry_supports_generic_journal_platforms(self) -> None:
        source = SourceConfig(
            source_name="Yeast",
            canonical_url="https://onlinelibrary.wiley.com/journal/10970061",
            platform="wiley",
            incremental_url="https://onlinelibrary.wiley.com/action/showFeed?jc=10970061&type=etoc&feed=rss",
            collector_kind="rss+html_detail",
        )

        self.assertIsInstance(get_collector(source), GenericJournalCollector)

        science_source = SourceConfig(
            source_name="Science",
            canonical_url="https://www.science.org/journal/science",
            platform="science",
            incremental_url=(
                "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science"
            ),
            collector_kind="rss+html_detail",
        )
        self.assertIsInstance(get_collector(science_source), GenericJournalCollector)


class SpringerCollectorTests(unittest.TestCase):
    def test_collects_crossref_records_without_opening_springer_pages(self) -> None:
        source = SourceConfig(
            source_name="Journal of Biological Engineering",
            canonical_url="https://link.springer.com/journal/13036",
            platform="springer",
            incremental_url="https://api.crossref.org/journals/1754-1611/works",
            collector_kind="crossref_api",
        )
        collector = DummyCrossrefSpringerCollector(
            [
                {
                    "DOI": "10.1186/s13036-026-00744-8",
                    "URL": "https://doi.org/10.1186/s13036-026-00744-8",
                    "title": ["A precision bioengineering study"],
                    "author": [
                        {"given": "Alice", "family": "Example"},
                        {"given": "Bob", "family": "Researcher"},
                    ],
                    "published-online": {"date-parts": [[2026, 8, 5]]},
                    "abstract": "<jats:p>Abstract A structured abstract.</jats:p>",
                    "subject": ["Biomedical Engineering", "Biotechnology"],
                    "type": "journal-article",
                }
            ]
        )

        records = collector.collect(source)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].doi, "10.1186/s13036-026-00744-8")
        self.assertEqual(records[0].authors, "Alice Example; Bob Researcher")
        self.assertEqual(records[0].published_at, "2026-08-05")
        self.assertEqual(records[0].abstract, "A structured abstract.")
        self.assertEqual(records[0].metadata["external_metadata_source"], "crossref")
        self.assertEqual(
            records[0].metadata["keywords"],
            ["Biomedical Engineering", "Biotechnology"],
        )


if __name__ == "__main__":
    unittest.main()
