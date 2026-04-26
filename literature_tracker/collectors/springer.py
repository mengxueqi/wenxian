from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import RawRecord, SourceConfig
from .base import BaseCollector


class SpringerCollector(BaseCollector):
    platform = "springer"

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        records: list[RawRecord] = []
        last_error: Exception | None = None

        for listing_url in self._candidate_listing_urls(source):
            try:
                soup = self.fetch_soup(listing_url)
                records = self._collect_from_listing_soup(
                    source,
                    soup,
                    listing_url=listing_url,
                    limit=limit,
                )
                if records:
                    break
            except Exception as exc:
                last_error = exc

        if not records and last_error is not None:
            raise last_error

        enriched: list[RawRecord] = []
        for record in records:
            try:
                enriched.append(self.enrich_with_citation_meta(record))
            except Exception:
                enriched.append(record)
        return self.dedupe_by_article_url(enriched)

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

        for anchor in soup.select('a[href*="/article/"]'):
            href = (anchor.get("href") or "").strip()
            title = self.clean_text(anchor.get_text(" ", strip=True))
            if not href or not title:
                continue
            article_url = self.absolute_url(source.canonical_url, href)
            if article_url in seen:
                continue
            seen.add(article_url)

            container = anchor.find_parent(["article", "li", "section", "div"])
            published_at = None
            if container:
                time_tag = container.find("time")
                if time_tag:
                    published_at = (
                        time_tag.get("datetime")
                        or self.clean_text(time_tag.get_text(" ", strip=True))
                        or None
                    )

            records.append(
                self.build_record(
                    source,
                    listing_url=listing_url,
                    article_url=article_url,
                    title=title,
                    published_at=published_at,
                    metadata={"discovered_from": listing_url},
                )
            )
            if limit and len(records) >= limit:
                break
        return records

    @staticmethod
    def _candidate_listing_urls(source: SourceConfig) -> list[str]:
        candidates = [source.incremental_url]
        fallback_url = source.canonical_url.rstrip("/") + "/articles"
        if "articles_fallback" in source.collector_kind and fallback_url not in candidates:
            candidates.append(fallback_url)
        return candidates
