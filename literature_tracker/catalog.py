"""Current articles, interest matches, and search without loading change history."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from html import unescape
import re
from typing import Any

from .presentation import metadata_keywords
from .storage import SQLiteRepository


THEME_LABELS = {
    "synthetic_biology": "合成生物学",
    "crispr": "CRISPR / 基因编辑",
    "p450_enzyme": "P450 酶",
    "kred": "酮还原酶（KRED）",
    "gamma_lactone": "γ-内酯",
    "delta_lactone": "δ-内酯",
    "lactone": "内酯",
    "flavors_and_fragrances": "香精香料",
    "benzyl_alcohol": "苯甲醇",
    "phenethyl_alcohol": "苯乙醇",
    "carbonyl_reductase": "羰基还原酶",
    "p450bs_beta": "P450BSβ",
    "sclareol": "香紫苏醇",
    "macrocyclic_lactone": "大环内酯",
    "squalene": "角鲨烯",
    "heme": "血红素",
    "directed_evolution": "定向进化",
    "lactone_product_extraction": "内酯产物提取",
}


_NOTICE_TITLE = re.compile(
    r"^(?:"
    r"(?:(?:author|publisher|editor)(?:['’]s)?\s+)?(?:corrigendum|corrigenda|erratum|errata)\b"
    r"|(?:(?:author|publisher|editor)(?:['’]s)?\s+)?corrections?"
    r"(?=\s*(?:$|[:：\[\]\(\"“‘–—-])|\s+(?:to|for)\b)"
    r"|(?:retraction|withdrawal)(?:\s+(?:notice|note|statement))?"
    r"(?=\s*(?:$|[:：\[\(\"“‘–—-])|\s+(?:to|for)\b|\s+of\s*(?:[:：\"“‘]|(?:the\s+)?(?:research\s+)?article\b))"
    r"|(?:retracted|withdrawn)(?=\s*(?:$|[:：\[])|\s+by\s+(?:the\s+)?authors?\b)"
    r"|notice\s+of\s+(?:correction|retraction|withdrawal)\b"
    r"|(?:editorial\s+)?expression\s+of\s+concern\b"
    r"|(?:更正|勘误|撤稿|撤回)(?:通知|声明|启事)?(?=\s*(?:$|[:：《“「\[\(（–—-]))"
    r"|关于[《“].+[》”]的(?:更正|勘误|撤稿|撤回)(?:通知|声明|启事)?\s*$"
    r")",
    re.IGNORECASE,
)


def is_publication_notice(title: str) -> bool:
    # Match editorial title labels, not scientific uses of "correction" in the paper.
    plain_title = unescape(re.sub(r"<[^>]+>", "", title)).lstrip("\ufeff \t\r\n[({【（")
    return bool(_NOTICE_TITLE.match(plain_title))


def build_catalog(repository: SQLiteRepository) -> list[dict[str, Any]]:
    tracking = {row["paper_id"]: row for row in repository.fetch_tracking_items()}
    cards = []
    for paper in repository.fetch_papers():
        item = tracking.get(paper.id, {})
        metadata = item.get("metadata") or {}
        card = {
            "paper_id": paper.id,
            "title": paper.canonical_title,
            "authors": paper.normalized_authors,
            "abstract": paper.abstract,
            "source_name": paper.source_name,
            "sources": sorted({paper.source_name, *paper.metadata.get("observed_sources", [])}),
            "journal_name": paper.journal_name,
            "published_at": paper.published_at or "",
            "created_at": paper.created_at,
            "doi": paper.doi or "",
            "article_url": paper.article_url,
            "keywords": metadata_keywords(paper.metadata),
            "source_summary": str(paper.metadata.get("feed_summary") or ""),
            "themes": list(metadata.get("themes") or []),
            "author_hits": list(metadata.get("author_hits") or []),
            "priority_score": float(item.get("priority_score") or 0),
            "is_publication_notice": is_publication_notice(paper.canonical_title),
            "is_retracted": str(paper.metadata.get("is_retracted", "")).strip().casefold() in {"true", "1", "yes"},
        }
        card["recommendation_reason"] = recommendation_reason(card)
        card["_search_text"] = " ".join(
            [
                card["title"], card["authors"], card["abstract"], card["doi"],
                card["journal_name"], *card["sources"], *card["keywords"],
                *card["themes"], *[THEME_LABELS.get(t, t) for t in card["themes"]],
                card["source_summary"],
            ]
        ).casefold()
        cards.append(card)
    return cards


def recommendation_reason(card: dict[str, Any]) -> str:
    parts = []
    if card["themes"]:
        parts.append("命中主题：" + "、".join(THEME_LABELS.get(t, t) for t in card["themes"]))
    if card["author_hits"]:
        parts.append("关注作者：" + "、".join(card["author_hits"]))
    return "；".join(parts)


def select_articles(
    cards: list[dict[str, Any]],
    *,
    query: str = "",
    source_name: str | None = None,
    themes: list[str] | None = None,
    days: int | None = None,
    recommended_only: bool = False,
    sort_by: str = "published_desc",
    now: date | None = None,
) -> list[dict[str, Any]]:
    today = now or date.today()
    terms = query.casefold().split()
    selected_themes = set(themes or [])
    results = []
    for card in cards:
        if source_name and source_name not in card["sources"]:
            continue
        if selected_themes and not selected_themes.intersection(card["themes"]):
            continue
        if recommended_only:
            if card.get("is_publication_notice") or card.get("is_retracted"):
                continue
            if not (card["themes"] or card["author_hits"]):
                continue
        if terms and not all(term in card["_search_text"] for term in terms):
            continue
        if days is not None:
            added = _article_date(card["created_at"])
            if added is None or not today - timedelta(days=days) <= added <= today:
                continue
        results.append(card)

    if sort_by == "title_asc":
        return sorted(results, key=lambda card: (card["title"].casefold(), card["paper_id"]))
    def sort_key(card: dict[str, Any]) -> tuple:
        published = _article_date(card["published_at"]) or date.min
        added = _article_date(card["created_at"]) or date.min
        if sort_by == "priority_desc":
            return card["priority_score"], added, published, card["paper_id"]
        if sort_by == "added_desc":
            return added, card["paper_id"]
        return published, added, card["paper_id"]
    return sorted(results, key=sort_key, reverse=True)


def source_summary(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter = Counter()
    latest: dict[str, str] = {}
    for card in cards:
        for source in card["sources"]:
            counts[source] += 1
            latest[source] = max(latest.get(source, ""), card["created_at"])
    return [
        {"数据源": source, "文章数": counts[source], "最近入库": latest[source][:10]}
        for source in sorted(counts)
    ]


def article_export_rows(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "标题": card["title"], "作者": card["authors"],
            "期刊": card["journal_name"], "数据源": "；".join(card["sources"]),
            "发表日期": card["published_at"], "入库日期": card["created_at"],
            "DOI": card["doi"], "摘要": card["abstract"],
            "关键词": "；".join(card["keywords"]),
            "推荐理由": card["recommendation_reason"], "原文链接": card["article_url"],
        }
        for card in cards
    ]


def _article_date(value: str) -> date | None:
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%Y-%m", "%Y/%m/%d", "%Y/%m", "%B %Y", "%b %Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
