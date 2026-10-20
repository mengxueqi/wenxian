from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from literature_tracker.collectors import get_collector
from literature_tracker.collectors.crossref import CrossrefCollector
from literature_tracker.collectors.metadata_api import MetadataClient
from literature_tracker.models import SourceConfig


def response(content, status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result.url = "https://api.example.org"
    result._content = content if isinstance(content, bytes) else json.dumps(content).encode()
    result.headers.update(headers or {})
    return result


class MetadataClientTests(unittest.TestCase):
    def test_successful_responses_are_cached(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            session = Mock()
            session.get.return_value = response({"message": "article"})
            client = MetadataClient(session, Path(folder), min_interval=0)
            first = client.get("https://api.example.org", params={"rows": 1})
            second = client.get("https://api.example.org", params={"rows": 1})
            self.assertEqual(first.json(), second.json())
            session.get.assert_called_once()

    def test_rate_limit_retries_after_server_delay(self) -> None:
        session = Mock()
        session.get.side_effect = [response({}, 429, {"Retry-After": "2"}), response({"ok": True})]
        with patch("literature_tracker.collectors.metadata_api.time.sleep") as sleep:
            result = MetadataClient(session, None, min_interval=0).get("https://api.example.org", params={})
        self.assertTrue(result.json()["ok"])
        sleep.assert_called_once_with(2)

    def test_long_server_cooldown_is_deferred_without_an_early_retry(self) -> None:
        session = Mock()
        session.get.return_value = response({}, 429, {"Retry-After": "3600"})
        with self.assertRaises(requests.HTTPError):
            MetadataClient(session, None, min_interval=0).get("https://api.example.org", params={})
        session.get.assert_called_once()

    def test_transient_connection_error_is_retried(self) -> None:
        session = Mock()
        session.get.side_effect = [requests.Timeout("temporary"), response({"ok": True})]
        with patch("literature_tracker.collectors.metadata_api.time.sleep"):
            result = MetadataClient(session, None, min_interval=0).get("https://api.example.org", params={})
        self.assertTrue(result.json()["ok"])
        self.assertEqual(session.get.call_count, 2)


class CrossrefPubMedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SourceConfig(
            "Nature Biotechnology", "https://www.nature.com/nbt/", "nature",
            "https://api.crossref.org/journals/1087-0156/works", "crossref_api+pubmed",
        )
        self.work = {
            "title": ["CRISPR editing advances"], "DOI": "10.1000/example", "URL": "https://doi.org/10.1000/example",
            "author": [{"given": "A", "family": "Researcher"}], "published": {"date-parts": [[2026, 10, 1]]},
        }

    def test_factory_uses_metadata_collector_without_changing_publisher_platform(self) -> None:
        self.assertIsInstance(get_collector(self.source), CrossrefCollector)
        self.assertEqual(self.source.platform, "nature")

    def test_missing_abstract_is_filled_by_a_matching_doi_and_title(self) -> None:
        session = Mock(headers={})
        session.get.side_effect = [
            response({"message": {"items": [self.work]}}),
            response({"esearchresult": {"idlist": ["123"]}}),
            response(b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><Article>
                <ArticleTitle>CRISPR editing advances</ArticleTitle><Abstract><AbstractText>Verified abstract.</AbstractText></Abstract>
                </Article><KeywordList><Keyword>Genome engineering</Keyword></KeywordList></MedlineCitation>
                <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/example</ArticleId>
                <ArticleId IdType="pubmed">123</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''),
        ]
        collector = CrossrefCollector(session, cache_dir=None)
        collector.api.min_interval = 0
        records = collector.collect(self.source)
        self.assertEqual(records[0].abstract, "Verified abstract.")
        self.assertEqual(records[0].metadata["abstract_source"], "pubmed")
        self.assertEqual(records[0].metadata["pubmed_id"], "123")
        self.assertEqual(records[0].authors, "A Researcher")
        self.assertTrue(all("nature.com" not in call.args[0] for call in session.get.call_args_list))
        self.assertIn('[AID]', session.get.call_args_list[1].kwargs["params"]["term"])

    def test_mismatched_doi_or_title_cannot_replace_abstract(self) -> None:
        collector = CrossrefCollector(cache_dir=None)
        with patch.object(collector, "_fetch_crossref_items", return_value=[self.work]):
            for matches in (
                {"10.1000/wrong": {"doi": "10.1000/wrong", "title": self.work["title"][0], "abstract": "Wrong work"}},
                {"10.1000/example": {"doi": "10.1000/example", "title": "Entirely different study", "abstract": "Wrong work"}},
            ):
                with patch.object(collector, "_fetch_pubmed_batch", return_value=matches):
                    records = collector.collect(self.source)
                self.assertEqual(records[0].abstract, "")

    def test_pubmed_failure_keeps_primary_records_and_marks_partial_enrichment(self) -> None:
        collector = CrossrefCollector(cache_dir=None)
        with (
            patch.object(collector, "_fetch_crossref_items", return_value=[self.work]),
            patch.object(collector, "_fetch_pubmed_batch", side_effect=requests.Timeout("PubMed timeout")),
        ):
            records = collector.collect(self.source)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].metadata["enrichment_status"], "failed")

    def test_existing_abstract_skips_pubmed(self) -> None:
        collector = CrossrefCollector(cache_dir=None)
        self.work["abstract"] = "<jats:p>Publisher abstract.</jats:p>"
        with (
            patch.object(collector, "_fetch_crossref_items", return_value=[self.work]),
            patch.object(collector, "_fetch_pubmed_batch") as fetch,
        ):
            records = collector.collect(self.source)
        self.assertEqual(records[0].abstract, "Publisher abstract.")
        fetch.assert_not_called()

    def test_crossref_query_excludes_whole_issue_and_volume_records(self) -> None:
        collector = CrossrefCollector(cache_dir=None)
        with patch.object(collector.api, "get", return_value=response({"message": {"items": [self.work]}})) as fetch:
            items = collector._fetch_crossref_items(self.source.incremental_url, limit=1)
        self.assertEqual(items, [self.work])
        self.assertEqual(fetch.call_args.kwargs['params']['filter'], 'type:journal-article')
        self.assertEqual(fetch.call_args.kwargs['params']['rows'], 1)

    def test_wiley_inline_title_markup_is_cleaned_and_issue_entries_are_ignored(self) -> None:
        collector = CrossrefCollector(cache_dir=None)
        work = {**self.work, 'title': ['Production in <i>Escherichia coli</i> &amp; yeast'],
                'abstract': '<jats:p>Publisher abstract.</jats:p>', 'type': 'journal-article'}
        issue = {'title': ['Volume 19 Issue 10'], 'DOI': '10.1000/issue', 'type': 'journal-issue'}
        with patch.object(collector, '_fetch_crossref_items', return_value=[issue, work]):
            records = collector.collect(self.source)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, 'Production in Escherichia coli & yeast')
        self.assertEqual(records[0].doi, self.work['DOI'])


if __name__ == "__main__":
    unittest.main()
