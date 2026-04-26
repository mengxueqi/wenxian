from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SourceConfig:
    source_name: str
    canonical_url: str
    platform: str
    incremental_url: str
    collector_kind: str
    dedupe_key: str = "doi"
    lang: str = "en"
    status: str = "active"
    notes: str = ""

    @property
    def is_active(self) -> bool:
        return self.status.strip().lower() == "active"


@dataclass(slots=True)
class RawRecord:
    source_name: str
    journal_name: str
    listing_url: str
    article_url: str
    title: str
    authors: str = ""
    abstract: str = ""
    published_at: str | None = None
    doi: str | None = None
    language: str | None = None
    collector_kind: str = ""
    content_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )


@dataclass(slots=True)
class StoredRawRecord:
    id: int
    source_name: str
    journal_name: str
    listing_url: str
    article_url: str
    title: str
    authors: str = ""
    abstract: str = ""
    published_at: str | None = None
    doi: str | None = None
    language: str | None = None
    collector_kind: str = ""
    content_text: str = ""
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    first_seen_at: str = ""
    last_seen_at: str = ""
    seen_count: int = 1


@dataclass(slots=True)
class PaperRecord:
    raw_record_id: int
    paper_key: str
    source_name: str
    journal_name: str
    article_url: str
    doi: str | None
    canonical_title: str
    normalized_authors: str
    published_at: str | None
    abstract: str = ""
    language: str | None = None
    status: str = "normalized"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoredPaper:
    id: int
    raw_record_id: int | None
    paper_key: str
    source_name: str
    journal_name: str
    article_url: str
    doi: str | None
    canonical_title: str
    normalized_authors: str
    published_at: str | None
    abstract: str = ""
    language: str | None = None
    status: str = "normalized"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class PaperChangeCandidate:
    paper_id: int
    paper_key: str
    source_name: str
    change_type: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoredPaperChange:
    id: int
    change_key: str
    paper_id: int
    source_name: str
    change_type: str
    summary: str
    detected_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PaperInsightRecord:
    change_id: int
    paper_id: int
    insight_key: str
    source_name: str
    summary: str
    reason: str
    score: float
    score_label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrackingItemRecord:
    paper_id: int
    tracking_key: str
    source_name: str
    tracking_status: str
    priority_score: float
    note: str
    metadata: dict[str, Any] = field(default_factory=dict)
