from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from ..models import (
    PaperChangeCandidate,
    PaperInsightRecord,
    PaperRecord,
    RawRecord,
    SourceConfig,
    StoredPaper,
    StoredPaperChange,
    StoredRawRecord,
    TrackingItemRecord,
)


class SQLiteRepository:
    CONTENT_HASH_VERSION = 2
    MATERIAL_METADATA_KEYS = (
        "keywords",
        "pdf_url",
        "online_date",
        "openalex_id",
        "pubmed_id",
        "is_retracted",
        "is_corrected",
    )

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS sources (
                    source_name TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    incremental_url TEXT NOT NULL,
                    collector_kind TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    lang TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS crawl_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    FOREIGN KEY (source_name) REFERENCES sources(source_name)
                );

                CREATE TABLE IF NOT EXISTS raw_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    journal_name TEXT NOT NULL,
                    listing_url TEXT NOT NULL,
                    article_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    authors TEXT NOT NULL DEFAULT '',
                    abstract TEXT NOT NULL DEFAULT '',
                    published_at TEXT,
                    doi TEXT,
                    language TEXT,
                    collector_kind TEXT NOT NULL,
                    content_text TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(source_name, article_url)
                );

                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_record_id INTEGER,
                    paper_key TEXT,
                    source_name TEXT NOT NULL,
                    journal_name TEXT NOT NULL DEFAULT '',
                    article_url TEXT NOT NULL DEFAULT '',
                    doi TEXT,
                    canonical_title TEXT,
                    normalized_authors TEXT,
                    published_at TEXT,
                    abstract TEXT NOT NULL DEFAULT '',
                    language TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (raw_record_id) REFERENCES raw_records(id)
                );

                CREATE TABLE IF NOT EXISTS process_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS change_detection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS insight_build_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS report_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS paper_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_key TEXT,
                    paper_id INTEGER,
                    source_name TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (paper_id) REFERENCES papers(id)
                );

                CREATE TABLE IF NOT EXISTS paper_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    insight_key TEXT,
                    change_id INTEGER,
                    paper_id INTEGER,
                    source_name TEXT NOT NULL,
                    summary TEXT,
                    reason TEXT,
                    score REAL,
                    score_label TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (paper_id) REFERENCES papers(id)
                );

                CREATE TABLE IF NOT EXISTS tracking_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracking_key TEXT,
                    paper_id INTEGER,
                    source_name TEXT NOT NULL,
                    tracking_status TEXT NOT NULL DEFAULT 'pending',
                    priority_score REAL,
                    note TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (paper_id) REFERENCES papers(id)
                );
                """
            )
            self._migrate_schema(connection)
            connection.commit()

    def sync_sources(self, sources: list[SourceConfig]) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            connection.executemany(
                """
                INSERT INTO sources (
                    source_name, canonical_url, platform, incremental_url,
                    collector_kind, dedupe_key, lang, status, notes, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    canonical_url = excluded.canonical_url,
                    platform = excluded.platform,
                    incremental_url = excluded.incremental_url,
                    collector_kind = excluded.collector_kind,
                    dedupe_key = excluded.dedupe_key,
                    lang = excluded.lang,
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        source.source_name,
                        source.canonical_url,
                        source.platform,
                        source.incremental_url,
                        source.collector_kind,
                        source.dedupe_key,
                        source.lang,
                        source.status,
                        source.notes,
                        timestamp,
                    )
                    for source in sources
                ],
            )
            connection.commit()

    def start_crawl_run(self, source_name: str) -> int:
        return self._start_run("crawl_runs", source_name)

    def finish_crawl_run(
        self,
        run_id: int,
        *,
        status: str,
        item_count: int,
        error_message: str | None = None,
    ) -> None:
        self._finish_run("crawl_runs", run_id, status, item_count, error_message)

    def start_process_run(self, source_name: str = "__all__") -> int:
        return self._start_run("process_runs", source_name)

    def finish_process_run(
        self,
        run_id: int,
        *,
        status: str,
        item_count: int,
        error_message: str | None = None,
    ) -> None:
        self._finish_run("process_runs", run_id, status, item_count, error_message)

    def start_change_detection_run(self, source_name: str = "__all__") -> int:
        return self._start_run("change_detection_runs", source_name)

    def finish_change_detection_run(
        self,
        run_id: int,
        *,
        status: str,
        item_count: int,
        error_message: str | None = None,
    ) -> None:
        self._finish_run(
            "change_detection_runs",
            run_id,
            status,
            item_count,
            error_message,
        )

    def start_insight_build_run(self, source_name: str = "__all__") -> int:
        return self._start_run("insight_build_runs", source_name)

    def finish_insight_build_run(
        self,
        run_id: int,
        *,
        status: str,
        item_count: int,
        error_message: str | None = None,
    ) -> None:
        self._finish_run(
            "insight_build_runs",
            run_id,
            status,
            item_count,
            error_message,
        )

    def start_report_run(self, source_name: str = "__all__") -> int:
        return self._start_run("report_runs", source_name)

    def finish_report_run(
        self,
        run_id: int,
        *,
        status: str,
        item_count: int,
        error_message: str | None = None,
    ) -> None:
        self._finish_run("report_runs", run_id, status, item_count, error_message)

    def upsert_raw_records(self, records: list[RawRecord]) -> int:
        if not records:
            return 0

        timestamp = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            for record in records:
                existing = connection.execute(
                    """
                    SELECT
                        journal_name, listing_url, title, authors, abstract,
                        published_at, doi, language, collector_kind, content_text,
                        metadata_json
                    FROM raw_records
                    WHERE source_name = ? AND article_url = ?
                    """,
                    (record.source_name, record.article_url),
                ).fetchone()
                merged_record = self._merge_raw_record(record, existing, timestamp)
                connection.execute(
                    """
                    INSERT INTO raw_records (
                        source_name, journal_name, listing_url, article_url, title,
                        authors, abstract, published_at, doi, language, collector_kind,
                        content_text, content_hash, metadata_json, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_name, article_url) DO UPDATE SET
                        journal_name = excluded.journal_name,
                        listing_url = excluded.listing_url,
                        title = excluded.title,
                        authors = excluded.authors,
                        abstract = excluded.abstract,
                        published_at = excluded.published_at,
                        doi = excluded.doi,
                        language = excluded.language,
                        collector_kind = excluded.collector_kind,
                        content_text = excluded.content_text,
                        content_hash = excluded.content_hash,
                        metadata_json = excluded.metadata_json,
                        last_seen_at = excluded.last_seen_at,
                        seen_count = raw_records.seen_count + 1
                    """,
                    (
                        merged_record.source_name,
                        merged_record.journal_name,
                        merged_record.listing_url,
                        merged_record.article_url,
                        merged_record.title,
                        merged_record.authors,
                        merged_record.abstract,
                        merged_record.published_at,
                        merged_record.doi,
                        merged_record.language,
                        merged_record.collector_kind,
                        merged_record.content_text,
                        self._hash_record(merged_record),
                        json.dumps(merged_record.metadata, ensure_ascii=False),
                        timestamp,
                        timestamp,
                    ),
                )
            connection.commit()
        return len(records)

    def fetch_raw_records(
        self,
        *,
        source_name: str | None = None,
        limit: int | None = None,
    ) -> list[StoredRawRecord]:
        query = """
            SELECT
                id,
                source_name,
                journal_name,
                listing_url,
                article_url,
                title,
                authors,
                abstract,
                published_at,
                doi,
                language,
                collector_kind,
                content_text,
                content_hash,
                metadata_json,
                first_seen_at,
                last_seen_at,
                seen_count
            FROM raw_records
        """
        parameters: list[object] = []
        if source_name:
            query += " WHERE source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY COALESCE(published_at, last_seen_at) DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            StoredRawRecord(
                id=row[0],
                source_name=row[1],
                journal_name=row[2],
                listing_url=row[3],
                article_url=row[4],
                title=row[5],
                authors=row[6],
                abstract=row[7],
                published_at=row[8],
                doi=row[9],
                language=row[10],
                collector_kind=row[11],
                content_text=row[12],
                content_hash=row[13],
                metadata=self._loads_json(row[14]),
                first_seen_at=row[15],
                last_seen_at=row[16],
                seen_count=row[17],
            )
            for row in rows
        ]

    def upsert_papers(self, papers: list[PaperRecord]) -> int:
        if not papers:
            return 0

        timestamp = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            for paper in papers:
                existing = connection.execute(
                    """
                    SELECT id, metadata_json
                    FROM papers
                    WHERE paper_key = ? OR raw_record_id = ?
                    ORDER BY
                        CASE WHEN paper_key = ? THEN 0 ELSE 1 END,
                        id ASC
                    LIMIT 1
                    """,
                    (paper.paper_key, paper.raw_record_id, paper.paper_key),
                ).fetchone()
                metadata = self._merge_paper_metadata(
                    self._loads_json(existing[1]) if existing else {},
                    paper,
                )
                values = (
                    paper.raw_record_id,
                    paper.paper_key,
                    paper.source_name,
                    paper.journal_name,
                    paper.article_url,
                    paper.doi,
                    paper.canonical_title,
                    paper.normalized_authors,
                    paper.published_at,
                    paper.abstract,
                    paper.language,
                    paper.status,
                    json.dumps(metadata, ensure_ascii=False),
                    timestamp,
                )

                if existing:
                    connection.execute(
                        """
                        UPDATE papers
                        SET raw_record_id = ?,
                            paper_key = ?,
                            source_name = ?,
                            journal_name = ?,
                            article_url = ?,
                            doi = ?,
                            canonical_title = ?,
                            normalized_authors = ?,
                            published_at = ?,
                            abstract = ?,
                            language = ?,
                            status = ?,
                            metadata_json = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (*values, existing[0]),
                    )
                    continue

                connection.execute(
                    """
                    INSERT INTO papers (
                        raw_record_id,
                        paper_key,
                        source_name,
                        journal_name,
                        article_url,
                        doi,
                        canonical_title,
                        normalized_authors,
                        published_at,
                        abstract,
                        language,
                        status,
                        metadata_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*values, timestamp),
                )
            connection.commit()
        return len(papers)

    def fetch_papers(
        self,
        *,
        source_name: str | None = None,
        limit: int | None = None,
    ) -> list[StoredPaper]:
        query = """
            SELECT
                id,
                raw_record_id,
                paper_key,
                source_name,
                journal_name,
                article_url,
                doi,
                canonical_title,
                normalized_authors,
                published_at,
                abstract,
                language,
                status,
                metadata_json,
                created_at,
                updated_at
            FROM papers
        """
        parameters: list[object] = []
        if source_name:
            query += " WHERE source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY COALESCE(published_at, updated_at) DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            StoredPaper(
                id=row[0],
                raw_record_id=row[1],
                paper_key=row[2] or "",
                source_name=row[3],
                journal_name=row[4],
                article_url=row[5],
                doi=row[6],
                canonical_title=row[7] or "",
                normalized_authors=row[8] or "",
                published_at=row[9],
                abstract=row[10] or "",
                language=row[11],
                status=row[12] or "normalized",
                metadata=self._loads_json(row[13]),
                created_at=row[14] or "",
                updated_at=row[15] or "",
            )
            for row in rows
        ]

    def fetch_paper_change_state(self) -> dict[int, list[dict[str, object]]]:
        state: dict[int, list[dict[str, object]]] = {}
        for change in self.fetch_paper_changes():
            state.setdefault(change.paper_id, []).append(
                {
                    "change_key": change.change_key,
                    "change_type": change.change_type,
                    "summary": change.summary,
                    "detected_at": change.detected_at,
                    "metadata": change.metadata,
                }
            )
        return state

    def upsert_paper_changes(self, changes: list[PaperChangeCandidate]) -> int:
        if not changes:
            return 0

        inserted_count = 0
        detected_at = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            for change in changes:
                metadata_json = json.dumps(change.metadata, ensure_ascii=False)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO paper_changes (
                        change_key,
                        paper_id,
                        source_name,
                        change_type,
                        summary,
                        detected_at,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._build_change_key(change),
                        change.paper_id,
                        change.source_name,
                        change.change_type,
                        change.summary,
                        detected_at,
                        metadata_json,
                    ),
                )
                inserted_count += int(cursor.rowcount > 0)
            connection.commit()
        return inserted_count

    def fetch_paper_changes(
        self,
        *,
        source_name: str | None = None,
        limit: int | None = None,
    ) -> list[StoredPaperChange]:
        query = """
            SELECT
                id,
                change_key,
                paper_id,
                source_name,
                change_type,
                summary,
                detected_at,
                metadata_json
            FROM paper_changes
        """
        parameters: list[object] = []
        if source_name:
            query += " WHERE source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY detected_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            StoredPaperChange(
                id=row[0],
                change_key=row[1] or "",
                paper_id=row[2],
                source_name=row[3],
                change_type=row[4],
                summary=row[5],
                detected_at=row[6],
                metadata=self._loads_json(row[7]),
            )
            for row in rows
        ]

    def upsert_paper_insights(self, insights: list[PaperInsightRecord]) -> int:
        if not insights:
            return 0

        timestamp = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            connection.executemany(
                """
                INSERT INTO paper_insights (
                    insight_key,
                    change_id,
                    paper_id,
                    source_name,
                    summary,
                    reason,
                    score,
                    score_label,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(change_id) DO UPDATE SET
                    insight_key = excluded.insight_key,
                    paper_id = excluded.paper_id,
                    source_name = excluded.source_name,
                    summary = excluded.summary,
                    reason = excluded.reason,
                    score = excluded.score,
                    score_label = excluded.score_label,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        insight.insight_key,
                        insight.change_id,
                        insight.paper_id,
                        insight.source_name,
                        insight.summary,
                        insight.reason,
                        insight.score,
                        insight.score_label,
                        json.dumps(insight.metadata, ensure_ascii=False),
                        timestamp,
                        timestamp,
                    )
                    for insight in insights
                ],
            )
            connection.commit()
        return len(insights)

    def fetch_paper_insights(
        self,
        *,
        source_name: str | None = None,
    ) -> list[dict[str, object]]:
        query = """
            SELECT
                insight_key,
                change_id,
                paper_id,
                source_name,
                summary,
                reason,
                score,
                score_label,
                metadata_json
            FROM paper_insights
        """
        parameters: list[object] = []
        if source_name:
            query += " WHERE source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY score DESC, id ASC"

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            {
                "insight_key": row[0],
                "change_id": row[1],
                "paper_id": row[2],
                "source_name": row[3],
                "summary": row[4],
                "reason": row[5],
                "score": row[6],
                "score_label": row[7],
                "metadata": self._loads_json(row[8]),
            }
            for row in rows
        ]

    def upsert_tracking_items(self, items: list[TrackingItemRecord]) -> int:
        if not items:
            return 0

        timestamp = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            connection.executemany(
                """
                INSERT INTO tracking_items (
                    tracking_key,
                    paper_id,
                    source_name,
                    tracking_status,
                    priority_score,
                    note,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    tracking_key = excluded.tracking_key,
                    source_name = excluded.source_name,
                    tracking_status = excluded.tracking_status,
                    priority_score = excluded.priority_score,
                    note = excluded.note,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        item.tracking_key,
                        item.paper_id,
                        item.source_name,
                        item.tracking_status,
                        item.priority_score,
                        item.note,
                        json.dumps(item.metadata, ensure_ascii=False),
                        timestamp,
                        timestamp,
                    )
                    for item in items
                ],
            )
            connection.commit()
        return len(items)

    def fetch_tracking_items(
        self,
        *,
        source_name: str | None = None,
    ) -> list[dict[str, object]]:
        query = """
            SELECT
                tracking_key,
                paper_id,
                source_name,
                tracking_status,
                priority_score,
                note,
                metadata_json
            FROM tracking_items
        """
        parameters: list[object] = []
        if source_name:
            query += " WHERE source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY priority_score DESC, id ASC"

        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            {
                "tracking_key": row[0],
                "paper_id": row[1],
                "source_name": row[2],
                "tracking_status": row[3],
                "priority_score": row[4],
                "note": row[5],
                "metadata": self._loads_json(row[6]),
            }
            for row in rows
        ]

    def fetch_source_health(
        self,
        *,
        source_name: str | None = None,
    ) -> list[dict[str, object]]:
        query = """
            SELECT source_name, platform, status, notes, updated_at
            FROM sources
        """
        parameters: list[object] = []
        if source_name:
            query += " WHERE source_name = ?"
            parameters.append(source_name)
        query += " ORDER BY source_name"

        health_rows: list[dict[str, object]] = []
        with closing(self._connect()) as connection:
            for source in connection.execute(query, parameters).fetchall():
                latest_run = connection.execute(
                    """
                    SELECT status, item_count, started_at, completed_at, error_message
                    FROM crawl_runs
                    WHERE source_name = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (source[0],),
                ).fetchone()
                health_rows.append(
                    {
                        "source_name": source[0],
                        "platform": source[1],
                        "source_status": source[2],
                        "notes": source[3],
                        "configured_at": source[4],
                        "last_run_status": latest_run[0] if latest_run else "never",
                        "item_count": latest_run[1] if latest_run else 0,
                        "started_at": latest_run[2] if latest_run else None,
                        "completed_at": latest_run[3] if latest_run else None,
                        "error_message": latest_run[4] if latest_run else None,
                    }
                )
        return health_rows

    def fetch_pipeline_health(self) -> list[dict[str, object]]:
        stages = (
            ("process", "process_runs"),
            ("detect_changes", "change_detection_runs"),
            ("build_insights", "insight_build_runs"),
            ("build_report", "report_runs"),
        )
        rows: list[dict[str, object]] = []
        with closing(self._connect()) as connection:
            for stage_name, table_name in stages:
                latest_run = connection.execute(
                    f"""
                    SELECT source_name, status, item_count, started_at,
                           completed_at, error_message
                    FROM {table_name}
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
                rows.append(
                    {
                        "stage": stage_name,
                        "source_name": latest_run[0] if latest_run else "__all__",
                        "status": latest_run[1] if latest_run else "never",
                        "item_count": latest_run[2] if latest_run else 0,
                        "started_at": latest_run[3] if latest_run else None,
                        "completed_at": latest_run[4] if latest_run else None,
                        "error_message": latest_run[5] if latest_run else None,
                    }
                )
        return rows

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        self._ensure_column(connection, "papers", "paper_key", "TEXT")
        self._ensure_column(connection, "papers", "journal_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(connection, "papers", "article_url", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(connection, "papers", "abstract", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(connection, "papers", "language", "TEXT")
        self._ensure_column(connection, "paper_changes", "change_key", "TEXT")
        self._ensure_column(connection, "paper_insights", "insight_key", "TEXT")
        self._ensure_column(connection, "paper_insights", "change_id", "INTEGER")
        self._ensure_column(connection, "paper_insights", "updated_at", "TEXT")
        self._ensure_column(connection, "tracking_items", "tracking_key", "TEXT")
        self._dedupe_existing_papers_by_key(connection)
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_raw_record_id_unique
            ON papers(raw_record_id)
            """
        )
        connection.execute(
            "DROP INDEX IF EXISTS idx_papers_paper_key"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_paper_key_unique ON papers(paper_key)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)"
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_changes_change_key_unique
            ON paper_changes(change_key)
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_changes_paper_id ON paper_changes(paper_id)"
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_insights_change_id_unique
            ON paper_insights(change_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_insights_insight_key_unique
            ON paper_insights(insight_key)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_items_paper_id_unique
            ON tracking_items(paper_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_items_tracking_key_unique
            ON tracking_items(tracking_key)
            """
        )
        self._migrate_tracking_status_labels(connection)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        existing_columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )

    @staticmethod
    def _migrate_tracking_status_labels(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE tracking_items
            SET tracking_status = 'review'
            WHERE tracking_status = 'priority'
            """
        )

    @classmethod
    def _dedupe_existing_papers_by_key(cls, connection: sqlite3.Connection) -> None:
        duplicate_keys = [
            row[0]
            for row in connection.execute(
                """
                SELECT paper_key
                FROM papers
                WHERE paper_key IS NOT NULL AND TRIM(paper_key) != ''
                GROUP BY paper_key
                HAVING COUNT(*) > 1
                """
            ).fetchall()
        ]
        for paper_key in duplicate_keys:
            rows = connection.execute(
                """
                SELECT id, metadata_json, raw_record_id, source_name, article_url
                FROM papers
                WHERE paper_key = ?
                ORDER BY id ASC
                """,
                (paper_key,),
            ).fetchall()
            keep_id = rows[0][0]
            duplicate_ids = [row[0] for row in rows[1:]]
            if not duplicate_ids:
                continue

            merged_metadata: dict[str, object] = {}
            for row in rows:
                merged_metadata.update(cls._loads_json(row[1]))
                merged_metadata = cls._merge_metadata_observation(
                    merged_metadata,
                    raw_record_id=row[2],
                    source_name=row[3],
                    article_url=row[4],
                )
            connection.execute(
                "UPDATE papers SET metadata_json = ? WHERE id = ?",
                (json.dumps(merged_metadata, ensure_ascii=False), keep_id),
            )

            placeholders = ", ".join("?" for _ in duplicate_ids)
            connection.execute(
                f"DELETE FROM tracking_items WHERE paper_id IN ({placeholders})",
                duplicate_ids,
            )
            connection.execute(
                f"DELETE FROM paper_insights WHERE paper_id IN ({placeholders})",
                duplicate_ids,
            )
            connection.execute(
                f"UPDATE paper_changes SET paper_id = ? WHERE paper_id IN ({placeholders})",
                [keep_id, *duplicate_ids],
            )
            connection.execute(
                f"DELETE FROM papers WHERE id IN ({placeholders})",
                duplicate_ids,
            )

    @classmethod
    def _merge_paper_metadata(
        cls,
        existing_metadata: dict[str, object],
        paper: PaperRecord,
    ) -> dict[str, object]:
        merged = dict(existing_metadata)
        merged.update(paper.metadata)
        return cls._merge_metadata_observation(
            merged,
            raw_record_id=paper.raw_record_id,
            source_name=paper.source_name,
            article_url=paper.article_url,
        )

    @staticmethod
    def _merge_metadata_observation(
        metadata: dict[str, object],
        *,
        raw_record_id: int | None,
        source_name: str,
        article_url: str,
    ) -> dict[str, object]:
        merged = dict(metadata)
        raw_ids = set()
        for value in merged.get("observed_raw_record_ids", []):
            try:
                raw_ids.add(int(value))
            except (TypeError, ValueError):
                continue
        if raw_record_id is not None:
            raw_ids.add(int(raw_record_id))
        merged["observed_raw_record_ids"] = sorted(raw_ids)

        sources = {
            str(value)
            for value in merged.get("observed_sources", [])
            if str(value).strip()
        }
        if source_name.strip():
            sources.add(source_name.strip())
        merged["observed_sources"] = sorted(sources)

        urls = {
            str(value)
            for value in merged.get("observed_article_urls", [])
            if str(value).strip()
        }
        if article_url.strip():
            urls.add(article_url.strip())
        merged["observed_article_urls"] = sorted(urls)
        return merged

    @staticmethod
    def _loads_json(value: str | None) -> dict[str, object]:
        try:
            return json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _build_change_key(change: PaperChangeCandidate) -> str:
        raw_key = change.metadata.get("change_key")
        if isinstance(raw_key, str) and raw_key.strip():
            return raw_key
        payload = "||".join(
            [
                change.paper_key,
                change.change_type,
                change.source_name,
                json.dumps(change.metadata, ensure_ascii=False, sort_keys=True),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _merge_raw_record(
        self,
        record: RawRecord,
        existing: tuple[object, ...] | None,
        timestamp: str,
    ) -> RawRecord:
        if existing is None:
            metadata = dict(record.metadata)
            metadata["content_hash_version"] = self.CONTENT_HASH_VERSION
            return RawRecord(
                source_name=record.source_name,
                journal_name=record.journal_name,
                listing_url=record.listing_url,
                article_url=record.article_url,
                title=record.title,
                authors=record.authors,
                abstract=record.abstract,
                published_at=record.published_at,
                doi=record.doi,
                language=record.language,
                collector_kind=record.collector_kind,
                content_text=record.content_text,
                metadata=metadata,
            )

        existing_metadata = self._loads_json(str(existing[10] or "{}"))
        previous_record = RawRecord(
            source_name=record.source_name,
            journal_name=str(existing[0] or ""),
            listing_url=str(existing[1] or ""),
            article_url=record.article_url,
            title=str(existing[2] or ""),
            authors=str(existing[3] or ""),
            abstract=str(existing[4] or ""),
            published_at=str(existing[5]) if existing[5] else None,
            doi=str(existing[6]) if existing[6] else None,
            language=str(existing[7]) if existing[7] else None,
            collector_kind=str(existing[8] or ""),
            content_text=str(existing[9] or ""),
            metadata=existing_metadata,
        )
        metadata = self._merge_metadata(existing_metadata, record.metadata)
        metadata["content_hash_version"] = self.CONTENT_HASH_VERSION
        merged_record = RawRecord(
            source_name=record.source_name,
            journal_name=self._prefer_value(record.journal_name, previous_record.journal_name),
            listing_url=self._prefer_value(record.listing_url, previous_record.listing_url),
            article_url=record.article_url,
            title=self._prefer_value(record.title, previous_record.title),
            authors=self._prefer_value(record.authors, previous_record.authors),
            abstract=self._prefer_value(record.abstract, previous_record.abstract),
            published_at=self._prefer_optional(record.published_at, previous_record.published_at),
            doi=self._prefer_optional(record.doi, previous_record.doi),
            language=self._prefer_optional(record.language, previous_record.language),
            collector_kind=self._prefer_value(
                record.collector_kind,
                previous_record.collector_kind,
            ),
            content_text=self._prefer_value(record.content_text, previous_record.content_text),
            metadata=metadata,
        )

        previous_snapshot = self._material_snapshot(previous_record)
        current_snapshot = self._material_snapshot(merged_record)
        field_changes = {
            field_name: {
                "before": previous_snapshot.get(field_name),
                "after": current_snapshot.get(field_name),
            }
            for field_name in current_snapshot
            if previous_snapshot.get(field_name) != current_snapshot.get(field_name)
        }
        if field_changes:
            merged_record.metadata["field_changes"] = field_changes
            merged_record.metadata["fields_changed_at"] = timestamp
        return merged_record

    @classmethod
    def _merge_metadata(
        cls,
        existing: dict[str, object],
        incoming: dict[str, object],
    ) -> dict[str, object]:
        merged = dict(existing)
        for key, value in incoming.items():
            if cls._has_value(value):
                merged[key] = value
        if incoming.get("enrichment_status") == "success":
            merged.pop("enrichment_error", None)
        return merged

    @staticmethod
    def _has_value(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    @staticmethod
    def _prefer_value(incoming: str, existing: str) -> str:
        return incoming if incoming.strip() else existing

    @staticmethod
    def _prefer_optional(incoming: str | None, existing: str | None) -> str | None:
        if incoming is not None and incoming.strip():
            return incoming
        return existing

    @classmethod
    def _material_snapshot(cls, record: RawRecord) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "title": record.title.strip(),
            "authors": record.authors.strip(),
            "abstract": record.abstract.strip(),
            "published_at": (record.published_at or "").strip(),
            "doi": (record.doi or "").strip().casefold(),
            "language": (record.language or "").strip().casefold(),
        }
        for key in cls.MATERIAL_METADATA_KEYS:
            value = record.metadata.get(key)
            if isinstance(value, list):
                snapshot[key] = sorted(
                    {str(item).strip() for item in value if str(item).strip()},
                    key=str.casefold,
                )
            else:
                snapshot[key] = value if value is not None else ""
        return snapshot

    @classmethod
    def _hash_record(cls, record: RawRecord) -> str:
        payload = json.dumps(
            cls._material_snapshot(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _start_run(self, table_name: str, source_name: str) -> int:
        started_at = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO {table_name} (source_name, started_at, status)
                VALUES (?, ?, 'running')
                """,
                (source_name, started_at),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def _finish_run(
        self,
        table_name: str,
        run_id: int,
        status: str,
        item_count: int,
        error_message: str | None = None,
    ) -> None:
        completed_at = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            connection.execute(
                f"""
                UPDATE {table_name}
                SET completed_at = ?, status = ?, item_count = ?, error_message = ?
                WHERE id = ?
                """,
                (completed_at, status, item_count, error_message, run_id),
            )
            connection.commit()
