from __future__ import annotations

from typing import Iterable

from ..models import PaperChangeCandidate, StoredPaper


CORRECTION_KEYWORDS = (
    "correction",
    "erratum",
    "corrigendum",
    "更正",
    "勘误",
)

RETRACTION_KEYWORDS = (
    "retraction",
    "retracted",
    "withdrawn",
    "withdrawal",
    "撤稿",
    "撤回",
)


def build_change_candidates(
    papers: list[StoredPaper],
    existing_state: dict[int, list[dict[str, object]]],
) -> list[PaperChangeCandidate]:
    candidates: list[PaperChangeCandidate] = []
    for paper in papers:
        history = existing_state.get(paper.id, [])
        observed_hash = _str_value(paper.metadata.get("raw_record_content_hash"))
        observed_hashes = {
            _str_value(change["metadata"].get("observed_content_hash"))
            for change in history
            if isinstance(change.get("metadata"), dict)
        }

        if not history:
            candidates.append(_build_new_paper_change(paper, observed_hash))
        elif observed_hash and observed_hash not in observed_hashes:
            candidates.append(_build_content_updated_change(paper, history, observed_hash))

        title_and_abstract = f"{paper.canonical_title} {paper.abstract}".lower()
        correction_matches = _matched_keywords(title_and_abstract, CORRECTION_KEYWORDS)
        retraction_matches = _matched_keywords(title_and_abstract, RETRACTION_KEYWORDS)

        if correction_matches and _should_emit_signal(history, "correction_notice", observed_hash):
            candidates.append(
                _build_signal_change(
                    paper,
                    "correction_notice",
                    "检测到勘误/更正信号",
                    observed_hash,
                    correction_matches,
                )
            )
        if retraction_matches and _should_emit_signal(history, "retraction_notice", observed_hash):
            candidates.append(
                _build_signal_change(
                    paper,
                    "retraction_notice",
                    "检测到撤稿/撤回信号",
                    observed_hash,
                    retraction_matches,
                )
            )
    return candidates


def _build_new_paper_change(
    paper: StoredPaper,
    observed_hash: str,
) -> PaperChangeCandidate:
    return PaperChangeCandidate(
        paper_id=paper.id,
        paper_key=paper.paper_key,
        source_name=paper.source_name,
        change_type="new_paper",
        summary=f"发现新文献：{paper.canonical_title}",
        metadata={
            "change_key": f"{paper.paper_key}|new_paper",
            "observed_content_hash": observed_hash,
            "article_url": paper.article_url,
            "doi": paper.doi,
            "published_at": paper.published_at,
            "first_seen_at": paper.metadata.get("first_seen_at"),
            "last_seen_at": paper.metadata.get("last_seen_at"),
            "seen_count": paper.metadata.get("seen_count"),
        },
    )


def _build_content_updated_change(
    paper: StoredPaper,
    history: list[dict[str, object]],
    observed_hash: str,
) -> PaperChangeCandidate:
    previous_hash = ""
    for change in reversed(history):
        metadata = change.get("metadata")
        if isinstance(metadata, dict):
            previous_hash = _str_value(metadata.get("observed_content_hash"))
            if previous_hash:
                break

    return PaperChangeCandidate(
        paper_id=paper.id,
        paper_key=paper.paper_key,
        source_name=paper.source_name,
        change_type="content_updated",
        summary=f"文献内容发生更新：{paper.canonical_title}",
        metadata={
            "change_key": f"{paper.paper_key}|content_updated|{observed_hash}",
            "observed_content_hash": observed_hash,
            "previous_content_hash": previous_hash,
            "article_url": paper.article_url,
            "doi": paper.doi,
            "published_at": paper.published_at,
            "last_seen_at": paper.metadata.get("last_seen_at"),
            "seen_count": paper.metadata.get("seen_count"),
        },
    )


def _build_signal_change(
    paper: StoredPaper,
    change_type: str,
    label: str,
    observed_hash: str,
    matched_keywords: list[str],
) -> PaperChangeCandidate:
    signal_key = observed_hash or paper.canonical_title.casefold()
    return PaperChangeCandidate(
        paper_id=paper.id,
        paper_key=paper.paper_key,
        source_name=paper.source_name,
        change_type=change_type,
        summary=f"{label}：{paper.canonical_title}",
        metadata={
            "change_key": f"{paper.paper_key}|{change_type}|{signal_key}",
            "observed_content_hash": observed_hash,
            "matched_keywords": matched_keywords,
            "article_url": paper.article_url,
            "doi": paper.doi,
        },
    )


def _matched_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _should_emit_signal(
    history: list[dict[str, object]],
    signal_type: str,
    observed_hash: str,
) -> bool:
    for change in history:
        if change.get("change_type") != signal_type:
            continue
        metadata = change.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if _str_value(metadata.get("observed_content_hash")) == observed_hash:
            return False
    return True


def _str_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
