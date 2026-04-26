from __future__ import annotations

import re
from typing import Iterable

from ..models import PaperRecord, StoredRawRecord


WHITESPACE_RE = re.compile(r"\s+")
AUTHOR_SPLIT_RE = re.compile(r"[;；]+")
COMMA_SPLIT_RE = re.compile(r"[，,]+")
DATE_YEAR_MONTH_DAY_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")
DATE_YEAR_MONTH_RE = re.compile(r"^\d{4}/\d{2}$")


def normalize_raw_record(record: StoredRawRecord) -> PaperRecord:
    canonical_title = clean_text(record.title)
    normalized_authors = "; ".join(normalize_authors(record.authors))
    normalized_date = normalize_published_at(record.published_at)
    paper_key = build_paper_key(record)

    metadata = dict(record.metadata)
    metadata.update(
        {
            "raw_record_id": record.id,
            "raw_record_content_hash": record.content_hash,
            "listing_url": record.listing_url,
            "collector_kind": record.collector_kind,
            "article_url": record.article_url,
            "first_seen_at": record.first_seen_at,
            "last_seen_at": record.last_seen_at,
            "seen_count": record.seen_count,
            "normalized_title": canonical_title.casefold(),
        }
    )

    return PaperRecord(
        raw_record_id=record.id,
        paper_key=paper_key,
        source_name=record.source_name,
        journal_name=clean_text(record.journal_name),
        article_url=record.article_url.strip(),
        doi=clean_text(record.doi or "") or None,
        canonical_title=canonical_title,
        normalized_authors=normalized_authors,
        published_at=normalized_date,
        abstract=clean_text(record.abstract),
        language=normalize_language(record.language),
        status="normalized",
        metadata=metadata,
    )


def clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value or "").strip()


def normalize_authors(authors: str) -> list[str]:
    clean_authors = clean_text(authors)
    if not clean_authors:
        return []

    if AUTHOR_SPLIT_RE.search(clean_authors):
        parts = AUTHOR_SPLIT_RE.split(clean_authors)
    else:
        parts = COMMA_SPLIT_RE.split(clean_authors)

    return dedupe_preserving_order(clean_text(part) for part in parts if clean_text(part))


def normalize_published_at(value: str | None) -> str | None:
    clean_value = clean_text(value or "")
    if not clean_value:
        return None
    if DATE_YEAR_MONTH_DAY_RE.match(clean_value):
        return clean_value.replace("/", "-")
    if DATE_YEAR_MONTH_RE.match(clean_value):
        return clean_value.replace("/", "-")
    return clean_value


def normalize_language(value: str | None) -> str | None:
    clean_value = clean_text(value or "").lower()
    if not clean_value:
        return None
    if clean_value.startswith("zh"):
        return "zh"
    if clean_value.startswith("en"):
        return "en"
    return clean_value


def build_paper_key(record: StoredRawRecord) -> str:
    doi = clean_text(record.doi or "")
    if doi:
        return f"doi:{doi.lower()}"
    return f"url:{record.source_name.lower()}::{record.article_url.strip().lower()}"


def dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
