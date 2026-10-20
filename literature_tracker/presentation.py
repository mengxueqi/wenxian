from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import StringIO
from typing import Any

from .models import SourceConfig, StoredPaper, StoredPaperChange
from .storage import SQLiteRepository

PRIORITY_REVIEW_THRESHOLD = 0.85
TRACKING_STATUS_ALIASES = {
    "priority": "review",
}

SOURCE_HEALTH_LABELS = {
    "healthy": "正常", "running": "抓取中", "never": "未运行", "stale": "超过两天未更新",
    "partial": "部分失败", "failed": "失败", "blocked": "访问受限", "disabled": "已停用",
}
SOURCE_HEALTH_ORDER = {state: index for index, state in enumerate(SOURCE_HEALTH_LABELS)}


def build_source_status_rows(health: list[dict[str, Any]], sources: list[SourceConfig]) -> list[dict[str, str]]:
    configured = {source.source_name: source.canonical_url for source in sources}
    visible = [row for row in health if row["source_name"] in configured]
    visible.sort(key=lambda row: (SOURCE_HEALTH_ORDER.get(row["health_state"], 5), row["source_name"].casefold()))
    return [
        {
            "数据源": row["source_name"],
            "状态": SOURCE_HEALTH_LABELS.get(row["health_state"], row["health_state"]),
            "网址": configured[row["source_name"]],
        }
        for row in visible
    ]


def build_snapshot(
    repository: SQLiteRepository,
    *,
    source_name: str | None = None,
) -> dict[str, Any]:
    papers = repository.fetch_papers(source_name=source_name)
    changes = repository.fetch_paper_changes(source_name=source_name)
    insights = repository.fetch_paper_insights(source_name=source_name)
    tracking_items = repository.fetch_tracking_items(source_name=source_name)
    source_health, pipeline_health = build_run_health(
        repository,
        source_name=source_name,
    )

    papers_by_id = {paper.id: paper for paper in papers}
    changes_by_paper = _group_changes_by_paper(changes)
    insights_by_paper = _group_insights_by_paper(insights)
    tracking_by_paper = {item["paper_id"]: item for item in tracking_items}

    focus_cards: list[dict[str, Any]] = []
    for paper_id, tracking in tracking_by_paper.items():
        paper = papers_by_id.get(paper_id)
        if paper is None:
            continue
        tracking_status = _tracking_status_label(tracking["tracking_status"])
        tracking_metadata = tracking.get("metadata") if tracking.get("metadata") else {}
        paper_metadata = paper.metadata or {}
        themes = tracking_metadata.get("themes", [])
        latest_change = changes_by_paper.get(paper_id, [None])[0]
        best_insight = insights_by_paper.get(paper_id, [None])[0]
        focus_cards.append(
            {
                "paper_id": paper.id,
                "title": paper.canonical_title,
                "abstract": paper.abstract,
                "source_name": paper.source_name,
                "journal_name": paper.journal_name,
                "published_at": paper.published_at,
                "created_at": paper.created_at,
                "updated_at": paper.updated_at,
                "doi": paper.doi,
                "article_url": paper.article_url,
                "tracking_status": tracking_status,
                "priority_score": tracking["priority_score"],
                "note": tracking["note"],
                "latest_change_type": getattr(latest_change, "change_type", None),
                "latest_change_summary": getattr(latest_change, "summary", None),
                "latest_change_at": getattr(latest_change, "detected_at", None),
                "insight_summary": best_insight["summary"] if best_insight else None,
                "insight_reason": best_insight["reason"] if best_insight else None,
                "keywords": metadata_keywords(paper_metadata),
                "source_summary": _source_summary(paper_metadata),
                "themes": themes,
            }
        )
    focus_cards = sort_focus_cards(focus_cards, sort_by="priority_desc")

    source_summary = _build_source_summary(
        papers,
        changes,
        tracking_items,
        insights,
    )
    change_breakdown = Counter(change.change_type for change in changes)
    tracking_breakdown = Counter(
        _tracking_status_label(item["tracking_status"]) for item in tracking_items
    )

    return {
        "metrics": {
            "papers": len(papers),
            "changes": len(changes),
            "insights": len(insights),
            "tracking_items": len(tracking_items),
        },
        "focus_cards": focus_cards,
        "source_summary": source_summary,
        "change_breakdown": dict(change_breakdown),
        "tracking_breakdown": dict(tracking_breakdown),
        "papers": papers,
        "changes": changes,
        "insights": insights,
        "tracking_items": tracking_items,
        "source_health": source_health,
        "pipeline_health": pipeline_health,
    }


