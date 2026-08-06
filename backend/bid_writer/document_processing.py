from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts


PROCESSING_FIELDS = {
    "tender_id",
    "source_path",
    "original_filename",
    "file_type",
    "action",
    "status",
    "text_chars",
    "page_count",
    "ocr_job_id",
    "ocr_output_dir",
    "markdown_path",
    "error_message",
}


def record_document_processing(
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    payload = {key: data.get(key) for key in PROCESSING_FIELDS if key in data}
    source_path = str(payload.get("source_path") or "")
    payload.setdefault("original_filename", Path(source_path).name if source_path else "")
    payload.setdefault("file_type", Path(source_path).suffix.lower().lstrip(".") if source_path else "")
    payload.setdefault("action", "extract_text")
    payload.setdefault("status", "success")
    payload.setdefault("text_chars", 0)
    payload.setdefault("page_count", 0)
    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    with conn:
        cur = conn.execute(
            f"INSERT INTO document_processing_records ({columns}) VALUES ({placeholders})",
            tuple(payload.values()),
        )
    row = row_to_dict(conn.execute("SELECT * FROM document_processing_records WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def list_document_processing_records(
    tender_id: int | None = None,
    *,
    limit: int = 80,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    if tender_id:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT dpr.*, t.name AS tender_name
                FROM document_processing_records dpr
                LEFT JOIN tenders t ON t.id = dpr.tender_id
                WHERE dpr.tender_id = ?
                ORDER BY dpr.id DESC
                LIMIT ?
                """,
                (tender_id, limit),
            ).fetchall()
        )
    else:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT dpr.*, t.name AS tender_name
                FROM document_processing_records dpr
                LEFT JOIN tenders t ON t.id = dpr.tender_id
                ORDER BY dpr.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
    if own_conn:
        conn.close()
    return rows
