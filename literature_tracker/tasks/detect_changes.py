from __future__ import annotations

from pathlib import Path
from typing import Any

from ..detectors import build_change_candidates
from ..paths import DB_PATH, ensure_runtime_directories
from ..storage import SQLiteRepository


def run_change_detection(
    *,
    db_path: Path = DB_PATH,
    source_name: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    ensure_runtime_directories()
    repository = SQLiteRepository(db_path)
    repository.initialize()

    run_id = repository.start_change_detection_run(source_name or "__all__")
    try:
        papers = repository.fetch_papers(source_name=source_name, limit=limit)
        existing_state = repository.fetch_paper_change_state()
        candidates = build_change_candidates(papers, existing_state)
        inserted_count = repository.upsert_paper_changes(candidates)
        repository.finish_change_detection_run(
            run_id,
            status="success",
            item_count=inserted_count,
        )
    except Exception as exc:
        repository.finish_change_detection_run(
            run_id,
            status="failed",
            item_count=0,
            error_message=str(exc),
        )
        raise

    return {
        "status": "success",
        "source_name": source_name or "__all__",
        "scanned_papers": len(papers),
        "detected_changes": inserted_count,
        "candidate_changes": len(candidates),
        "processed_sources": sorted({paper.source_name for paper in papers}),
    }
