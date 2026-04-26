from __future__ import annotations

import argparse
import json
from pathlib import Path

from .paths import DB_PATH, ensure_runtime_directories
from .storage import SQLiteRepository
from .tasks import (
    build_report,
    crawl_sources,
    run_change_detection,
    run_insight_build,
    run_process_stage,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Literature tracker CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="Initialize SQLite schema")
    init_db_parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )

    crawl_parser = subparsers.add_parser("crawl", help="Collect raw records from sources")
    crawl_parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )
    crawl_parser.add_argument(
        "--source",
        help="Optional source name filter, e.g. 合成生物学",
    )
    crawl_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional per-source record limit.",
    )

    process_parser = subparsers.add_parser(
        "process",
        help="Normalize raw_records into papers",
    )
    process_parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )
    process_parser.add_argument(
        "--source",
        help="Optional source name filter, e.g. 合成生物学",
    )
    process_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional raw-record limit for one processing run.",
    )

    detect_parser = subparsers.add_parser(
        "detect-changes",
        help="Build paper_changes from normalized papers",
    )
    detect_parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )
    detect_parser.add_argument(
        "--source",
        help="Optional source name filter, e.g. 合成生物学",
    )
    detect_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional paper limit for one detection run.",
    )

    insight_parser = subparsers.add_parser(
        "build-insights",
        help="Build paper_insights and tracking_items from paper_changes",
    )
    insight_parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )
    insight_parser.add_argument(
        "--source",
        help="Optional source name filter, e.g. 合成生物学",
    )
    insight_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional paper/change limit for one insight run.",
    )

    report_parser = subparsers.add_parser(
        "build-report",
        help="Generate a markdown report from the current tracking snapshot",
    )
    report_parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to the SQLite database file.",
    )
    report_parser.add_argument(
        "--source",
        help="Optional source name filter, e.g. 合成生物学",
    )
    return parser


def main() -> None:
    ensure_runtime_directories()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        repository = SQLiteRepository(args.db)
        repository.initialize()
        print(f"Initialized database at {args.db}")
        return

    if args.command == "crawl":
        summary = crawl_sources(db_path=args.db, source_name=args.source, limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "process":
        summary = run_process_stage(
            db_path=args.db,
            source_name=args.source,
            limit=args.limit,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "detect-changes":
        summary = run_change_detection(
            db_path=args.db,
            source_name=args.source,
            limit=args.limit,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "build-insights":
        summary = run_insight_build(
            db_path=args.db,
            source_name=args.source,
            limit=args.limit,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "build-report":
        summary = build_report(
            db_path=args.db,
            source_name=args.source,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
