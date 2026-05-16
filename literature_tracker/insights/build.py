from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from ..models import (
    PaperInsightRecord,
    StoredPaper,
    StoredPaperChange,
    TrackingItemRecord,
)
from ..paths import AUTHOR_WATCHLIST_CSV


THEME_KEYWORDS = {
    "synthetic_biology": [
        "synthetic biology",
        "synbio",
        "synthetic biomanufacturing",
        "microbial cell factory",
        "cell factory",
    ],
    "crispr": [
        "crispr",
        "crispr-cas",
        "crispr/cas",
        "cas9",
        "cas12",
        "gene editing",
        "genome editing",
        "base editing",
        "prime editing",
    ],
    "p450_enzyme": [
        "p450 enzyme",
        "p450 enzymes",
        "cytochrome p450",
        "cytochrome p450 enzyme",
        "cytochrome p450 monooxygenase",
        "cyp450",
        "p450 monooxygenase",
        "p450 biocatalyst",
    ],
    "kred": [
        "kred",
        "kreds",
        "ketoreductase",
        "ketoreductases",
        "keto reductase",
        "keto reductases",
        "keto-reductase",
        "keto-reductases",
    ],
    "gamma_lactone": [
        "gamma-lactone",
        "gamma lactone",
        "gamma lactones",
        "gamma-butyrolactone",
        "gamma butyrolactone",
        "\u03b3-lactone",
        "\u03b3 lactone",
        "\u03b3-lactones",
        "\u03b3-butyrolactone",
        "\u03b3 butyrolactone",
    ],
    "flavors_and_fragrances": [
        "flavor",
        "flavors",
        "flavour",
        "flavours",
        "fragrance",
        "fragrances",
        "flavor compound",
        "flavour compound",
        "aroma compound",
        "aroma compounds",
        "aroma chemical",
        "aroma chemicals",
        "odorant",
        "odorants",
        "flavors and fragrances",
        "flavours and fragrances",
    ],
    "benzyl_alcohol": [
        "benzyl alcohol",
        "phenylmethanol",
        "benzenemethanol",
    ],
    "phenethyl_alcohol": [
        "phenethyl alcohol",
        "phenylethyl alcohol",
        "phenylethanol",
        "2-phenylethanol",
        "2 phenylethanol",
        "beta-phenylethyl alcohol",
        "\u03b2-phenylethyl alcohol",
    ],
    "lactone": [
        "lactone",
        "lactones",
        "cyclic ester",
        "cyclic esters",
    ],
    "carbonyl_reductase": [
        "carbonyl reductase",
        "carbonyl reductases",
        "carbonyl-reductase",
        "carbonyl-reductases",
        "nadph-dependent carbonyl reductase",
        "carbonyl reducing enzyme",
    ],
    "p450bs_beta": [
        "p450bs beta",
        "p450bsbeta",
        "p450bs-beta",
        "p450 bs beta",
        "p450 bs-beta",
        "p450bs\u03b2",
        "p450 bs\u03b2",
        "cyp152a1",
    ],
    "delta_lactone": [
        "delta-lactone",
        "delta lactone",
        "delta lactones",
        "delta-decalactone",
        "delta decalactone",
        "delta-dodecalactone",
        "delta dodecalactone",
        "\u03b4-lactone",
        "\u03b4 lactone",
        "\u03b4-lactones",
        "\u03b4-decalactone",
        "\u03b4 decalactone",
        "\u03b4-dodecalactone",
        "\u03b4 dodecalactone",
    ],
}

CHANGE_BASE_SCORES = {
    "new_paper": 0.05,
    "content_updated": 0.1,
    "correction_notice": 0.16,
    "retraction_notice": 0.2,
}

DEFAULT_CHANGE_BASE_SCORE = 0.12
RECENT_ACTIVITY_SCORE = 0.2
THEME_SCORE_PER_HIT = 0.15
THEME_SCORE_CAP = 0.4
AUTHOR_HIT_BASE_SCORE = 0.4
AUTHOR_HIT_EXTRA_SCORE = 0.0
AUTHOR_HIT_SCORE_CAP = 0.4

