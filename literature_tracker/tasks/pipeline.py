from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..paths import DB_PATH, REPORTS_DIR
from .build_insights import run_insight_build
from .crawl import crawl_sources
from .detect_changes import run_change_detection
from .process import run_process_stage
from .report import build_report


def run_full_pipeline(
    *,
    db_path: Path = DB_PATH,
    source_name: str | None = None,
    limit: int | None = None,
    output_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    """Run the complete monitoring pipeline and return one scheduler-friendly result."""
    stages: dict[str, Any] = {}
    crawl_summary = crawl_sources(
        db_path=db_path,
        source_name=source_name,
        limit=limit,
    )
    stages["crawl"] = crawl_summary

    stage_calls: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        (
            "process",
            lambda: run_process_stage(
                db_path=db_path,
                source_name=source_name,
                limit=limit,
            ),
        ),
        (
            "detect_changes",
            lambda: run_change_detection(
                db_path=db_path,
                source_name=source_name,
                limit=limit,
            ),
        ),
        (
            "build_insights",
            lambda: run_insight_build(
                db_path=db_path,
                source_name=source_name,
                limit=limit,
            ),
        ),
        (
            "build_report",
            lambda: build_report(
                db_path=db_path,
                source_name=source_name,
                output_dir=output_dir,
            ),
        ),
    ]

    for stage_name, stage_call in stage_calls:
        try:
            stages[stage_name] = stage_call()
        except Exception as exc:
            return {
                "status": "failed",
                "failed_stage": stage_name,
                "error": str(exc),
                "source_name": source_name or "__all__",
                "stages": stages,
            }

    crawl_failures = int(crawl_summary.get("failure_count", 0))
    crawl_partials = int(crawl_summary.get("partial_count", 0))
    status = "partial" if crawl_failures or crawl_partials else "success"
    return {
        "status": status,
        "source_name": source_name or "__all__",
        "stages": stages,
    }
