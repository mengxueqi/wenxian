from __future__ import annotations

from bs4 import BeautifulSoup
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
                enriched.append(self.enrich_with_citation_meta(record))
            except Exception:
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
