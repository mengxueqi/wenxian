from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import SourceConfig
from .paths import AUTHOR_WATCHLIST_CSV, SOURCES_CSV, THEME_WATCHLIST_CSV


TRACKING_QUERY_KEYS = {
    "_ga",
    "_gl",
    "_gs",
    "fbclid",
    "gad_source",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def strip_tracking_params(url: str) -> str:
    parsed = urlparse(url.strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    ]
    cleaned_query = urlencode(query_pairs, doseq=True)
    return urlunparse(parsed._replace(query=cleaned_query))


def load_sources(csv_path: Path = SOURCES_CSV) -> list[SourceConfig]:
    sources: list[SourceConfig] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_name = (row.get("source_name") or "").strip()
            if not source_name:
                continue
            sources.append(
                SourceConfig(
                    source_name=source_name,
                    canonical_url=strip_tracking_params(row["canonical_url"]),
                    platform=(row.get("platform") or "").strip(),
                    incremental_url=strip_tracking_params(row["incremental_url"]),
                    collector_kind=(row.get("collector_kind") or "").strip(),
                    dedupe_key=(row.get("dedupe_key") or "doi").strip() or "doi",
                    lang=(row.get("lang") or "en").strip() or "en",
                    status=(row.get("status") or "active").strip() or "active",
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return sources


def load_theme_watchlist(
    csv_path: Path = THEME_WATCHLIST_CSV,
) -> list[dict[str, object]]:
    if not csv_path.exists():
        return []
    entries: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            theme_name = (row.get("theme_name") or "").strip()
            keywords = _split_pipe_values(row.get("keywords") or "")
            if not theme_name or not keywords or not _parse_enabled(row.get("enabled")):
                continue
            entries.append(
                {
                    "theme_name": theme_name,
                    "keywords": keywords,
                    "score_weight": _parse_score(row.get("score_weight"), 0.15),
                }
            )
    return entries


def load_author_watchlist(
    csv_path: Path = AUTHOR_WATCHLIST_CSV,
) -> list[dict[str, object]]:
    if not csv_path.exists():
        return []
    entries: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            author_name = (row.get("author_name") or "").strip()
            if not author_name or not _parse_enabled(row.get("enabled")):
                continue
            entries.append(
                {
                    "author_name": author_name,
                    "aliases": _split_pipe_values(row.get("aliases") or ""),
                    "field_hint": (row.get("field_hint") or "").strip(),
                    "score_weight": _parse_score(row.get("score_weight"), 0.4),
                }
            )
    return entries


def _split_pipe_values(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _parse_enabled(value: str | None) -> bool:
    normalized = (value or "true").strip().casefold()
    return normalized not in {"0", "false", "no", "off", "disabled"}


def _parse_score(value: str | None, default: float) -> float:
    try:
        return max(0.0, float(value)) if value not in {None, ""} else default
    except ValueError:
        return default
