from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import DB_PATH, ensure_runtime_directories
from ..processors import normalize_raw_record
from ..storage import SQLiteRepository


def run_process_stage(
    *,
    db_path: Path = DB_PATH,
    source_name: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    ensure_runtime_directories()
    repository = SQLiteRepository(db_path)
    repository.initialize()

    run_id = repository.start_process_run(source_name or "__all__")
    try:
        raw_records = repository.fetch_raw_records(source_name=source_name, limit=limit)
        papers = [normalize_raw_record(record) for record in raw_records]
        upserted_count = repository.upsert_papers(papers)
        repository.finish_process_run(
            run_id,
            status="success",
            item_count=upserted_count,
        )
    except Exception as exc:
        repository.finish_process_run(
            run_id,
            status="failed",
            item_count=0,
            error_message=str(exc),
        )
        raise

    return {
        "status": "success",
        "source_name": source_name or "__all__",
        "scanned_raw_records": len(raw_records),
        "upserted_papers": upserted_count,
        "processed_sources": sorted({record.source_name for record in raw_records}),
    }
