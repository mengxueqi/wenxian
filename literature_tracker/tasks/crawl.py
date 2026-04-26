from __future__ import annotations

from pathlib import Path
from typing import Any

from ..collectors import get_collector
from ..config import load_sources
from ..paths import DB_PATH, ensure_runtime_directories
from ..storage import SQLiteRepository


def crawl_sources(
    *,
    db_path: Path = DB_PATH,
    source_name: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    ensure_runtime_directories()
    repository = SQLiteRepository(db_path)
    repository.initialize()

    sources = load_sources()
    repository.sync_sources(sources)

    active_sources = [source for source in sources if source.is_active]
    if source_name:
        active_sources = [source for source in active_sources if source.source_name == source_name]

    summary: dict[str, Any] = {
        "total_sources": len(active_sources),
        "success_count": 0,
        "failure_count": 0,
        "stored_raw_records": 0,
        "failures": [],
    }

    for source in active_sources:
        run_id = repository.start_crawl_run(source.source_name)
        try:
            collector = get_collector(source)
            records = collector.collect(source, limit=limit)
            stored_count = repository.upsert_raw_records(records)
            repository.finish_crawl_run(
                run_id,
                status="success",
                item_count=stored_count,
            )
            summary["success_count"] += 1
            summary["stored_raw_records"] += stored_count
        except Exception as exc:
            repository.finish_crawl_run(
                run_id,
                status="failed",
                item_count=0,
                error_message=str(exc),
            )
            summary["failure_count"] += 1
            summary["failures"].append(
                {
                    "source_name": source.source_name,
                    "error": str(exc),
                }
            )

    return summary

