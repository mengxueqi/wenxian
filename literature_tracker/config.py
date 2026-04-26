from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import SourceConfig
from .paths import SOURCES_CSV


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

