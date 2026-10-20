"""Repair the confirmed Editorial Board/OpenAlex mismatch without dropping records.

Run with --apply after reviewing the default read-only audit. A SQLite backup is
created before any changes; repeated runs are safe.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from ..models import RawRecord
from ..paths import DB_PATH
from ..storage import SQLiteRepository


BAD_DOI = "10.1080/03610928308827180"
BAD_OPENALEX_ID = "https://openalex.org/W4250434996"
EXTERNAL_FIELDS = ("keywords", "openalex_id", "pubmed_id", "external_metadata_source")


def repair_editorial_metadata(db_path: Path, *, apply: bool = False) -> dict[str, object]:
    db_path = Path(db_path).resolve()
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as audit:
        audit.row_factory = sqlite3.Row
        rows = audit.execute(
            "SELECT * FROM raw_records WHERE source_name = ? AND lower(title) = ? AND doi = ?",
            ("Metabolic Engineering", "editorial board", BAD_DOI),
        ).fetchall()
        rows = [row for row in rows if json.loads(row["metadata_json"]).get("openalex_id") == BAD_OPENALEX_ID]
    result: dict[str, object] = {"raw_record_ids": [row["id"] for row in rows], "applied": False}
    if not apply or not rows:
        return result

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = db_path.parent / "backups" / f"{db_path.stem}_before_metadata_repair_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        with closing(sqlite3.connect(backup_path)) as backup:
            connection.backup(backup)
        # Claim the write transaction before re-checking the audited rows.
        connection.execute("BEGIN IMMEDIATE")
        timestamp = datetime.now().isoformat(timespec="seconds")
        corrected: list[int] = []
        for original in rows:
            cursor = connection.execute("SELECT * FROM raw_records WHERE id = ?", (original["id"],))
            columns = [column[0] for column in cursor.description]
            row = dict(zip(columns, cursor.fetchone()))
            metadata = json.loads(row["metadata_json"])
            if row["doi"] != BAD_DOI or metadata.get("openalex_id") != BAD_OPENALEX_ID:
                continue
            removed = {key: metadata.pop(key) for key in EXTERNAL_FIELDS if key in metadata}
            removed["doi"] = BAD_DOI
            metadata.pop("field_changes", None)
            metadata["metadata_repair"] = {
                "reason": "ambiguous_title_matched_unrelated_work",
                "rejected_metadata": removed,
                "repaired_at": timestamp,
            }
            record = RawRecord(
                **{key: row[key] for key in RawRecord.__dataclass_fields__ if key in row and key != "doi"},
                doi=None,
                metadata=metadata,
            )
            connection.execute(
                "UPDATE raw_records SET doi = NULL, metadata_json = ?, content_hash = ? WHERE id = ?",
                (json.dumps(metadata, ensure_ascii=False), SQLiteRepository._hash_record(record), row["id"]),
            )
            corrected.append(row["id"])

            papers = connection.execute(
                "SELECT id, metadata_json FROM papers WHERE raw_record_id = ? AND doi = ?",
                (row["id"], BAD_DOI),
            ).fetchall()
            for paper_id, metadata_json in papers:
                paper_metadata = json.loads(metadata_json)
                for key in (*EXTERNAL_FIELDS, "field_changes"):
                    paper_metadata.pop(key, None)
                paper_metadata["metadata_repair"] = metadata["metadata_repair"]
                paper_metadata["observed_raw_record_ids"] = [row["id"]]
                paper_metadata["observed_sources"] = [row["source_name"]]
                paper_metadata["observed_article_urls"] = [row["article_url"]]
                connection.execute(
                    "UPDATE papers SET doi = NULL, paper_key = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
                    (
                        f"url:{row['source_name'].lower()}::{row['article_url'].strip().lower()}",
                        json.dumps(paper_metadata, ensure_ascii=False), timestamp, paper_id,
                    ),
                )
        connection.commit()
    result.update(applied=True, raw_record_ids=corrected, backup_path=str(backup_path))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(repair_editorial_metadata(args.db, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
