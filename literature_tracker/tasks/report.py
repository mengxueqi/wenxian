from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..paths import DB_PATH, REPORTS_DIR, ensure_runtime_directories
from ..presentation import build_markdown_report, build_snapshot
from ..storage import SQLiteRepository


def build_report(
    *,
    db_path: Path = DB_PATH,
    source_name: str | None = None,
    output_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    ensure_runtime_directories()
    output_dir.mkdir(parents=True, exist_ok=True)
    repository = SQLiteRepository(db_path)
    repository.initialize()

    run_id = repository.start_report_run(source_name or "__all__")
    try:
        snapshot = build_snapshot(repository, source_name=source_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = "Literature Tracker Report"
        if source_name:
            title = f"Literature Tracker Report - {source_name}"
        markdown = build_markdown_report(snapshot, title=title)

        report_filename = f"{timestamp}_report.md"
        if source_name:
            safe_source = "".join(ch if ch.isalnum() else "_" for ch in source_name).strip("_")
            report_filename = f"{timestamp}_{safe_source}_report.md"

        report_path = output_dir / report_filename
        latest_path = output_dir / "latest_report.md"
        report_path.write_text(markdown, encoding="utf-8")
        latest_path.write_text(markdown, encoding="utf-8")

        focus_count = len(snapshot["focus_cards"])
        repository.finish_report_run(
            run_id,
            status="success",
            item_count=focus_count,
        )
    except Exception as exc:
        repository.finish_report_run(
            run_id,
            status="failed",
            item_count=0,
            error_message=str(exc),
        )
        raise

    return {
        "status": "success",
        "source_name": source_name or "__all__",
        "report_path": str(report_path),
        "latest_report_path": str(latest_path),
        "focus_items": focus_count,
        "metrics": snapshot["metrics"],
    }
