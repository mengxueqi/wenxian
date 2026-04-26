from __future__ import annotations

from pathlib import Path
from typing import Any

from ..insights import build_insight_outputs
from ..paths import DB_PATH, ensure_runtime_directories
from ..storage import SQLiteRepository


def run_insight_build(
    *,
    db_path: Path = DB_PATH,
    source_name: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    ensure_runtime_directories()
    repository = SQLiteRepository(db_path)
    repository.initialize()

    run_id = repository.start_insight_build_run(source_name or "__all__")
    try:
        papers = repository.fetch_papers(source_name=source_name, limit=limit)
        changes = repository.fetch_paper_changes(source_name=source_name, limit=limit)
        insights, tracking_items = build_insight_outputs(papers, changes)
        insight_count = repository.upsert_paper_insights(insights)
        tracking_count = repository.upsert_tracking_items(tracking_items)
        repository.finish_insight_build_run(
            run_id,
            status="success",
            item_count=insight_count,
        )
    except Exception as exc:
        repository.finish_insight_build_run(
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
        "scanned_changes": len(changes),
        "upserted_insights": insight_count,
        "upserted_tracking_items": tracking_count,
        "processed_sources": sorted({paper.source_name for paper in papers}),
    }
