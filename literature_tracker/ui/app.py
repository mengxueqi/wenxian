from __future__ import annotations

from pathlib import Path

import streamlit as st

from ..paths import DB_PATH
from ..presentation import (
    SORT_OPTIONS,
    build_change_rows,
    build_filter_options,
    build_filtered_snapshot,
    build_markdown_report,
    build_paper_rows,
    build_snapshot,
    build_tracking_rows,
    rows_to_csv_bytes,
)
from ..storage import SQLiteRepository


def render_app(db_path: Path = DB_PATH) -> None:
    st.set_page_config(
        page_title="Literature Tracker",
        layout="wide",
    )
    st.title("Literature Tracker")
    st.caption("Monitor sources, detect changes, and maintain a review queue.")

    repository = SQLiteRepository(db_path)
    repository.initialize()

    all_snapshot = build_snapshot(repository)
    source_options = ["All Sources"] + [row["source_name"] for row in all_snapshot["source_summary"]]
    selected_source = st.sidebar.selectbox("Source", source_options, index=0)
    effective_source = None if selected_source == "All Sources" else selected_source
    snapshot = (
        all_snapshot
        if effective_source is None
        else build_snapshot(repository, source_name=effective_source)
    )

    filter_options = build_filter_options(snapshot)
    st.sidebar.header("Filters")
    query = st.sidebar.text_input("Search", placeholder="Title, DOI, theme, summary...")
    tracking_statuses = st.sidebar.multiselect(
        "Tracking status",
        filter_options["tracking_statuses"],
    )
    score_labels = st.sidebar.multiselect("Score label", filter_options["score_labels"])
    change_types = st.sidebar.multiselect("Change type", filter_options["change_types"])
    themes = st.sidebar.multiselect("Themes", filter_options["themes"])

    max_priority = max(
        (float(card["priority_score"] or 0) for card in snapshot["focus_cards"]),
        default=1.0,
    )
    slider_max = max(1.0, round(max_priority, 2))
    min_priority = st.sidebar.slider(
        "Minimum priority",
        min_value=0.0,
        max_value=slider_max,
        value=0.0,
        step=0.01,
    )
    sort_label = st.sidebar.selectbox(
        "Sort focus cards",
        list(SORT_OPTIONS.values()),
        index=0,
    )
    sort_by = next(
        key
        for key, value in SORT_OPTIONS.items()
        if value == sort_label
    )

    filtered_snapshot = build_filtered_snapshot(
        snapshot,
        query=query,
        tracking_statuses=tracking_statuses,
        score_labels=score_labels,
        change_types=change_types,
        themes=themes,
        min_priority=min_priority,
        sort_by=sort_by,
    )

    tracking_rows = build_tracking_rows(filtered_snapshot)
    change_rows = build_change_rows(filtered_snapshot)
    paper_rows = build_paper_rows(filtered_snapshot)
    report_title = "Literature Tracker Report"
    if effective_source:
        report_title = f"{report_title} - {effective_source}"
    report_markdown = build_markdown_report(filtered_snapshot, title=report_title)

    st.sidebar.header("Exports")
    st.sidebar.download_button(
        "Tracking CSV",
        data=rows_to_csv_bytes(tracking_rows),
        file_name="tracking_queue.csv",
        mime="text/csv",
        disabled=not tracking_rows,
        use_container_width=True,
    )
    st.sidebar.download_button(
        "Changes CSV",
        data=rows_to_csv_bytes(change_rows),
        file_name="change_analysis.csv",
        mime="text/csv",
        disabled=not change_rows,
        use_container_width=True,
    )
    st.sidebar.download_button(
        "Papers CSV",
        data=rows_to_csv_bytes(paper_rows),
        file_name="papers.csv",
        mime="text/csv",
        disabled=not paper_rows,
        use_container_width=True,
    )
    st.sidebar.download_button(
        "Report Markdown",
        data=report_markdown.encode("utf-8"),
        file_name="literature_tracker_report.md",
        mime="text/markdown",
        disabled=not report_markdown.strip(),
        use_container_width=True,
    )

    metrics = filtered_snapshot["metrics"]
    metric_columns = st.columns(4)
    metric_columns[0].metric("Papers", metrics["papers"])
    metric_columns[1].metric("Changes", metrics["changes"])
    metric_columns[2].metric("Insights", metrics["insights"])
    metric_columns[3].metric("Tracking", metrics["tracking_items"])

    active_filters = _build_active_filters(
        source_name=effective_source,
        query=query,
        tracking_statuses=tracking_statuses,
        score_labels=score_labels,
        change_types=change_types,
        themes=themes,
        min_priority=min_priority,
        sort_label=sort_label,
    )
    if active_filters:
        st.caption("Active filters: " + " | ".join(active_filters))

    tabs = st.tabs(["Dashboard", "Change Analysis", "Tracking Queue", "Papers", "Report Preview"])

    with tabs[0]:
        st.subheader("Dashboard")
        summary_left, summary_right = st.columns([3, 2])
        with summary_left:
            if filtered_snapshot["focus_cards"]:
                for card in filtered_snapshot["focus_cards"]:
                    with st.container(border=True):
                        left, right = st.columns([3, 2])
                        left.markdown(f"### {card['title']}")
                        left.caption(
                            " | ".join(
                                value
                                for value in (
                                    card["source_name"],
                                    card["journal_name"],
                                    card["published_at"] or "unknown",
                                )
                                if value
                            )
                        )
                        left.write(
                            card["insight_summary"]
                            or card["latest_change_summary"]
                            or "No summary available."
                        )
                        left.write(card["insight_reason"] or card["note"] or "No reason available.")
                        if card["article_url"]:
                            left.markdown(f"[Open Article]({card['article_url']})")
                        right.metric("Priority", f"{float(card['priority_score'] or 0):.2f}")
                        right.metric("Status", card["tracking_status"])
                        right.metric("Score Label", card["score_label"] or "n/a")
                        if card["themes"]:
                            right.write("Themes: " + ", ".join(card["themes"]))
            else:
                st.info("No papers match the current filters.")

        with summary_right:
            st.markdown("#### Source Summary")
            if filtered_snapshot["source_summary"]:
                st.dataframe(
                    filtered_snapshot["source_summary"],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No visible source summary rows.")

            st.markdown("#### Change Breakdown")
            if filtered_snapshot["change_breakdown"]:
                st.dataframe(
                    [
                        {"change_type": key, "count": value}
                        for key, value in filtered_snapshot["change_breakdown"].items()
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No visible changes.")

            st.markdown("#### Tracking Breakdown")
            if filtered_snapshot["tracking_breakdown"]:
                st.dataframe(
                    [
                        {"tracking_status": key, "count": value}
                        for key, value in filtered_snapshot["tracking_breakdown"].items()
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No visible tracking items.")

    with tabs[1]:
        st.subheader("Change Analysis")
        if change_rows:
            st.dataframe(change_rows, use_container_width=True, hide_index=True)
            insights_by_change = {row["change_id"]: row for row in filtered_snapshot["insights"]}
            for change in filtered_snapshot["changes"]:
                insight = insights_by_change.get(change.id)
                with st.expander(f"{change.change_type} | {change.summary}", expanded=False):
                    st.write(f"Source: {change.source_name}")
                    st.write(f"Detected At: {change.detected_at}")
                    if insight:
                        st.write(f"Insight Summary: {insight['summary']}")
                        st.write(f"Reason: {insight['reason']}")
                        st.write(f"Score: {insight['score']} ({insight['score_label']})")
                    st.json(change.metadata)
        else:
            st.info("No changes match the current filters.")

    with tabs[2]:
        st.subheader("Tracking Queue")
        if tracking_rows:
            st.dataframe(tracking_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No tracking items match the current filters.")

    with tabs[3]:
        st.subheader("Papers")
        if paper_rows:
            st.dataframe(paper_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No papers match the current filters.")

    with tabs[4]:
        st.subheader("Report Preview")
        st.download_button(
            "Download Markdown",
            data=report_markdown.encode("utf-8"),
            file_name="literature_tracker_report.md",
            mime="text/markdown",
            use_container_width=False,
        )
        st.code(report_markdown, language="markdown")


def _build_active_filters(
    *,
    source_name: str | None,
    query: str,
    tracking_statuses: list[str],
    score_labels: list[str],
    change_types: list[str],
    themes: list[str],
    min_priority: float,
    sort_label: str,
) -> list[str]:
    parts: list[str] = []
    if source_name:
        parts.append(f"source={source_name}")
    if query.strip():
        parts.append(f"query={query.strip()}")
    if tracking_statuses:
        parts.append("status=" + ",".join(tracking_statuses))
    if score_labels:
        parts.append("score=" + ",".join(score_labels))
    if change_types:
        parts.append("change=" + ",".join(change_types))
    if themes:
        parts.append("theme=" + ",".join(themes))
    if min_priority > 0:
        parts.append(f"min_priority={min_priority:.2f}")
    if sort_label != SORT_OPTIONS["priority_desc"]:
        parts.append(f"sort={sort_label}")
    return parts
