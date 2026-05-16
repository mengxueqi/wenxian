from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..models import RawRecord, SourceConfig


class CollectorError(RuntimeError):
    """Collector-level error with a user-facing message."""


class BaseCollector(ABC):
    platform: str = "generic"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0.0.0 Safari/537.36"
                )
            }
        )

    @abstractmethod
    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        raise NotImplementedError

    def fetch_bytes(self, url: str) -> bytes:
        response = self.session.get(url, timeout=30)
        if response.status_code in {403, 429}:
            self.raise_for_known_blockers(response.text, url)
        response.raise_for_status()
        return response.content

    def fetch_html(self, url: str) -> str:
        response = self.session.get(url, timeout=30)
        if response.status_code in {403, 429}:
            self.raise_for_known_blockers(response.text, url)
        response.raise_for_status()
        self.raise_for_known_blockers(response.text, url)
        return response.text

    def fetch_soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetch_html(url), "html.parser")

    @staticmethod
    def raise_for_known_blockers(html: str, url: str) -> None:
        lowered = html.lower()
        if "client challenge" in lowered and "javascript is disabled in your browser" in lowered:
            raise CollectorError(
                f"Source blocked non-browser access for {url}. "
                "This source needs a browser-backed fetcher in the next iteration."
            )
        if "just a moment" in lowered and (
            "cloudflare" in lowered
            or "checking if the site connection is secure" in lowered
            or "cf-browser-verification" in lowered
        ):
            raise CollectorError(
                f"Source blocked non-browser access for {url}. "
                "This source needs a browser-backed fetcher in the next iteration."
            )

    @staticmethod
    def absolute_url(base_url: str, href: str) -> str:
        return urljoin(base_url, href)

    @staticmethod
    def clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @classmethod
    def extract_doi(cls, value: str) -> str | None:
        match = re.search(r"(10\.\d{4,9}/[^\s\"'<>]+)", value or "", re.IGNORECASE)
        if not match:
            return None
        doi = match.group(1).rstrip(").,;")
        return doi

    @staticmethod
    def meta_contents(soup: BeautifulSoup, name: str) -> list[str]:
        values: list[str] = []
        for meta in soup.find_all("meta"):
            meta_name = (meta.get("name") or "").strip().lower()
            if meta_name != name.lower():
                continue
            content = (meta.get("content") or "").strip()
            if content:
                values.append(content)
        return values

    def enrich_with_citation_meta(self, record: RawRecord) -> RawRecord:
        soup = self.fetch_soup(record.article_url)
        title_values = self.meta_contents(soup, "citation_title")
        author_values = self.meta_contents(soup, "citation_author")
        author_values.extend(self.meta_contents(soup, "citation_authors"))
        abstract_values = self.abstract_contents(soup)
        keyword_values = self.keyword_contents(soup)
        journal_values = self.meta_contents(soup, "citation_journal_title")
        doi_values = self.meta_contents(soup, "citation_doi")
        language_values = self.meta_contents(soup, "citation_language")
        publication_values = self.meta_contents(soup, "citation_publication_date")
        online_values = self.meta_contents(soup, "citation_online_date")
        pdf_values = self.meta_contents(soup, "citation_pdf_url")

        if title_values:
            record.title = title_values[0]
        if author_values:
            record.authors = "; ".join(self.dedupe_text_values(author_values))
        if abstract_values:
            record.abstract = abstract_values[0]
        if journal_values:
            record.journal_name = journal_values[0]
        if doi_values:
            record.doi = doi_values[0]
        if keyword_values:
            record.metadata["keywords"] = keyword_values
        if language_values:
            record.language = language_values[0]
        if publication_values:
            record.published_at = publication_values[0]
        elif online_values and not record.published_at:
            record.published_at = online_values[0]

        if pdf_values:
            record.metadata["pdf_url"] = pdf_values[0]
        if online_values:
            record.metadata["online_date"] = online_values[0]

        record.content_text = self.clean_text(" ".join(filter(None, [record.title, record.abstract])))
        return record

    @staticmethod
    def dedupe_by_article_url(records: list[RawRecord]) -> list[RawRecord]:
        seen: set[str] = set()
        unique_records: list[RawRecord] = []
        for record in records:
            key = record.article_url.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_records.append(record)
        return unique_records

    @classmethod
    def dedupe_text_values(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            cleaned = cls.clean_text(value)
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            unique_values.append(cleaned)
        return unique_values

    @classmethod
    def abstract_contents(cls, soup: BeautifulSoup) -> list[str]:
        values: list[str] = []
        for meta_name in (
            "citation_abstract",
            "dc.description",
            "dc.Description",
            "description",
        ):
            values.extend(cls.meta_contents(soup, meta_name))

        for selector in (
            "#Abs1-content",
            "section#Abs1 .c-article-section__content",
            "[data-test='abstract']",
            ".Abstract",
        ):
            for node in soup.select(selector):
                text = cls.clean_text(node.get_text(" ", strip=True))
                if text:
                    values.append(cls._strip_abstract_heading(text))

        return sorted(cls.dedupe_text_values(values), key=len, reverse=True)

    @classmethod
    def keyword_contents(cls, soup: BeautifulSoup) -> list[str]:
        values: list[str] = []
        for meta_name in (
            "citation_keywords",
            "citation_keyword",
            "dc.subject",
            "dc.Subject",
            "dc.keywords",
            "dc.Keywords",
            "keywords",
        ):
            values.extend(cls.meta_contents(soup, meta_name))

        split_values: list[str] = []
        for value in values:
            split_values.extend(re.split(r"\s*[;,]\s*|\s*\|\s*", value))
        return cls.dedupe_text_values(split_values)

    @staticmethod
    def _strip_abstract_heading(value: str) -> str:
        return re.sub(r"^(abstract|摘要)\s*", "", value, flags=re.IGNORECASE).strip()

    def build_record(
        self,
        source: SourceConfig,
        *,
        listing_url: str | None = None,
        article_url: str,
        title: str,
        abstract: str = "",
        published_at: str | None = None,
        doi: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RawRecord:
        clean_title = self.clean_text(title)
        clean_abstract = self.clean_text(abstract)
        return RawRecord(
            source_name=source.source_name,
            journal_name=source.source_name,
            listing_url=listing_url or source.incremental_url,
            article_url=article_url,
            title=clean_title,
            abstract=clean_abstract,
            published_at=published_at,
            doi=doi or self.extract_doi(article_url) or self.extract_doi(clean_abstract),
            language=source.lang,
            collector_kind=source.collector_kind,
            content_text=self.clean_text(" ".join(filter(None, [clean_title, clean_abstract]))),
            metadata=metadata or {},
        )
