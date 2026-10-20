from __future__ import annotations

from html import escape
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from ..catalog import (
    THEME_LABELS, article_export_rows, build_catalog, select_articles, source_summary,
)
from ..config import load_author_watchlist, load_sources, load_theme_watchlist
from ..paths import DB_PATH, SOURCES_CSV
from ..presentation import build_run_health, build_source_status_rows, rows_to_csv_bytes
from ..storage import SQLiteRepository
from ..tasks.update_job import UpdateJob


TIME_WINDOWS = {"最近 30 天入库": 30, "最近 7 天入库": 7, "最近 90 天入库": 90, "全部": None}
SORT_OPTIONS = {"发表时间": "published_desc", "入库时间": "added_desc", "推荐分": "priority_desc", "标题": "title_asc"}


def _file_stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return 0, 0


@st.cache_resource(show_spinner=False)
def _prepare_repository(db_path: str, sources_stamp: tuple[int, int]) -> SQLiteRepository:
    repository = SQLiteRepository(Path(db_path))
    repository.initialize()
    repository.sync_sources(load_sources())
    return repository


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def _load_catalog(db_path: str, database_stamp: tuple) -> list[dict[str, Any]]:
    return build_catalog(SQLiteRepository(Path(db_path)))


def _current_catalog(db_path: Path) -> list[dict[str, Any]]:
    return _load_catalog(str(db_path.resolve()), (_file_stamp(db_path), _file_stamp(Path(str(db_path) + "-wal"))))


@st.cache_resource(show_spinner=False)
def _update_job(db_path: str) -> UpdateJob:
    return UpdateJob(Path(db_path))


@st.fragment(run_every=5)
def _render_update_controls(db_path: Path) -> None:
    job = _update_job(str(db_path.resolve()))
    running = job.future is not None and not job.future.done()
    if st.button("立即更新", type="primary", width="stretch", disabled=running):
        job.start()
        running = True
    if st.button("刷新页面数据", width="stretch"):
        _load_catalog.clear()
        st.rerun()
    if running:
        st.info("正在后台更新，可在数据源页查看实时状态。")
    elif job.future is not None:
        try:
            result = job.future.result()
        except Exception as exc:
            result = {"status": "failed", "error": str(exc)}
        if result["status"] == "success":
            count = result.get("stages", {}).get("crawl", {}).get("stored_raw_records", 0)
            st.success(f"更新完成，本次采集 {count} 条记录。")
        elif result["status"] == "partial":
            st.warning("更新已完成，部分来源异常，可在数据源页查看。")
        else:
            st.error("更新失败：" + str(result.get("error") or "请检查运行日志。"))


def render_app(db_path: Path = DB_PATH) -> None:
    st.set_page_config(page_title="文献监控", layout="wide")
    st.title("文献监控")
    repository = _prepare_repository(str(db_path.resolve()), _file_stamp(SOURCES_CSV))

    with st.sidebar:
        _render_update_controls(db_path)
    cards = _current_catalog(db_path)
    st.sidebar.caption(f"文献库共 {len(cards):,} 篇")
    tabs = st.tabs(["推荐", "搜索", "数据源"], key="main_view", on_change="rerun")
    if tabs[0].open:
        with tabs[0]:
            _render_recommendations(cards)
    if tabs[1].open:
        with tabs[1]:
            _render_search(cards)
    if tabs[2].open:
        with tabs[2]:
            _render_sources(repository)


def _render_recommendations(cards: list[dict[str, Any]]) -> None:
    columns = st.columns(2)
    window = columns[0].selectbox("入库范围", list(TIME_WINDOWS), key="recommendation_window")
    limit = columns[1].selectbox("显示篇数", [10, 20, 50], key="recommendation_limit")
    results = select_articles(cards, days=TIME_WINDOWS[window], recommended_only=True, sort_by="priority_desc")
    st.caption(f"命中关注主题或作者 {len(results)} 篇，按现有评分排序，显示前 {min(limit, len(results))} 篇。")
    with st.expander("当前推荐规则"):
        theme_rules = load_theme_watchlist()
        author_rules = load_author_watchlist()
        st.write("关注主题：" + "、".join(THEME_LABELS.get(str(r["theme_name"]), str(r["theme_name"])) for r in theme_rules))
        st.write(f"关注作者：{len(author_rules)} 位；评分沿用主题、作者、变化类型及近期活跃度的现有权重。")
        st.caption("推荐时间范围按首次入库时间计算。")
    if not results:
        st.info("该时间范围内暂无匹配文章，可切换到“全部”或在搜索页查看文献库。")
    for card in results[:limit]:
        _render_article(card)


