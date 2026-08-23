from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag
import feedparser

from ..models import RawRecord, SourceConfig
from .base import BaseCollector, CollectorError


class CIPCollector(BaseCollector):
    platform = "magtech_cip"
    fallback_listing_url = "https://synbioj.cip.com.cn/CN/article/showNewArticle.do"

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        records: list[RawRecord] = []

        try:
            records = self._collect_from_rss(source, limit=limit)
        except Exception:
            records = []

        if not records:
            records = self._collect_from_listing(source, limit=limit)

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

    def _collect_from_rss(
        self,
        source: SourceConfig,
        *,
        limit: int | None = None,
    ) -> list[RawRecord]:
        payload = self.fetch_bytes(source.incremental_url)
        parsed = feedparser.parse(payload)
        if parsed.bozo and not parsed.entries:
            raise CollectorError(f"Failed to parse RSS feed for {source.source_name}")

        records: list[RawRecord] = []
        for entry in parsed.entries[: limit or None]:
            article_url = getattr(entry, "link", "").strip()
            title = getattr(entry, "title", "").strip()
            summary_html = getattr(entry, "summary", "") or getattr(entry, "description", "")
            abstract = BeautifulSoup(summary_html, "html.parser").get_text(" ", strip=True)
            published_at = getattr(entry, "published", "") or getattr(entry, "updated", "") or None
            if not article_url or not title:
                continue
            records.append(
                self.build_record(
                    source,
                    listing_url=source.incremental_url,
                    article_url=article_url,
                    title=title,
                    abstract=abstract,
                    published_at=published_at,
                )
            )
        return records

    def _collect_from_listing(
        self,
        source: SourceConfig,
        *,
        limit: int | None = None,
    ) -> list[RawRecord]:
        listing_url = self.fallback_listing_url
        soup = self.fetch_soup(listing_url)
        anchors = soup.select('a[href*="/CN/10."]')
        records: list[RawRecord] = []
        for anchor in anchors:
            href = (anchor.get("href") or "").strip()
            title = self.clean_text(anchor.get_text(" ", strip=True))
            if not href:
                continue
            article_url = self.absolute_url(listing_url, href)
            if not title:
                title = article_url.rsplit("/", 1)[-1]
            records.append(
                self.build_record(
                    source,
                    listing_url=listing_url,
                    article_url=article_url,
                    title=title,
                    metadata={"discovered_from": listing_url},
                )
            )
            if limit and len(records) >= limit:
                break
        return self.dedupe_by_article_url(records)

    @classmethod
    def abstract_contents(cls, soup: BeautifulSoup) -> list[str]:
        values = [*super().abstract_contents(soup), *cls._magtech_abstract_contents(soup)]
        return sorted(cls.dedupe_text_values(values), key=cls._abstract_sort_key, reverse=True)

    @classmethod
    def _magtech_abstract_contents(cls, soup: BeautifulSoup) -> list[str]:
        values: list[str] = []
        for panel in soup.select("#collapseOne .panel-body"):
            label = panel.find(
                "strong",
                string=lambda value: bool(value and re.search(r"摘要|abstract", value, re.I)),
            )
            if label is None:
                continue

            parts: list[str] = []
            for element in label.next_elements:
                if isinstance(element, Tag):
                    text = cls.clean_text(element.get_text(" ", strip=True))
                    if element.name == "form":
                        break
                    if element.name == "strong" and re.search(r"关键词|key\s*words?", text, re.I):
                        break
                    continue
                if not isinstance(element, NavigableString) or element.parent is label:
                    continue

                text = cls.clean_text(str(element))
                if not text or re.fullmatch(r"(摘要|abstract)\s*[:：]?", text, re.I):
                    continue
                if re.match(r"(关键词|key\s*words?)\s*[:：]?", text, re.I):
                    break
                parts.append(text)

            abstract = cls.clean_text(" ".join(parts))
            if abstract:
                values.append(cls._strip_abstract_heading(abstract))
        return values

    @staticmethod
    def _abstract_sort_key(value: str) -> tuple[bool, int]:
        return (not value.rstrip().endswith(("...", "…")), len(value))
