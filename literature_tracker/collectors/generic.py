from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup
import feedparser

from ..models import RawRecord, SourceConfig
from .base import BaseCollector, CollectorError


class GenericJournalCollector(BaseCollector):
    platform = "generic_journal"

    ARTICLE_TRACKING_QUERY_KEYS = {
        "_ga",
        "_gl",
        "_gs",
        "af",
        "dgcid",
        "fbclid",
        "gad_source",
        "gclid",
        "mc_cid",
        "mc_eid",
        "rss",
        "spm",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        records: list[RawRecord] = []
        last_error: Exception | None = None

        for listing_url in self._candidate_listing_urls(source):
            try:
                current_records = self._collect_from_listing_url(
                    source,
                    listing_url=listing_url,
                    limit=limit,
                )
                records.extend(current_records)
            except Exception as exc:
                last_error = exc

            records = self.dedupe_by_article_url(records)
            if limit and len(records) >= limit:
                records = records[:limit]
                break

        if not records and last_error is not None:
            raise last_error

        if "html_detail" not in source.collector_kind.casefold():
            return self.dedupe_by_article_url(records)

        enriched: list[RawRecord] = []
        for record in records[: limit or len(records)]:
            try:
                enriched_record = self.enrich_with_citation_meta(record)
                enriched_record.metadata["enrichment_status"] = "success"
                enriched_record.metadata.pop("enrichment_error", None)
                enriched.append(enriched_record)
            except Exception as exc:
                record.metadata["enrichment_status"] = "failed"
                record.metadata["enrichment_error"] = str(exc)
                enriched.append(record)
        return self.dedupe_by_article_url(enriched)

    def _collect_from_listing_url(
        self,
        source: SourceConfig,
        *,
        listing_url: str,
        limit: int | None = None,
    ) -> list[RawRecord]:
        if self._looks_like_feed_url(listing_url):
            return self._collect_from_feed(source, listing_url=listing_url, limit=limit)

        html = self.fetch_html(listing_url)
        if self._looks_like_feed_payload(html):
            return self._collect_from_feed_payload(
                source,
                payload=html.encode("utf-8"),
                listing_url=listing_url,
                limit=limit,
            )

        soup = BeautifulSoup(html, "html.parser")
        return self._collect_from_listing_soup(
            source,
            soup,
            listing_url=listing_url,
            limit=limit,
        )

    def _collect_from_feed(
        self,
        source: SourceConfig,
        *,
        listing_url: str,
        limit: int | None = None,
    ) -> list[RawRecord]:
        payload = self.fetch_bytes(listing_url)
        return self._collect_from_feed_payload(
            source,
            payload=payload,
            listing_url=listing_url,
            limit=limit,
        )

    def _collect_from_feed_payload(
        self,
        source: SourceConfig,
        *,
        payload: bytes,
        listing_url: str,
        limit: int | None = None,
    ) -> list[RawRecord]:
        parsed = feedparser.parse(payload)
        if parsed.bozo and not parsed.entries:
            raise CollectorError(f"Failed to parse feed for {source.source_name}")

        feed_title = self.clean_text(parsed.feed.get("title", ""))
        records: list[RawRecord] = []
        for entry in parsed.entries[: limit or None]:
            article_url = self._clean_article_url(
                self._entry_string(entry, "link") or self._entry_string(entry, "id")
            )
            title = self._clean_html_text(self._entry_string(entry, "title"))
            if not article_url or not title:
                continue

            summary_html = (
                self._entry_string(entry, "summary")
                or self._entry_string(entry, "description")
                or self._entry_string(entry, "content")
            )
            summary_text = self._clean_html_text(summary_html)
            metadata = self._feed_entry_metadata(entry, feed_title, summary_text, listing_url)

            record = self.build_record(
                source,
                listing_url=listing_url,
                article_url=article_url,
                title=title,
                abstract=self._feed_abstract(source, summary_text),
                published_at=self._entry_date(entry, summary_text),
                doi=self._entry_doi(entry, article_url, summary_text),
                metadata=metadata,
            )
            record.authors = self._entry_authors(entry, summary_text)
            self._enrich_from_external_metadata(source, record)
            records.append(record)
        return self.dedupe_by_article_url(records)

    def _collect_from_listing_soup(
        self,
        source: SourceConfig,
        soup: BeautifulSoup,
        *,
        listing_url: str,
        limit: int | None = None,
    ) -> list[RawRecord]:
        records: list[RawRecord] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not self._is_article_href(source, href):
                continue

            title = self._anchor_title(anchor)
            if not title:
                continue

            article_url = self._clean_article_url(self.absolute_url(listing_url, href))
            if not article_url or article_url in seen:
                continue
            seen.add(article_url)

            records.append(
                self.build_record(
                    source,
                    listing_url=listing_url,
                    article_url=article_url,
                    title=title,
                    published_at=self._container_date(anchor),
                    metadata={"discovered_from": listing_url},
                )
            )
            if limit and len(records) >= limit:
                break

        return self.dedupe_by_article_url(records)

    @classmethod
    def _candidate_listing_urls(cls, source: SourceConfig) -> list[str]:
        candidates: list[str] = []
        cls._append_unique(candidates, source.incremental_url)

        kind = source.collector_kind.casefold()
        platform = source.platform.casefold()

        if platform == "oup" and "rss_current_issue_fallback" in kind:
            fallback = re.sub(
                r"/advanceAccess_(\d+)\.xml$",
                r"/\1.xml",
                source.incremental_url,
            )
            cls._append_unique(candidates, fallback)

        if platform == "cell" and "rss_current_fallback" in kind:
            cls._append_unique(
                candidates,
                source.incremental_url.replace("/inpress.rss", "/current.rss"),
            )

        if "html_articles_fallback" in kind:
            cls._append_unique(candidates, source.canonical_url.rstrip("/") + "/articles")

        if "html_home_fallback" in kind:
            cls._append_unique(candidates, source.canonical_url)

        if not cls._looks_like_feed_url(source.incremental_url):
            cls._append_unique(candidates, source.canonical_url)

        return candidates

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        value = (value or "").strip()
        if value and value not in values:
            values.append(value)

    @staticmethod
    def _looks_like_feed_url(url: str) -> bool:
        lowered = (url or "").casefold()
        hostname = (urlparse(url).hostname or "").casefold()
        return (
            lowered.endswith(".rss")
            or lowered.endswith(".xml")
            or "/rss/" in lowered
            or "feed=rss" in lowered
            or "fmt=rss" in lowered
            or "showfeed" in lowered
            or hostname.startswith("rss.")
        )

    @staticmethod
    def _looks_like_feed_payload(payload: str) -> bool:
        start = payload.lstrip()[:200].casefold()
        return start.startswith("<?xml") or "<rss" in start or "<rdf:rdf" in start

    @classmethod
    def _is_article_href(cls, source: SourceConfig, href: str) -> bool:
        lowered = (href or "").casefold()
        if not lowered or lowered.startswith(("#", "mailto:", "javascript:")):
            return False

        platform = source.platform.casefold()
        if platform == "sciencedirect":
            return "/science/article/pii/" in lowered
        if platform == "oup":
            return "/synbio/article/" in lowered or "/synbio/advance-article/" in lowered
        if platform == "scientific_american":
            return "/article/" in lowered
        if platform == "asm":
            return "/doi/" in lowered and not lowered.rstrip("/").endswith("/doi")
        if platform == "cell":
            return "/fulltext/" in lowered
        if platform == "nature":
            return bool(re.search(r"/articles/s\d{5}-", lowered))
        if platform == "microbiology_research":
            return "/content/journal/micro/" in lowered and "10." in lowered
        if platform == "wiley":
            return "/doi/" in lowered and ("10." in lowered or "/doi/abs/" in lowered)

        return any(
            pattern in lowered
            for pattern in ("/article/", "/articles/", "/doi/", "/fulltext/")
        )

    @classmethod
    def _anchor_title(cls, anchor: Any) -> str:
        title = cls.clean_text(anchor.get_text(" ", strip=True))
        if not title:
            title = cls.clean_text(anchor.get("title") or anchor.get("aria-label") or "")
        if title.casefold() in {
            "abstract",
            "full text",
            "html",
            "pdf",
            "view article",
            "view full text",
        }:
            return ""
        return title

    @classmethod
    def _container_date(cls, anchor: Any) -> str | None:
        container = anchor.find_parent(["article", "li", "section", "div"])
        if not container:
            return None
        time_tag = container.find("time")
        if not time_tag:
            return None
        return time_tag.get("datetime") or cls.clean_text(time_tag.get_text(" ", strip=True)) or None

    @classmethod
    def _clean_html_text(cls, value: Any) -> str:
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
        return cls.clean_text(text)

    @classmethod
    def _entry_string(cls, entry: Any, key: str) -> str:
        value = entry.get(key, "") if hasattr(entry, "get") else getattr(entry, key, "")
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value or "")

    @classmethod
    def _entry_authors(cls, entry: Any, summary_text: str) -> str:
        author_values: list[str] = []

        authors = entry.get("authors", []) if hasattr(entry, "get") else getattr(entry, "authors", [])
        for author in authors or []:
            if hasattr(author, "get"):
                author_values.append(str(author.get("name", "") or ""))
            else:
                author_values.append(str(author or ""))

        author_text = cls._entry_string(entry, "author")
        if author_text:
            author_values.append(author_text)

        summary_match = re.search(r"Author\(s\):\s*(.+)$", summary_text)
        if summary_match:
            author_values.append(summary_match.group(1))

        split_values: list[str] = []
        for value in author_values:
            split_values.extend(re.split(r"\s*,\s*|\s*;\s*|\s*\n\s*", value))
        return "; ".join(cls.dedupe_text_values(split_values))

    @classmethod
    def _entry_date(cls, entry: Any, summary_text: str) -> str | None:
        for key in ("published", "updated", "prism_publicationdate", "prism_coverdate"):
            value = cls._entry_string(entry, key)
            if value:
                return value
        summary_match = re.search(r"Publication date:\s*(.+?)(?:\s+Source:|$)", summary_text)
        if summary_match:
            return cls.clean_text(summary_match.group(1))
        return None

    @classmethod
    def _entry_doi(cls, entry: Any, article_url: str, summary_text: str) -> str | None:
        for key in ("prism_doi", "dc_identifier", "doi", "id"):
            value = cls._entry_string(entry, key)
            doi = cls.extract_doi(value)
            if doi:
                return doi
        return cls.extract_doi(article_url) or cls.extract_doi(summary_text)

    @classmethod
    def _feed_abstract(cls, source: SourceConfig, summary_text: str) -> str:
        if not summary_text:
            return ""
        if source.platform.casefold() in {"sciencedirect", "wiley"}:
            if not summary_text.casefold().startswith("abstract"):
                return ""
        return cls._strip_abstract_heading(summary_text)

    @classmethod
    def _feed_entry_metadata(
        cls,
        entry: Any,
        feed_title: str,
        summary_text: str,
        listing_url: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"discovered_from": listing_url}
        if feed_title:
            metadata["feed_title"] = feed_title
        if summary_text:
            metadata["feed_summary"] = summary_text

        keywords = cls._entry_keywords(entry)
        if keywords:
            metadata["keywords"] = keywords

        for key in (
            "prism_publicationname",
            "prism_section",
            "prism_volume",
            "prism_number",
            "prism_coverdisplaydate",
        ):
            value = cls._entry_string(entry, key)
            if value:
                metadata[key] = value
        return metadata

    @classmethod
    def _entry_keywords(cls, entry: Any) -> list[str]:
        values: list[str] = []
        for tag in entry.get("tags", []) if hasattr(entry, "get") else []:
            if hasattr(tag, "get"):
                values.append(str(tag.get("term", "") or tag.get("label", "") or ""))
            else:
                values.append(str(tag or ""))
        return cls.dedupe_text_values(values)

    def _enrich_from_external_metadata(
        self,
        source: SourceConfig,
        record: RawRecord,
    ) -> None:
        if source.platform.casefold() != "sciencedirect":
            return
        if record.doi and record.metadata.get("keywords") and record.abstract:
            return

        work = self._fetch_openalex_work(record)
        if work and self._openalex_title_matches(record.title, work):
            doi = self._normalize_external_doi(str(work.get("doi") or ""))
            if doi and not record.doi:
                record.doi = doi

            keywords = self._openalex_keywords(work)
            if keywords and not record.metadata.get("keywords"):
                record.metadata["keywords"] = keywords

            abstract = self._openalex_abstract(work)
            if abstract and not record.abstract:
                self._set_record_abstract(record, abstract)

            if work.get("id"):
                record.metadata["openalex_id"] = work["id"]
            if doi or keywords or abstract:
                record.metadata["external_metadata_source"] = "openalex"

        pubmed_record = self._fetch_pubmed_record(record)
        if pubmed_record and self._pubmed_title_matches(record.title, pubmed_record):
            doi = self._normalize_external_doi(str(pubmed_record.get("doi") or ""))
            if doi and not record.doi:
                record.doi = doi

            keywords = pubmed_record.get("keywords") or []
            if keywords:
                record.metadata["keywords"] = self.dedupe_text_values(
                    [str(keyword) for keyword in keywords]
                )

            abstract = self.clean_text(str(pubmed_record.get("abstract") or ""))
            if abstract and not record.abstract:
                self._set_record_abstract(record, abstract)

            if pubmed_record.get("pmid"):
                record.metadata["pubmed_id"] = pubmed_record["pmid"]
            if doi or keywords or abstract:
                record.metadata["external_metadata_source"] = "pubmed"

    def _fetch_openalex_work(self, record: RawRecord) -> dict[str, Any] | None:
        try:
            response = self.session.get(
                "https://api.openalex.org/works",
                params={
                    "search": record.title,
                    "per-page": 1,
                    "select": (
                        "id,doi,display_name,abstract_inverted_index,keywords,concepts"
                    ),
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        results = data.get("results") or []
        if not results:
            return None
        return results[0]

    @classmethod
    def _openalex_title_matches(cls, title: str, work: dict[str, Any]) -> bool:
        candidate = cls.clean_text(str(work.get("display_name") or ""))
        if not title or not candidate:
            return False
        title_key = cls._normalize_match_text(title)
        candidate_key = cls._normalize_match_text(candidate)
        if title_key == candidate_key:
            return True
        return SequenceMatcher(None, title_key, candidate_key).ratio() >= 0.92

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @staticmethod
    def _normalize_external_doi(value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
        return value or None

    @classmethod
    def _openalex_keywords(cls, work: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for item in work.get("keywords") or []:
            if float(item.get("score") or 0) >= 0.25:
                values.append(str(item.get("display_name") or ""))
        if values:
            return cls.dedupe_text_values(values[:8])

        for item in work.get("concepts") or []:
            if 0 < int(item.get("level") or 0) <= 4 and float(item.get("score") or 0) >= 0.35:
                values.append(str(item.get("display_name") or ""))
        return cls.dedupe_text_values(values[:8])

    @classmethod
    def _openalex_abstract(cls, work: dict[str, Any]) -> str:
        inverted_index = work.get("abstract_inverted_index") or {}
        if not isinstance(inverted_index, dict):
            return ""

        positions: list[tuple[int, str]] = []
        for word, indexes in inverted_index.items():
            for index in indexes or []:
                positions.append((int(index), str(word)))
        positions.sort()
        return cls.clean_text(" ".join(word for _, word in positions))

    def _fetch_pubmed_record(self, record: RawRecord) -> dict[str, Any] | None:
        query = record.doi or record.title
        if not query:
            return None

        try:
            search_response = self.session.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmode": "json",
                    "retmax": 1,
                },
                timeout=15,
            )
            search_response.raise_for_status()
            id_list = (
                search_response.json()
                .get("esearchresult", {})
                .get("idlist", [])
            )
            if not id_list:
                return None

            fetch_response = self.session.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params={
                    "db": "pubmed",
                    "id": id_list[0],
                    "retmode": "xml",
                },
                timeout=15,
            )
            fetch_response.raise_for_status()
            root = ET.fromstring(fetch_response.content)
        except Exception:
            return None

        article = root.find(".//PubmedArticle")
        if article is None:
            return None
        return self._parse_pubmed_article(article)

    @classmethod
    def _parse_pubmed_article(cls, article: ET.Element) -> dict[str, Any]:
        title_node = article.find(".//ArticleTitle")
        title = cls.clean_text("".join(title_node.itertext()) if title_node is not None else "")

        abstract_parts: list[str] = []
        for abstract_node in article.findall(".//Abstract/AbstractText"):
            text = cls.clean_text(" ".join(abstract_node.itertext()))
            if not text:
                continue
            label = cls.clean_text(abstract_node.get("Label") or "")
            abstract_parts.append(f"{label}: {text}" if label else text)

        keywords = [
            cls.clean_text(" ".join(keyword.itertext()))
            for keyword in article.findall(".//KeywordList/Keyword")
        ]
        article_ids = {
            (node.get("IdType") or "").casefold(): cls.clean_text("".join(node.itertext()))
            for node in article.findall(".//ArticleId")
        }

        return {
            "pmid": article_ids.get("pubmed", ""),
            "doi": article_ids.get("doi", ""),
            "pii": article_ids.get("pii", ""),
            "title": title,
            "abstract": cls.clean_text(" ".join(abstract_parts)),
            "keywords": cls.dedupe_text_values(keywords),
        }

    @classmethod
    def _pubmed_title_matches(cls, title: str, record: dict[str, Any]) -> bool:
        candidate = cls.clean_text(str(record.get("title") or "")).rstrip(".")
        if not title or not candidate:
            return False
        title_key = cls._normalize_match_text(title)
        candidate_key = cls._normalize_match_text(candidate)
        if title_key == candidate_key:
            return True
        return SequenceMatcher(None, title_key, candidate_key).ratio() >= 0.92

    @classmethod
    def _set_record_abstract(cls, record: RawRecord, abstract: str) -> None:
        record.abstract = cls.clean_text(abstract)
        record.content_text = cls.clean_text(" ".join([record.title, record.abstract]))

    @classmethod
    def _clean_article_url(cls, url: str) -> str:
        parsed = urlparse((url or "").strip())
        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in cls.ARTICLE_TRACKING_QUERY_KEYS
        ]
        return urlunparse(parsed._replace(query=urlencode(query_pairs, doseq=True)))