def _render_search(cards: list[dict[str, Any]]) -> None:
    query = st.text_input("搜索文章", placeholder="标题、作者、DOI、摘要或关键词；多个词用空格分隔", key="article_query")
    columns = st.columns(4)
    sources = sorted({source for card in cards for source in card["sources"]})
    source = columns[0].selectbox("数据源", ["全部数据源", *sources], key="article_source")
    topics = sorted({theme for card in cards for theme in card["themes"]})
    themes = columns[1].multiselect("关注主题", topics, format_func=lambda value: THEME_LABELS.get(value, value), key="article_themes")
    window = columns[2].selectbox("入库范围", ["全部", *[label for label in TIME_WINDOWS if label != "全部"]], key="search_window")
    sort_label = columns[3].selectbox("排序", list(SORT_OPTIONS), key="article_sort")
    results = select_articles(
        cards, query=query, source_name=None if source == "全部数据源" else source,
        themes=themes, days=TIME_WINDOWS[window], sort_by=SORT_OPTIONS[sort_label],
    )
    if not results:
        st.info("没有符合条件的文章。")
        return
    page_size = 25
    page_count = (len(results) + page_size - 1) // page_size
    filter_key = (query, source, tuple(themes), window, sort_label)
    if st.session_state.get("search_filter_key") != filter_key:
        st.session_state["search_page"] = 1
        st.session_state["search_filter_key"] = filter_key
    st.session_state["search_page"] = min(st.session_state.get("search_page", 1), page_count)
    controls = st.columns([1, 2])
    page = controls[0].number_input("页码", min_value=1, max_value=page_count, step=1, key="search_page")
    controls[1].download_button(
        "导出搜索结果 CSV", data=rows_to_csv_bytes(article_export_rows(results)),
        file_name="articles.csv", mime="text/csv", on_click="ignore",
    )
    start = (page - 1) * page_size
    st.caption(f"共 {len(results):,} 篇 · 第 {page}/{page_count} 页 · 显示第 {start + 1}–{min(start + page_size, len(results))} 篇")
    for card in results[start : start + page_size]:
        _render_article(card)


@st.fragment(run_every=10)
def _render_sources(repository: SQLiteRepository) -> None:
    health, _ = build_run_health(repository, include_pipeline=False)
    st.markdown("#### 数据源状态")
    st.caption(f"每 10 秒自动刷新 · 最后刷新 {datetime.now():%H:%M:%S} · 失败来源排后")
    rows = build_source_status_rows(health, load_sources())
    if rows:
        st.dataframe(
            rows, width="stretch", hide_index=True,
            column_config={"网址": st.column_config.LinkColumn("网址", width="large")},
        )
    else:
        st.info("暂无数据源。")
    st.markdown("#### Source Summary")
    summary = source_summary(_current_catalog(repository.db_path))
    if summary:
        st.dataframe(summary, width="stretch", hide_index=True)
    else:
        st.info("暂无来源统计。")


def _render_article(card: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown(
            "<div style='font-size:1.08rem;font-weight:600;line-height:1.4'>"
            + escape(card["title"]) + "</div>", unsafe_allow_html=True,
        )
        st.caption(f"{card['journal_name'] or card['source_name']} · {card['published_at'] or '发表日期未提供'}")
        if card["recommendation_reason"]:
            st.caption(f"推荐分 {card['priority_score']:.2f} · {card['recommendation_reason']}")
        abstract = card["abstract"]
        preview = abstract or card["source_summary"]
        if not abstract:
            st.caption("来源未提供摘要。" if not preview else "来源未提供摘要，以下为来源简介。")
        if preview:
            text = " ".join(preview.split())
            st.write(text if len(text) <= 360 else text[:360].rstrip() + "…")
        with st.expander("摘要与详细信息"):
            if abstract:
                st.write(abstract)
            if card["authors"]:
                st.write("作者：" + card["authors"])
            if card["doi"]:
                st.write("DOI：" + card["doi"])
            if card["keywords"]:
                st.write("关键词：" + "、".join(card["keywords"]))
            st.caption("来源：" + "、".join(card["sources"]) + " · 入库：" + card["created_at"][:10])
        if card["article_url"]:
            st.link_button("阅读原文", card["article_url"])