CHANGE_SUMMARY_PREFIX = {
    "new_paper": "新增文献",
    "content_updated": "文献更新",
    "correction_notice": "勘误/更正信号",
    "retraction_notice": "撤稿/撤回信号",
}

CHANGE_REASONS = {
    "new_paper": "这是新进入监控范围的文献，适合加入待读列表并判断是否需要持续跟踪。",
    "content_updated": "同一篇文献在站点上出现内容更新，可能涉及摘要、元数据或附件变化，值得复核差异。",
    "correction_notice": "勘误或更正通常意味着文献记录发生了实质修订，适合尽快复核原文与修订内容。",
    "retraction_notice": "撤稿或撤回会直接影响文献可用性和后续引用，应该优先人工核查。",
}


def build_insight_outputs(
    papers: list[StoredPaper],
    changes: list[StoredPaperChange],
) -> tuple[list[PaperInsightRecord], list[TrackingItemRecord]]:
    papers_by_id = {paper.id: paper for paper in papers}
    insights: list[PaperInsightRecord] = []

    for change in changes:
        paper = papers_by_id.get(change.paper_id)
        if paper is None:
            continue
        insights.append(_build_insight(paper, change))

    tracking_items = _build_tracking_items(papers_by_id, insights)
    return insights, tracking_items


def _build_insight(paper: StoredPaper, change: StoredPaperChange) -> PaperInsightRecord:
    themes = _extract_themes(paper)
    author_hits = _extract_author_hits(paper)
    score, score_factors = _score_change(paper, change, themes, author_hits)
    score_label = _score_label(score)
    summary_prefix = CHANGE_SUMMARY_PREFIX.get(change.change_type, "文献变化")
    reason = CHANGE_REASONS.get(change.change_type, "这条变化值得进一步核查。")
    if themes:
        reason = f"{reason} 当前主题信号包括：{', '.join(themes)}。"
    if author_hits:
        reason = f"{reason} 命中重点作者：{', '.join(author_hits)}。"

    return PaperInsightRecord(
        change_id=change.id,
        paper_id=paper.id,
        insight_key=f"{paper.paper_key}|change:{change.id}",
        source_name=paper.source_name,
        summary=f"{summary_prefix}：{paper.canonical_title}",
        reason=reason,
        score=score,
        score_label=score_label,
        metadata={
            "paper_key": paper.paper_key,
            "change_key": change.change_key,
            "change_type": change.change_type,
            "article_url": paper.article_url,
            "doi": paper.doi,
            "published_at": paper.published_at,
            "themes": themes,
            "author_hits": author_hits,
            "score_factors": score_factors,
            "source_change_summary": change.summary,
            "observed_content_hash": change.metadata.get("observed_content_hash"),
        },
    )


def _build_tracking_items(
    papers_by_id: dict[int, StoredPaper],
    insights: list[PaperInsightRecord],
) -> list[TrackingItemRecord]:
    grouped: dict[int, list[PaperInsightRecord]] = defaultdict(list)
    for insight in insights:
        grouped[insight.paper_id].append(insight)

    items: list[TrackingItemRecord] = []
    for paper_id, paper_insights in grouped.items():
        paper = papers_by_id.get(paper_id)
        if paper is None:
            continue
        selected = max(
            paper_insights,
            key=lambda insight: (insight.score, insight.change_id),
        )
        items.append(
            TrackingItemRecord(
                paper_id=paper.id,
                tracking_key=f"paper:{paper.paper_key}",
                source_name=paper.source_name,
                tracking_status=_tracking_status(selected.score_label),
                priority_score=selected.score,
                note=selected.reason,
                metadata={
                    "paper_key": paper.paper_key,
                    "latest_change_id": selected.change_id,
                    "latest_insight_key": selected.insight_key,
                    "latest_score_label": selected.score_label,
                    "article_url": paper.article_url,
                    "doi": paper.doi,
                    "themes": selected.metadata.get("themes", []),
                    "author_hits": selected.metadata.get("author_hits", []),
                    "score_factors": selected.metadata.get("score_factors", {}),
                },
            )
        )
    return items