def build_run_health(
    repository: SQLiteRepository,
    *,
    source_name: str | None = None,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(days=2),
    include_pipeline: bool = True,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    current_time = now or datetime.now()
    source_rows = [
        _with_health_state(
            row,
            current_time=current_time,
            stale_after=stale_after,
            configured_status=str(row.get("source_status") or ""),
            run_status=str(row.get("last_run_status") or "never"),
        )
        for row in repository.fetch_source_health(source_name=source_name)
    ]
    pipeline_rows = [
        _with_health_state(
            row,
            current_time=current_time,
            stale_after=stale_after,
            configured_status="active",
            run_status=str(row.get("status") or "never"),
        )
        for row in (repository.fetch_pipeline_health() if include_pipeline else [])
    ]
    return source_rows, pipeline_rows


def build_markdown_report(
    snapshot: dict[str, Any],
    *,
    title: str = "Literature Tracker Report",
) -> str:
    metrics = snapshot["metrics"]
    lines: list[str] = [
        f"# {title}",
        "",
        "## Overview",
        "",
        f"- Papers: `{metrics['papers']}`",
        f"- Changes: `{metrics['changes']}`",
        f"- Insights: `{metrics['insights']}`",
        f"- Tracking Items: `{metrics['tracking_items']}`",
        "",
        "## Tracking Queue",
        "",
    ]

    focus_cards = snapshot["focus_cards"]
    if not focus_cards:
        lines.extend(["No tracking items yet.", ""])
    else:
        for index, card in enumerate(focus_cards, start=1):
            lines.extend(
                [
                    f"### {index}. {card['title']}",
                    "",
                    f"- Source: `{card['source_name']}`",
                    f"- Journal: `{card['journal_name']}`",
                    f"- Published: `{card['published_at'] or 'unknown'}`",
                    f"- Status: `{card['tracking_status']}`",
                    f"- Priority Score: `{card['priority_score']}`",
                    f"- Latest Change: `{card['latest_change_type'] or 'n/a'}`",
                    f"- Summary: {card['insight_summary'] or card['latest_change_summary'] or 'n/a'}",
                    f"- Reason: {card['insight_reason'] or card['note'] or 'n/a'}",
                    f"- URL: {card['article_url'] or 'n/a'}",
                    "",
                ]
            )

    lines.extend(["## Source Summary", ""])
    if snapshot["source_summary"]:
        for row in snapshot["source_summary"]:
            lines.append(
                f"- `{row['source_name']}`: papers `{row['papers']}`, changes `{row['changes']}`, "
                f"tracking `{row['tracking_items']}`, high-priority `{row['priority_items']}`"
            )
    else:
        lines.append("- No source summary available yet.")
    lines.append("")

    lines.extend(["## Change Breakdown", ""])
    if snapshot["change_breakdown"]:
        for change_type, count in snapshot["change_breakdown"].items():
            lines.append(f"- `{change_type}`: `{count}`")
    else:
        lines.append("- No changes detected yet.")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def sort_focus_cards(cards: list[dict[str, Any]], *, sort_by: str) -> list[dict[str, Any]]:
    sorters = {
        "priority_desc": lambda card: (
            float(card["priority_score"] or 0),
            str(card["published_at"] or ""),
            card["title"].casefold(),
        ),
        "published_desc": lambda card: (
            str(card["published_at"] or ""),
            float(card["priority_score"] or 0),
            card["title"].casefold(),
        ),
        "title_asc": lambda card: card["title"].casefold(),
        "source_asc": lambda card: (
            card["source_name"].casefold(),
            card["title"].casefold(),
        ),
    }
    reverse = sort_by in {"priority_desc", "published_desc"}
    key_fn = sorters.get(sort_by, sorters["priority_desc"])
    return sorted(cards, key=key_fn, reverse=reverse)


def rows_to_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                ordered_keys.append(key)
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ordered_keys)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in ordered_keys})
    return buffer.getvalue().encode("utf-8-sig")


