from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..models import RawRecord, SourceConfig
from .generic import GenericJournalCollector
from .metadata_api import METADATA_CACHE_DIR, MetadataClient


class CrossrefCollector(GenericJournalCollector):
    """Use publisher-deposited metadata and DOI-verified PubMed abstracts."""
    platform = "crossref"

    def __init__(self, session: requests.Session | None = None, cache_dir: Path | None = METADATA_CACHE_DIR) -> None:
        super().__init__(session=session)
        self.session.headers["User-Agent"] = "LiteratureTracker/0.1 (journal metadata monitor)"
        self.api = MetadataClient(self.session, cache_dir)

    def collect(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        return self._collect_from_crossref(source, limit=limit)

    def _collect_from_crossref(self, source: SourceConfig, *, limit: int | None = None) -> list[RawRecord]:
        items = self._fetch_crossref_items(source.incremental_url, limit=limit)
        records = []
        for item in items:
            if item.get("type") in {"journal", "journal-issue", "journal-volume"}:
                continue
            title = self._clean_html_text(self._first_text(item.get("title")))
            doi = self.clean_text(str(item.get("DOI") or "")) or None
            article_url = self.clean_text(str(item.get("URL") or "")) or (f"https://doi.org/{doi}" if doi else "")
            if not title or not article_url:
                continue
            abstract = self._crossref_abstract(item)
            record = self.build_record(
                source, listing_url=source.incremental_url, article_url=article_url,
                title=title, abstract=abstract, published_at=self._crossref_date(item), doi=doi,
                metadata={
                    "discovered_from": source.incremental_url,
                    "external_metadata_source": "crossref",
                    "enrichment_status": "success",
                    "abstract_source": "crossref" if abstract else "",
                    "crossref_type": item.get("type") or "",
                    "keywords": self.dedupe_text_values([str(v) for v in item.get("subject") or []]),
                },
            )
            record.authors = self._crossref_authors(item)
            records.append(record)
        records = self.dedupe_by_article_url(records)
        if "pubmed" in source.collector_kind.casefold():
            self._enrich_pubmed_abstracts(records)
        return records

    def _fetch_crossref_items(self, url: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = max(1, min(limit or 100, 1000))
        response = self.api.get(url, params={
            "filter": "type:journal-article", "sort": "published", "order": "desc", "rows": rows,
        })
        items = response.json().get("message", {}).get("items", [])
        return [item for item in items if isinstance(item, dict)][:rows]

    def _enrich_pubmed_abstracts(self, records: list[RawRecord]) -> None:
        pending = [r for r in records if r.doi and not r.abstract]
        for start in range(0, len(pending), 20):
            batch = pending[start : start + 20]
            try:
                matches = self._fetch_pubmed_batch([str(r.doi) for r in batch])
            except Exception as exc:
                for record in pending[start:]:
                    record.metadata.update(enrichment_status="failed", enrichment_error=f"PubMed: {exc}")
                break
            for record in batch:
                doi = str(record.doi).casefold()
                candidate = matches.get(doi)
                if not candidate or not self._pubmed_title_matches(record.title, candidate):
                    record.metadata["pubmed_status"] = "not_matched"
                    continue
                record.metadata["pubmed_id"] = candidate["pmid"]
                record.metadata["pubmed_status"] = "matched"
                record.metadata["enrichment_status"] = "success"
                record.metadata["keywords"] = self.dedupe_text_values([
                    *record.metadata.get("keywords", []), *candidate.get("keywords", []),
                ])
                if candidate.get("abstract"):
                    self._set_record_abstract(record, str(candidate["abstract"]))
                    record.metadata["abstract_source"] = "pubmed"

    def _fetch_pubmed_batch(self, dois: list[str]) -> dict[str, dict[str, Any]]:
        query = " OR ".join(f'"{doi}"[AID]' for doi in dois)
        search = self.api.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmode": "json", "retmax": len(dois) * 2, "tool": "literature_tracker"},
            cache_ttl=21600,
        )
        payload = search.json()
        search_result = payload.get("esearchresult", {})
        if payload.get("error") or search_result.get("ERROR"):
            raise ValueError(str(payload.get("error") or search_result["ERROR"]))
        ids = search_result.get("idlist", [])
        if not ids:
            return {}
        response = self.api.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml", "tool": "literature_tracker"},
            cache_ttl=21600,
        )
        root = ET.fromstring(response.content)
        if root.find(".//ERROR") is not None:
            raise ValueError(root.findtext(".//ERROR"))
        matches = {}
        for article in root.findall(".//PubmedArticle"):
            parsed = self._parse_pubmed_article(article)
            doi = self._normalize_external_doi(str(parsed.get("doi") or ""))
            if doi:
                matches[doi.casefold()] = parsed
        return matches

    @classmethod
    def _crossref_authors(cls, item: dict[str, Any]) -> str:
        return "; ".join(cls.dedupe_text_values([
            " ".join(str(author.get(part) or "") for part in ("given", "family"))
            for author in item.get("author") or [] if isinstance(author, dict)
        ]))

    @classmethod
    def _crossref_abstract(cls, item: dict[str, Any]) -> str:
        text = BeautifulSoup(str(item.get("abstract") or ""), "html.parser").get_text(" ", strip=True)
        return cls._strip_abstract_heading(cls.clean_text(text))

    @classmethod
    def _crossref_date(cls, item: dict[str, Any]) -> str | None:
        for key in ("published-online", "published-print", "published", "created"):
            date_parts = (item.get(key) or {}).get("date-parts") or []
            if date_parts and date_parts[0]:
                parts = [int(v) for v in date_parts[0][:3]]
                return "-".join([f"{parts[0]:04d}", *[f"{v:02d}" for v in parts[1:]]])
        return None

    @classmethod
    def _first_text(cls, value: Any) -> str:
        return cls.clean_text(str((value[0] if value else "") if isinstance(value, list) else value or ""))
