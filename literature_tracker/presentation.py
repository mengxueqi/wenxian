from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import StringIO
from typing import Any

from .models import StoredPaper, StoredPaperChange
from .storage import SQLiteRepository

SORT_OPTIONS = {
    "priority_desc": "Priority (high to low)",
    "published_desc": "Published date (newest first)",
    "title_asc": "Title (A-Z)",
    "source_asc": "Source (A-Z)",
}

PRIORITY_REVIEW_THRESHOLD = 0.85
TRACKING_STATUS_ALIASES = {
    "priority": "review",
}


def build_snapshot(
    repository: SQLiteRepository,
    *,
    source_name: str | None = None,
) -> dict[str, Any]:
    papers = repository.fetch_papers(source_name=source_name)
    changes = repository.fetch_paper_changes(source_name=source_name)
    insights = repository.fetch_paper_insights(source_name=source_name)
    tracking_items = repository.fetch_tracking_items(source_name=source_name)

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
                "keywords": _metadata_keywords(paper_metadata),
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
    }


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


def build_filter_options(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "tracking_statuses": sorted(
            {
                card["tracking_status"]
                for card in snapshot["focus_cards"]
                if card.get("tracking_status")
            }
        ),
        "change_types": sorted(
            {change.change_type for change in snapshot["changes"] if change.change_type}
        ),
        "themes": sorted(
            {
                theme
                for card in snapshot["focus_cards"]
                for theme in card.get("themes", [])
                if theme
            }
        ),
    }


def build_filtered_snapshot(
    snapshot: dict[str, Any],
    *,
    query: str = "",
    tracking_statuses: list[str] | None = None,
    change_types: list[str] | None = None,
    themes: list[str] | None = None,
    min_priority: float = 0.0,
    sort_by: str = "priority_desc",
) -> dict[str, Any]:
    tracking_status_set = set(tracking_statuses or [])
    change_type_set = set(change_types or [])
    theme_set = set(themes or [])

    allowed_paper_ids = {
        change.paper_id
        for change in snapshot["changes"]
        if not change_type_set or change.change_type in change_type_set
    }

    filtered_cards = [
        card
        for card in snapshot["focus_cards"]
        if card["paper_id"] in allowed_paper_ids
        and _card_matches(
            card,
            query=query,
            tracking_statuses=tracking_status_set,
            themes=theme_set,
            min_priority=min_priority,
        )
    ]
    filtered_cards = sort_focus_cards(filtered_cards, sort_by=sort_by)
    visible_paper_ids = {card["paper_id"] for card in filtered_cards}

    filtered_papers = [paper for paper in snapshot["papers"] if paper.id in visible_paper_ids]
    filtered_changes = [
        change
        for change in snapshot["changes"]
        if change.paper_id in visible_paper_ids
        and (not change_type_set or change.change_type in change_type_set)
    ]
    filtered_change_ids = {change.id for change in filtered_changes}
    filtered_insights = [
        insight
        for insight in snapshot["insights"]
        if insight["paper_id"] in visible_paper_ids
        and (
            not change_type_set
            or insight["change_id"] in filtered_change_ids
        )
    ]
    filtered_tracking_items = [
        item for item in snapshot["tracking_items"] if item["paper_id"] in visible_paper_ids
    ]

    return {
        "metrics": {
            "papers": len(filtered_papers),
            "changes": len(filtered_changes),
            "insights": len(filtered_insights),
            "tracking_items": len(filtered_tracking_items),
        },
        "focus_cards": filtered_cards,
        "source_summary": _build_source_summary(
            filtered_papers,
            filtered_changes,
            filtered_tracking_items,
            filtered_insights,
        ),
        "change_breakdown": dict(Counter(change.change_type for change in filtered_changes)),
        "tracking_breakdown": dict(
            Counter(
                _tracking_status_label(item["tracking_status"])
                for item in filtered_tracking_items
            )
        ),
        "papers": filtered_papers,
        "changes": filtered_changes,
        "insights": filtered_insights,
        "tracking_items": filtered_tracking_items,
    }


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