def _group_changes_by_paper(changes: list[StoredPaperChange]) -> dict[int, list[StoredPaperChange]]:
    grouped: dict[int, list[StoredPaperChange]] = defaultdict(list)
    for change in changes:
        grouped[change.paper_id].append(change)
    return grouped


def _group_insights_by_paper(insights: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for insight in insights:
        grouped[insight["paper_id"]].append(insight)
    for paper_id in grouped:
        grouped[paper_id].sort(
            key=lambda row: (float(row["score"] or 0), int(row["change_id"] or 0)),
            reverse=True,
        )
    return grouped


def _build_source_summary(
    papers: list[StoredPaper],
    changes: list[StoredPaperChange],
    tracking_items: list[dict[str, Any]],
    insights: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    papers_counter = Counter(paper.source_name for paper in papers)
    changes_counter = Counter(change.source_name for change in changes)
    tracking_counter = Counter(item["source_name"] for item in tracking_items)
    priority_counter = Counter(
        item["source_name"]
        for item in tracking_items
        if _is_priority_item(item)
    )
    insight_counter = Counter(item["source_name"] for item in insights)
    all_sources = sorted(
        set(papers_counter) | set(changes_counter) | set(tracking_counter) | set(insight_counter)
    )

    return [
        {
            "source_name": source,
            "papers": papers_counter.get(source, 0),
            "changes": changes_counter.get(source, 0),
            "insights": insight_counter.get(source, 0),
            "tracking_items": tracking_counter.get(source, 0),
            "priority_items": priority_counter.get(source, 0),
        }
        for source in all_sources
    ]


def _tracking_status_label(value: object) -> str:
    status = str(value or "").strip()
    return TRACKING_STATUS_ALIASES.get(status.casefold(), status)


def metadata_keywords(metadata: dict[str, Any]) -> list[str]:
    raw_keywords = metadata.get("keywords", [])
    if isinstance(raw_keywords, str):
        values = [
            item.strip()
            for item in raw_keywords.replace("|", ";").split(";")
            if item.strip()
        ]
    elif isinstance(raw_keywords, list):
        values = [str(item).strip() for item in raw_keywords if str(item).strip()]
    else:
        values = []

    seen: set[str] = set()
    keywords: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(value)
    return keywords


def _source_summary(metadata: dict[str, Any]) -> str:
    return str(metadata.get("feed_summary") or "").strip()


def _is_priority_item(item: dict[str, Any]) -> bool:
    try:
        return float(item.get("priority_score") or 0) >= PRIORITY_REVIEW_THRESHOLD
    except (TypeError, ValueError):
        return False


def _with_health_state(
    row: dict[str, object],
    *,
    current_time: datetime,
    stale_after: timedelta,
    configured_status: str,
    run_status: str,
) -> dict[str, object]:
    normalized_source_status = configured_status.strip().casefold()
    normalized_run_status = run_status.strip().casefold()
    if normalized_source_status and normalized_source_status != "active":
        health_state = normalized_source_status
    elif normalized_run_status in {"failed", "partial", "running", "never"}:
        health_state = normalized_run_status
    else:
        completed_at = _parse_datetime(row.get("completed_at"))
        if completed_at is None:
            health_state = "never"
        elif current_time - completed_at > stale_after:
            health_state = "stale"
        else:
            health_state = "healthy"
    return {"health_state": health_state, **row}


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