def _extract_themes(paper: StoredPaper) -> list[str]:
    keywords = paper.metadata.get("keywords", [])
    if isinstance(keywords, list):
        keyword_text = " ".join(str(keyword) for keyword in keywords)
    else:
        keyword_text = str(keywords or "")
    text = f"{paper.canonical_title} {paper.abstract} {keyword_text}".lower()
    themes: list[str] = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            themes.append(theme)
    return themes


def _extract_author_hits(paper: StoredPaper) -> list[str]:
    paper_authors = _split_author_names(paper.normalized_authors)
    if not paper_authors:
        return []

    hits: list[str] = []
    for entry in load_author_watchlist():
        names = [entry["author_name"], *entry["aliases"]]
        if any(
            _author_name_matches(paper_author, watched_name)
            for paper_author in paper_authors
            for watched_name in names
        ):
            hits.append(entry["author_name"])
    return _dedupe_preserving_order(hits)


def _score_change(
    paper: StoredPaper,
    change: StoredPaperChange,
    themes: list[str],
    author_hits: list[str],
) -> tuple[float, dict[str, float]]:
    score = CHANGE_BASE_SCORES.get(change.change_type, DEFAULT_CHANGE_BASE_SCORE)
    factors = {"change_type": score}
    theme_score = min(THEME_SCORE_CAP, THEME_SCORE_PER_HIT * len(themes))
    score += theme_score
    factors["theme_hits"] = theme_score
    if author_hits:
        author_score = min(
            AUTHOR_HIT_SCORE_CAP,
            AUTHOR_HIT_BASE_SCORE + AUTHOR_HIT_EXTRA_SCORE * (len(author_hits) - 1),
        )
        score += author_score
        factors["author_hits"] = author_score
    if _is_recent(paper.metadata.get("last_seen_at")):
        score += RECENT_ACTIVITY_SCORE
        factors["recent_activity"] = RECENT_ACTIVITY_SCORE
    final_score = round(min(score, 0.99), 2)
    factors["total"] = final_score
    return final_score, factors


def _score_label(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def _tracking_status(score_label: str) -> str:
    if score_label == "high":
        return "review"
    if score_label == "medium":
        return "pending"
    return "watchlist"


def _is_recent(value: object) -> bool:
    if not value:
        return False
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m"):
        try:
            observed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    else:
        return False
    return (datetime.now() - observed).days <= 30


@lru_cache(maxsize=1)
def load_author_watchlist(csv_path: Path = AUTHOR_WATCHLIST_CSV) -> list[dict[str, object]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        entries: list[dict[str, object]] = []
        for row in reader:
            author_name = (row.get("author_name") or "").strip()
            if not author_name:
                continue
            aliases = [
                alias.strip()
                for alias in (row.get("aliases") or "").split("|")
                if alias.strip()
            ]
            entries.append(
                {
                    "author_name": author_name,
                    "aliases": aliases,
                    "field_hint": (row.get("field_hint") or "").strip(),
                }
            )
    return entries


def _split_author_names(authors: str) -> list[str]:
    return [
        author.strip()
        for author in re.split(r"\s*;\s*", authors or "")
        if author.strip()
    ]


def _author_name_matches(paper_author: str, watched_name: str) -> bool:
    paper_tokens = _name_tokens(paper_author)
    watched_tokens = _name_tokens(watched_name)
    if not paper_tokens or not watched_tokens:
        return False
    if " ".join(watched_tokens) == " ".join(paper_tokens):
        return True
    if len(watched_tokens) == 1:
        return watched_tokens[0] in paper_tokens

    surname = watched_tokens[-1]
    given_tokens = [token for token in watched_tokens[:-1] if len(token) > 1]
    if surname not in paper_tokens:
        return False
    if not given_tokens:
        return True
    return any(token in paper_tokens for token in given_tokens)


def _name_tokens(value: str) -> list[str]:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", value.casefold())
    return [token for token in normalized.split() if token]


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
