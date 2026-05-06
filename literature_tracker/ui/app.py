from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from ..paths import DB_PATH
from ..presentation import (
    SORT_OPTIONS,
    build_change_rows,
    build_filter_options,
    build_filtered_snapshot,
    build_markdown_report,
    build_new_paper_batch_rows,
    build_new_paper_rows,
    build_paper_rows,
    build_recent_focus_cards,
    build_snapshot,
    build_tracking_rows,
    rows_to_csv_bytes,
)
from ..storage import SQLiteRepository
from ..tasks import crawl_sources, run_change_detection, run_insight_build, run_process_stage


def render_app(db_path: Path = DB_PATH) -> None:
    st.set_page_config(
        page_title="Literature Tracker",
        layout="wide",
    )
    st.title("Literature Tracker")
    st.caption("Monitor sources, detect changes, and maintain a review queue.")

    repository = SQLiteRepository(db_path)
    repository.initialize()

    if st.sidebar.button("一键抓取", type="primary", use_container_width=True):
        with st.spinner("一键抓取中..."):
            st.session_state["one_click_crawl_result"] = _run_one_click_crawl(db_path)

    if "one_click_crawl_result" in st.session_state:
        result = st.session_state["one_click_crawl_result"]
        st.sidebar.success(
            "抓取完成："
            f"{result['raw_records']} 条原始记录，"
            f"{result['papers']} 篇论文，"
            f"{result['changes']} 条变化，"
            f"{result['tracking_items']} 个追踪项。"
        )

    all_snapshot = build_snapshot(repository)
    tracking_rows = build_tracking_rows(all_snapshot)
    change_rows = build_change_rows(all_snapshot)
    paper_rows = build_paper_rows(all_snapshot)
    report_title = "Literature Tracker Report"
    report_markdown = build_markdown_report(all_snapshot, title=report_title)

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

    metrics = all_snapshot["metrics"]
    metric_columns = st.columns(4)
    metric_columns[0].metric("Papers", metrics["papers"])
    metric_columns[1].metric("Changes", metrics["changes"])
    metric_columns[2].metric("Insights", metrics["insights"])
    metric_columns[3].metric("Tracking", metrics["tracking_items"])

    tabs = st.tabs(["Focus", "Library", "Dashboard", "Change Analysis"])

    with tabs[0]:
        focus_cards = build_recent_focus_cards(all_snapshot, days=30, limit=10)
        if focus_cards:
            for card in focus_cards:
                _render_literature_card(card)
        else:
            st.info("No focus papers entered the library in the last 30 days.")

    with tabs[1]:
        source_options = [
            "All Sources",
            *[row["source_name"] for row in all_snapshot["source_summary"]],
        ]
        selected_source = st.selectbox("Source", source_options, index=0)
        effective_source = None if selected_source == "All Sources" else selected_source
        library_snapshot = (
            all_snapshot
            if effective_source is None
            else build_snapshot(repository, source_name=effective_source)
        )
        filter_options = build_filter_options(library_snapshot)

        filter_top_columns = st.columns([2, 1])
        query = filter_top_columns[0].text_input(
            "Search",
            placeholder="Title, DOI, theme, summary...",
        )
        tracking_statuses = filter_top_columns[1].multiselect(
            "Tracking status",
            filter_options["tracking_statuses"],
        )

        max_priority = max(
            (float(card["priority_score"] or 0) for card in library_snapshot["focus_cards"]),
            default=1.0,
        )
        slider_max = max(1.0, round(max_priority, 2))
        filter_bottom_columns = st.columns([1, 1, 1, 1])
        change_types = filter_bottom_columns[0].multiselect(
            "Change type",
            filter_options["change_types"],
        )
        themes = filter_bottom_columns[1].multiselect(
            "Keywords",
            filter_options["themes"],
        )
        min_priority = filter_bottom_columns[2].slider(
            "Minimum priority",
            min_value=0.0,
            max_value=slider_max,
            value=0.0,
            step=0.01,
        )
        sort_label = filter_bottom_columns[3].selectbox(
            "Sort",
            list(SORT_OPTIONS.values()),
            index=0,
        )
        sort_by = next(
            key
            for key, value in SORT_OPTIONS.items()
            if value == sort_label
        )

        library_filtered_snapshot = build_filtered_snapshot(
            library_snapshot,
            query=query,
            tracking_statuses=tracking_statuses,
            change_types=change_types,
            themes=themes,
            min_priority=min_priority,
            sort_by=sort_by,
        )
        active_filters = _build_active_filters(
            source_name=effective_source,
            query=query,
            tracking_statuses=tracking_statuses,
            change_types=change_types,
            themes=themes,
            min_priority=min_priority,
            sort_label=sort_label,
        )
        if active_filters:
            st.caption("Active filters: " + " | ".join(active_filters))

        if library_filtered_snapshot["focus_cards"]:
            for card in library_filtered_snapshot["focus_cards"]:
                _render_literature_card(card)
        else:
            st.info("No tracking items match the current filters.")

    with tabs[2]:
        summary_columns = st.columns(3)
        with summary_columns[0]:
            st.markdown("#### Source Summary")
            if all_snapshot["source_summary"]:
                st.dataframe(
                    all_snapshot["source_summary"],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No visible source summary rows.")

        with summary_columns[1]:
            st.markdown("#### Change Breakdown")
            if all_snapshot["change_breakdown"]:
                st.dataframe(
                    [
                        {"change_type": key, "count": value}
                        for key, value in all_snapshot["change_breakdown"].items()
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No visible changes.")

        with summary_columns[2]:
            st.markdown("#### Tracking Breakdown")
            if all_snapshot["tracking_breakdown"]:
                st.dataframe(
                    [
                        {"tracking_status": key, "count": value}
                        for key, value in all_snapshot["tracking_breakdown"].items()
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No visible tracking items.")

    with tabs[3]:
        new_paper_batches = build_new_paper_batch_rows(all_snapshot)
        if new_paper_batches:
            batch_labels = [
                (
                    f"{batch['batch_date']} | {batch['new_papers']} new | "
                    f"{batch['existing_papers_before_batch']} existing before"
                )
                for batch in new_paper_batches
            ]
            selected_batch_label = st.selectbox("Batch date", batch_labels)
            selected_batch = new_paper_batches[batch_labels.index(selected_batch_label)]
            selected_batch_date = selected_batch["batch_date"]

            batch_columns = st.columns(4)
            batch_columns[0].metric("New papers", selected_batch["new_papers"])
            batch_columns[1].metric(
                "Existing before",
                selected_batch["existing_papers_before_batch"],
            )
            batch_columns[2].metric("Sources", selected_batch["source_count"])
            batch_columns[3].metric("Priority", selected_batch["priority_items"])

            new_paper_rows = build_new_paper_rows(
                all_snapshot,
                batch_date=selected_batch_date,
            )
            st.dataframe(new_paper_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No new paper batches match the current filters.")


def _build_active_filters(
    *,
    source_name: str | None,
    query: str,
    tracking_statuses: list[str],
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
    if change_types:
        parts.append("change=" + ",".join(change_types))
    if themes:
        parts.append("keywords=" + ",".join(themes))
    if min_priority > 0:
        parts.append(f"min_priority={min_priority:.2f}")
    if sort_label != SORT_OPTIONS["priority_desc"]:
        parts.append(f"sort={sort_label}")
    return parts


def _run_one_click_crawl(db_path: Path) -> dict[str, int]:
    crawl_summary = crawl_sources(db_path=db_path)
    process_summary = run_process_stage(db_path=db_path)
    change_summary = run_change_detection(db_path=db_path)
    insight_summary = run_insight_build(db_path=db_path)

    return {
        "raw_records": int(crawl_summary["stored_raw_records"]),
        "papers": int(process_summary["upserted_papers"]),
        "changes": int(change_summary["detected_changes"]),
        "tracking_items": int(insight_summary["upserted_tracking_items"]),
    }


def _render_literature_card(card: dict[str, object]) -> None:
    with st.container(border=True):
        st.markdown(
            "<div style='font-size: 1.08rem; font-weight: 650; "
            f"line-height: 1.35;'>{escape(str(card['title']))}</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"{card['source_name']} | {card['journal_name']} | "
            f"{card['published_at'] or 'unknown date'}"
        )
        meta_columns = st.columns(2)
        with meta_columns[0]:
            _render_compact_metric(
                "Priority",
                f"{float(card['priority_score'] or 0):.2f}",
            )
        with meta_columns[1]:
            _render_compact_metric("Status", str(card["tracking_status"] or "n/a"))
        abstract_preview, abstract_rest = _split_leading_sentences(
            str(card["abstract"] or ""),
            sentence_count=2,
        )
        st.write(abstract_preview)
        if abstract_rest:
            with st.expander("More abstract"):
                st.write(abstract_rest)
        themes = card.get("themes", [])
        st.write(
            "Keywords: "
            + (", ".join(str(theme) for theme in themes) if themes else "n/a")
        )
        if card["article_url"]:
            st.markdown(f"[Open Article]({card['article_url']})")


def _render_compact_metric(label: str, value: str) -> None:
    st.markdown(
        "<div style='margin: 0.3rem 0 0.8rem 0;'>"
        f"<div style='font-size: 0.78rem; color: #6b7280; line-height: 1.2;'>{escape(label)}</div>"
        f"<div style='font-size: 1.05rem; font-weight: 600; line-height: 1.3; color: #111827;'>{escape(value)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _preview_text(value: str, *, max_chars: int = 360) -> tuple[str, bool]:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized, False
    return normalized[:max_chars].rstrip() + "...", True


def _split_leading_sentences(value: str, *, sentence_count: int) -> tuple[str, str]:
    normalized = " ".join(value.split())
    if not normalized:
        return "No abstract available.", ""

    abbreviations = {"e.g", "i.e", "etc", "fig", "eq", "no", "al", "sp", "spp", "vs"}
    sentence_ends: list[int] = []
    for index, char in enumerate(normalized):
        if char not in ".!?。！？":
            continue
        prefix = normalized[:index].rstrip()
        suffix = normalized[index + 1 :].lstrip()
        previous_token = prefix.rsplit(" ", 1)[-1].rstrip(".").casefold()
        if char == "." and previous_token in abbreviations:
            continue
        if char == "." and suffix and suffix[0].islower():
            continue
        sentence_ends.append(index + 1)
        if len(sentence_ends) >= sentence_count:
            split_at = sentence_ends[-1]
            preview = normalized[:split_at].strip()
            rest = normalized[split_at:].strip()
            return preview, rest

    preview, has_more = _preview_text(normalized, max_chars=220)
    if not has_more:
        return preview, ""
    return preview, normalized[len(preview.rstrip(".")) :].strip()