def build_recent_focus_cards(
    snapshot: dict[str, Any],
    *,
    days: int = 30,
    limit: int = 10,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current_time = now or datetime.now()
    window = timedelta(days=days)
    recent_cards = [
        card
        for card in snapshot["focus_cards"]
        if _is_recent_card(card, now=current_time, window=window)
    ]
    return sort_focus_cards(recent_cards, sort_by="priority_desc")[:limit]


def build_tracking_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "paper_id": card["paper_id"],
            "source_name": card["source_name"],
            "title": card["title"],
            "journal_name": card["journal_name"],
            "published_at": card["published_at"],
            "tracking_status": card["tracking_status"],
            "priority_score": card["priority_score"],
            "latest_change_type": card["latest_change_type"],
            "themes": ", ".join(card["themes"]),
            "article_url": card["article_url"],
        }
        for card in snapshot["focus_cards"]
    ]


def build_change_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    insights_by_change = {row["change_id"]: row for row in snapshot["insights"]}
    papers_by_id = {paper.id: paper for paper in snapshot["papers"]}
    rows: list[dict[str, Any]] = []
    for change in snapshot["changes"]:
        paper = papers_by_id.get(change.paper_id)
        insight = insights_by_change.get(change.id)
        rows.append(
            {
                "change_id": change.id,
                "paper_id": change.paper_id,
                "source_name": change.source_name,
                "title": paper.canonical_title if paper else "",
                "change_type": change.change_type,
                "change_summary": change.summary,
                "detected_at": change.detected_at,
                "priority_score": insight["score"] if insight else None,
                "themes": ", ".join((insight or {}).get("metadata", {}).get("themes", [])),
                "reason": insight["reason"] if insight else "",
                "article_url": paper.article_url if paper else "",
            }
        )
    return rows


def build_new_paper_batch_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = build_new_paper_rows(snapshot)
    if not rows:
        return []

    rows_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_date[row["batch_date"]].append(row)

    batches: list[dict[str, Any]] = []
    for batch_date, batch_rows in rows_by_date.items():
        paper_ids = {row["paper_id"] for row in batch_rows}
        source_names = {row["source_name"] for row in batch_rows if row["source_name"]}
        priority_items = sum(
            1
            for row in batch_rows
            if float(row["priority_score"] or 0) >= PRIORITY_REVIEW_THRESHOLD
        )
        batches.append(
            {
                "batch_date": batch_date,
                "new_papers": len(paper_ids),
                "existing_papers_before_batch": _count_existing_papers_before_batch(
                    snapshot,
                    rows,
                    batch_date,
                ),
                "source_count": len(source_names),
                "sources": ", ".join(sorted(source_names)),
                "priority_items": priority_items,
            }
        )

    return sorted(batches, key=lambda row: row["batch_date"], reverse=True)


