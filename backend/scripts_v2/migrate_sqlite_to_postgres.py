from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKIP_TABLES = {
    "schema_migrations",
    "published_units_fts",
    "published_units_fts_data",
    "published_units_fts_idx",
    "published_units_fts_docsize",
    "published_units_fts_config",
}
MERGE_SEED_TABLES = {"organizations", "roles"}
REPLACE_SEED_TABLES = {"ai_prompt_versions"}
SELF_REFERENCE_COLUMNS = {
    "ai_runs": {"cached_from_run_id"},
    "document_chunks": {"parent_chunk_id"},
    "document_sections": {"parent_id"},
    "source_files": {"duplicate_of", "parent_source_id"},
}


def row_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )
        if row[0] not in SKIP_TABLES and not str(row[0]).startswith("published_units_fts_")
    ]


def migrate(sqlite_path: Path, database_url: str, report_path: Path) -> dict[str, Any]:
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite file does not exist: {sqlite_path}")

    import psycopg
    from psycopg import sql

    psycopg_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": str(sqlite_path),
        "tables": [],
        "status": "running",
    }
    try:
        with psycopg.connect(psycopg_url) as target:
            with target.transaction():
                for table in source_tables(source):
                    source_columns = [str(row[1]) for row in source.execute(f'PRAGMA table_info("{table}")')]
                    with target.cursor() as cursor:
                        cursor.execute(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                            (table,),
                        )
                        target_columns = [str(row[0]) for row in cursor.fetchall()]
                    columns = [column for column in source_columns if column in target_columns]
                    if not columns:
                        continue

                    selected = ",".join(f'"{column}"' for column in columns)
                    source_rows = [
                        dict(row)
                        for row in source.execute(f'SELECT {selected} FROM "{table}" ORDER BY rowid')
                    ]
                    if not source_rows:
                        report["tables"].append({"table": table, "rows": 0, "status": "skipped_empty"})
                        continue

                    with target.cursor() as cursor:
                        cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
                        existing_count = int(cursor.fetchone()[0])
                        if existing_count and table in REPLACE_SEED_TABLES:
                            cursor.execute("SELECT COUNT(*) FROM ai_runs")
                            if int(cursor.fetchone()[0]):
                                raise RuntimeError(
                                    "Target prompt versions are already referenced by AI runs; migration stopped"
                                )
                            cursor.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
                            existing_count = 0
                        if existing_count and table not in MERGE_SEED_TABLES:
                            raise RuntimeError(
                                f"Target table {table} already has {existing_count} rows; "
                                "migration stopped without commit"
                            )

                        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                            sql.Identifier(table),
                            sql.SQL(",").join(sql.Identifier(column) for column in columns),
                            sql.SQL(",").join(sql.Placeholder() for _ in columns),
                        )
                        deferred_columns = SELF_REFERENCE_COLUMNS.get(table, set()).intersection(columns)
                        cursor.executemany(
                            statement,
                            [
                                [None if column in deferred_columns else row[column] for column in columns]
                                for row in source_rows
                            ],
                        )
                        for column in deferred_columns:
                            update_statement = sql.SQL("UPDATE {} SET {}=%s WHERE id=%s").format(
                                sql.Identifier(table), sql.Identifier(column)
                            )
                            cursor.executemany(
                                update_statement,
                                [
                                    (row[column], row["id"])
                                    for row in source_rows
                                    if row[column] is not None
                                ],
                            )
                        cursor.execute(
                            sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                                sql.SQL(",").join(sql.Identifier(column) for column in columns),
                                sql.Identifier(table),
                                sql.Identifier("id") if "id" in columns else sql.Identifier(columns[0]),
                            )
                        )
                        target_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                        if "id" in columns:
                            cursor.execute("SELECT pg_get_serial_sequence(%s,%s)", (table, "id"))
                            sequence = cursor.fetchone()[0]
                            if sequence:
                                cursor.execute(
                                    sql.SQL("SELECT setval(%s,COALESCE((SELECT MAX(id) FROM {}),1),true)").format(
                                        sql.Identifier(table)
                                    ),
                                    (sequence,),
                                )

                    source_hash = row_digest(source_rows)
                    verification_columns = [
                        column
                        for column in columns
                        if not (table in MERGE_SEED_TABLES and column == "created_at")
                    ]
                    source_verification_rows = [
                        {column: row[column] for column in verification_columns} for row in source_rows
                    ]
                    target_verification_rows = [
                        {column: row[column] for column in verification_columns} for row in target_rows
                    ]
                    if (
                        len(source_rows) != len(target_rows)
                        or row_digest(source_verification_rows) != row_digest(target_verification_rows)
                    ):
                        raise RuntimeError(f"Table {table} verification failed; transaction rolled back")
                    report["tables"].append(
                        {
                            "table": table,
                            "rows": len(source_rows),
                            "min_id": min((int(row["id"]) for row in source_rows), default=None)
                            if "id" in columns
                            else None,
                            "max_id": max((int(row["id"]) for row in source_rows), default=None)
                            if "id" in columns
                            else None,
                            "sha256": source_hash,
                            "status": "migrated",
                        }
                    )
        report["status"] = "completed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        source.close()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate the legacy SQLite database to PostgreSQL once")
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--database-url", default=os.environ.get("BID_WRITER_DATABASE_URL", ""))
    parser.add_argument("--report", type=Path, default=Path("data/migration-report.json"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("Provide PostgreSQL through --database-url or BID_WRITER_DATABASE_URL")
    result = migrate(args.sqlite.resolve(), args.database_url, args.report.resolve())
    print(
        json.dumps(
            {"status": result["status"], "tables": len(result["tables"]), "report": str(args.report.resolve())},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
