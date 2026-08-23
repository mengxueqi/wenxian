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

FIELD_LABELS = {
    "title": "标题",
    "authors": "作者",
    "abstract": "摘要",
    "published_at": "发布日期",
    "doi": "DOI",
    "language": "语言",
    "keywords": "关键词",
    "pdf_url": "PDF 地址",
    "online_date": "在线日期",
    "openalex_id": "OpenAlex ID",
    "pubmed_id": "PubMed ID",
    "is_retracted": "撤稿状态",
    "is_corrected": "更正状态",
}


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
            field_changes = _field_changes_since_last_event(paper, history)
            if field_changes:
                candidates.append(
                    _build_content_updated_change(
                        paper,
                        history,
                        observed_hash,
                        field_changes,
                    )
                )

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
            "field_snapshot": _paper_field_snapshot(paper),
        },
    )


def _build_content_updated_change(
    paper: StoredPaper,
    history: list[dict[str, object]],
    observed_hash: str,
    field_changes: dict[str, dict[str, object]],
) -> PaperChangeCandidate:
    previous_hash = ""
    for change in history:
        metadata = change.get("metadata")
        if isinstance(metadata, dict):
            previous_hash = _str_value(metadata.get("observed_content_hash"))
            if previous_hash:
                break

    changed_fields = list(field_changes)
    changed_labels = [FIELD_LABELS.get(field, field) for field in changed_fields]
    return PaperChangeCandidate(
        paper_id=paper.id,
        paper_key=paper.paper_key,
        source_name=paper.source_name,
        change_type="content_updated",
        summary=(
            f"文献内容发生更新（{', '.join(changed_labels)}）："
            f"{paper.canonical_title}"
        ),
        metadata={
            "change_key": f"{paper.paper_key}|content_updated|{observed_hash}",
            "observed_content_hash": observed_hash,
            "previous_content_hash": previous_hash,
            "article_url": paper.article_url,
            "doi": paper.doi,
            "published_at": paper.published_at,
            "last_seen_at": paper.metadata.get("last_seen_at"),
            "seen_count": paper.metadata.get("seen_count"),
            "changed_fields": changed_fields,
            "field_changes": field_changes,
            "field_snapshot": _paper_field_snapshot(paper),
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


def _field_changes_since_last_event(
    paper: StoredPaper,
    history: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    current_snapshot = _paper_field_snapshot(paper)
    previous_snapshot = _latest_field_snapshot(history)
    if previous_snapshot is not None:
        return {
            field: {
                "before": previous_snapshot.get(field),
                "after": current_snapshot.get(field),
            }
            for field in current_snapshot
            if previous_snapshot.get(field) != current_snapshot.get(field)
        }

    raw_changes = paper.metadata.get("field_changes")
    if not isinstance(raw_changes, dict):
        return {}
    return {
        str(field): value
        for field, value in raw_changes.items()
        if isinstance(value, dict) and field in current_snapshot
    }


def _latest_field_snapshot(
    history: list[dict[str, object]],
) -> dict[str, object] | None:
    for change in history:
        metadata = change.get("metadata")
        if not isinstance(metadata, dict):
            continue
        snapshot = metadata.get("field_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    return None


def _paper_field_snapshot(paper: StoredPaper) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "title": paper.canonical_title.strip(),
        "authors": paper.normalized_authors.strip(),
        "abstract": paper.abstract.strip(),
        "published_at": (paper.published_at or "").strip(),
        "doi": (paper.doi or "").strip().casefold(),
        "language": (paper.language or "").strip().casefold(),
    }
    for key in (
        "keywords",
        "pdf_url",
        "online_date",
        "openalex_id",
        "pubmed_id",
        "is_retracted",
        "is_corrected",
    ):
        value = paper.metadata.get(key)
        if isinstance(value, list):
            snapshot[key] = sorted(
                {str(item).strip() for item in value if str(item).strip()},
                key=str.casefold,
            )
        else:
            snapshot[key] = value if value is not None else ""
    return snapshot


def _str_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