def build_new_paper_rows(
    snapshot: dict[str, Any],
    *,
    batch_date: str | None = None,
) -> list[dict[str, Any]]:
    papers_by_id = {paper.id: paper for paper in snapshot["papers"]}
    insights_by_change = {row["change_id"]: row for row in snapshot["insights"]}
    tracking_by_paper = {item["paper_id"]: item for item in snapshot["tracking_items"]}

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for change in snapshot["changes"]:
        if change.change_type != "new_paper":
            continue
        change_date = _date_part(change.detected_at)
        if batch_date is not None and change_date != batch_date:
            continue
        dedupe_key = (change_date, change.paper_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        paper = papers_by_id.get(change.paper_id)
        insight = insights_by_change.get(change.id)
        tracking = tracking_by_paper.get(change.paper_id, {})
        insight_metadata = (insight or {}).get("metadata", {})
        tracking_metadata = tracking.get("metadata", {}) if tracking else {}
        themes = insight_metadata.get("themes") or tracking_metadata.get("themes", [])
        themes_text = ", ".join(themes) if isinstance(themes, list) else str(themes or "")
        priority_score = tracking.get("priority_score") if tracking else None
        if priority_score is None and insight:
            priority_score = insight["score"]
        rows.append(
            {
                "batch_date": change_date,
                "detected_at": change.detected_at,
                "paper_id": change.paper_id,
                "source_name": change.source_name,
                "journal_name": paper.journal_name if paper else "",
                "title": paper.canonical_title if paper else "",
                "doi": paper.doi if paper else "",
                "published_at": paper.published_at if paper else "",
                "priority_score": priority_score,
                "tracking_status": _tracking_status_label(
                    tracking.get("tracking_status", "")
                )
                if tracking
                else "",
                "themes": themes_text,
                "reason": insight["reason"] if insight else "",
                "article_url": paper.article_url if paper else "",
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["batch_date"],
            str(row["detected_at"] or ""),
            float(row["priority_score"] or 0),
            row["title"].casefold(),
        ),
        reverse=True,
    )


def build_paper_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    tracking_by_paper = {item["paper_id"]: item for item in snapshot["tracking_items"]}

    rows: list[dict[str, Any]] = []
    for paper in snapshot["papers"]:
        tracking = tracking_by_paper.get(paper.id)
        rows.append(
            {
                "paper_id": paper.id,
                "source_name": paper.source_name,
                "journal_name": paper.journal_name,
                "title": paper.canonical_title,
                "doi": paper.doi,
                "published_at": paper.published_at,
                "status": paper.status,
                "tracking_status": _tracking_status_label(tracking["tracking_status"])
                if tracking
                else "",
                "priority_score": tracking["priority_score"] if tracking else None,
                "themes": ", ".join((tracking or {}).get("metadata", {}).get("themes", [])),
                "article_url": paper.article_url,
            }
        )
    return rows


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


def _card_matches(
    card: dict[str, Any],
    *,
    query: str,
    tracking_statuses: set[str],
    themes: set[str],
    min_priority: float,
) -> bool:
    if tracking_statuses and card["tracking_status"] not in tracking_statuses:
        return False
    if themes and not themes.intersection(set(card["themes"] or [])):
        return False
    if float(card["priority_score"] or 0) < min_priority:
        return False
    if not query.strip():
        return True
    normalized_query = query.strip().casefold()
    text_blob = " ".join(
        str(value or "")
        for value in (
            card["title"],
            card["source_name"],
            card["journal_name"],
            card["doi"],
            card["latest_change_type"],
            card["latest_change_summary"],
            card["insight_summary"],
            card["insight_reason"],
            " ".join(card["themes"] or []),
        )
    ).casefold()
    return normalized_query in text_blob


def _tracking_status_label(value: object) -> str:
    status = str(value or "").strip()
    return TRACKING_STATUS_ALIASES.get(status.casefold(), status)


def _metadata_keywords(metadata: dict[str, Any]) -> list[str]:
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


def _is_recent_card(
    card: dict[str, Any],
    *,
    now: datetime,
    window: timedelta,
) -> bool:
    created_at = _parse_datetime(card.get("created_at"))
    if created_at is None:
        return False
    age = now - created_at
    return timedelta(0) <= age <= window


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


def _count_existing_papers_before_batch(
    snapshot: dict[str, Any],
    new_paper_rows: list[dict[str, Any]],
    batch_date: str,
) -> int:
    first_new_date_by_paper: dict[int, str] = {}
    for row in new_paper_rows:
        paper_id = int(row["paper_id"])
        current_date = first_new_date_by_paper.get(paper_id)
        if current_date is None or row["batch_date"] < current_date:
            first_new_date_by_paper[paper_id] = row["batch_date"]

    count = 0
    for paper in snapshot["papers"]:
        first_new_date = first_new_date_by_paper.get(paper.id)
        if first_new_date:
            if first_new_date < batch_date:
                count += 1
            continue

        paper_date = _date_part(paper.created_at or paper.updated_at or paper.published_at)
        if paper_date and paper_date < batch_date:
            count += 1
    return count


def _date_part(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return "unknown"


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
