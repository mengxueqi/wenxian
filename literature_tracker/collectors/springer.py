from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from ..models import RawRecord, SourceConfig
from .base import BaseCollector


class SpringerCollector(BaseCollector):
    platform = "springer"

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        if "crossref_api" in source.collector_kind.casefold():
            return self._collect_from_crossref(source, limit=limit)

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
                enriched_record = self.enrich_with_citation_meta(record)
                enriched_record.metadata["enrichment_status"] = "success"
                enriched_record.metadata.pop("enrichment_error", None)
                enriched.append(enriched_record)
            except Exception as exc:
                record.metadata["enrichment_status"] = "failed"
                record.metadata["enrichment_error"] = str(exc)
                enriched.append(record)
        return self.dedupe_by_article_url(enriched)

    def _collect_from_crossref(
        self,
        source: SourceConfig,
        *,
        limit: int | None = None,
    ) -> list[RawRecord]:
        items = self._fetch_crossref_items(source.incremental_url, limit=limit)
        records: list[RawRecord] = []

        for item in items:
            title = self._first_text(item.get("title"))
            doi = self.clean_text(str(item.get("DOI") or "")) or None
            article_url = self.clean_text(str(item.get("URL") or ""))
            if not article_url and doi:
                article_url = f"https://doi.org/{doi}"
            if not title or not article_url:
                continue

            abstract = self._crossref_abstract(item)
            record = self.build_record(
                source,
                listing_url=source.incremental_url,
                article_url=article_url,
                title=title,
                abstract=abstract,
                published_at=self._crossref_date(item),
                doi=doi,
                metadata={
                    "discovered_from": source.incremental_url,
                    "external_metadata_source": "crossref",
                    "crossref_type": item.get("type") or "",
                    "keywords": self.dedupe_text_values(
                        [str(value) for value in item.get("subject") or []]
                    ),
                },
            )
            record.authors = self._crossref_authors(item)
            records.append(record)

        return self.dedupe_by_article_url(records)

    def _fetch_crossref_items(
        self,
        url: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = max(1, min(limit or 100, 1000))
        response = self.session.get(
            url,
            params={"sort": "published", "order": "desc", "rows": rows},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("message", {}).get("items", [])
        return [item for item in items if isinstance(item, dict)][:rows]

    @classmethod
    def _crossref_authors(cls, item: dict[str, Any]) -> str:
        names: list[str] = []
        for author in item.get("author") or []:
            if not isinstance(author, dict):
                continue
            name = cls.clean_text(
                " ".join(
                    part
                    for part in (
                        str(author.get("given") or ""),
                        str(author.get("family") or ""),
                    )
                    if part
                )
            )
            if name:
                names.append(name)
        return "; ".join(cls.dedupe_text_values(names))

    @classmethod
    def _crossref_abstract(cls, item: dict[str, Any]) -> str:
        value = str(item.get("abstract") or "")
        if not value:
            return ""
        text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        return cls._strip_abstract_heading(cls.clean_text(text))

    @classmethod
    def _crossref_date(cls, item: dict[str, Any]) -> str | None:
        for key in ("published-online", "published-print", "published", "created"):
            date_parts = (item.get(key) or {}).get("date-parts") or []
            if not date_parts or not date_parts[0]:
                continue
            parts = [int(value) for value in date_parts[0][:3]]
            return "-".join(
                [f"{parts[0]:04d}"]
                + [f"{value:02d}" for value in parts[1:]]
            )
        return None

    @classmethod
    def _first_text(cls, value: Any) -> str:
        if isinstance(value, list):
            value = value[0] if value else ""
        return cls.clean_text(str(value or ""))

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
