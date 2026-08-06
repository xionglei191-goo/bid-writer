from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .delivery_review import build_delivery_review
from .production_tasks import get_production_task


DELIVERY_UPDATE_FIELDS = (
    "delivery_channel",
    "recipient",
    "status",
    "notes",
    "delivered_at",
)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _decode_record(row: dict[str, Any]) -> dict[str, Any]:
    for field in ("components_json", "task_snapshot_json", "review_snapshot_json"):
        value = row.get(field)
        try:
            row[field.replace("_json", "")] = json.loads(value or "{}")
        except json.JSONDecodeError:
            row[field.replace("_json", "")] = {}
    return row


def record_delivery_export(
    tender_id: int,
    package_result: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    task = get_production_task(tender_id, conn=conn)
    review = build_delivery_review(tender_id, conn=conn)
    package_path = str(package_result.get("path") or "")
    package_format = str(package_result.get("format") or "zip")
    package_size = Path(package_path).stat().st_size if package_path and Path(package_path).exists() else 0
    notes = "系统在导出客户发货包时自动归档。" if package_format == "client_zip" else "系统在导出交付包时自动归档。"
    with conn:
        cur = conn.execute(
            """
            INSERT INTO delivery_records (
                tender_id, package_path, package_format, package_size,
                components_json, task_snapshot_json, review_snapshot_json,
                delivery_channel, recipient, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                package_path,
                package_format,
                package_size,
                _json_dumps(package_result.get("components") or {}),
                _json_dumps(task),
                _json_dumps(review),
                str(task.get("source_platform") or ""),
                str(task.get("customer_name") or ""),
                "已导出",
                notes,
            ),
        )
    record = row_to_dict(conn.execute("SELECT * FROM delivery_records WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return _decode_record(record)


def list_delivery_records(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM delivery_records
            WHERE tender_id = ?
            ORDER BY exported_at DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return [_decode_record(row) for row in rows]


def latest_delivery_record(
    tender_id: int,
    conn: sqlite3.Connection | None = None,
    package_formats: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    own_conn = conn is None
    conn = conn or connect()
    format_clause = ""
    params: list[Any] = [tender_id]
    if package_formats:
        placeholders = ",".join("?" for _ in package_formats)
        format_clause = f"AND COALESCE(package_format, '') IN ({placeholders})"
        params.extend(package_formats)
    row = row_to_dict(
        conn.execute(
            f"""
            SELECT *
            FROM delivery_records
            WHERE tender_id = ?
            {format_clause}
            ORDER BY exported_at DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    )
    if own_conn:
        conn.close()
    return _decode_record(row) if row else None


def update_delivery_record(
    record_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM delivery_records WHERE id = ?", (record_id,)).fetchone())
    if not row:
        raise ValueError(f"Delivery record not found: {record_id}")

    cleaned: dict[str, Any] = {}
    for field in DELIVERY_UPDATE_FIELDS:
        if field not in data:
            continue
        cleaned[field] = str(data[field] or "").strip()
    if cleaned.get("status") in {"已交付", "已结案"} and not cleaned.get("delivered_at") and not row.get("delivered_at"):
        cleaned["delivered_at"] = datetime.now().isoformat(timespec="seconds")
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        values = [*cleaned.values(), record_id]
        with conn:
            conn.execute(
                f"""
                UPDATE delivery_records
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values,
            )
    record = row_to_dict(conn.execute("SELECT * FROM delivery_records WHERE id = ?", (record_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return _decode_record(record)


def mark_latest_delivery(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    latest = latest_delivery_record(tender_id, conn=conn)
    if not latest:
        raise ValueError("当前项目还没有交付包导出记录。")
    record = update_delivery_record(int(latest["id"]), data, conn=conn)
    if own_conn:
        conn.close()
    return record
