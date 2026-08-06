from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .production_tasks import get_production_task


FEEDBACK_FIELDS = (
    "delivery_record_id",
    "customer_name",
    "source_channel",
    "feedback_text",
    "related_section",
    "priority",
    "status",
    "action_plan",
    "owner",
)


def _clean_payload(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field in FEEDBACK_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "delivery_record_id":
            cleaned[field] = int(value) if value not in ("", None) else None
        else:
            cleaned[field] = str(value or "").strip()
    return cleaned


def create_feedback_item(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    task = get_production_task(tender_id, conn=conn)
    latest = row_to_dict(
        conn.execute(
            """
            SELECT id
            FROM delivery_records
            WHERE tender_id = ?
            ORDER BY exported_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    )
    cleaned = {
        "delivery_record_id": latest.get("id") if latest else None,
        "customer_name": task.get("customer_name") or "",
        "source_channel": task.get("source_platform") or "",
        "feedback_text": "",
        "related_section": "",
        "priority": "normal",
        "status": "待处理",
        "action_plan": "",
        "owner": task.get("internal_owner") or "",
    }
    cleaned.update(_clean_payload(data))
    if not cleaned["feedback_text"]:
        raise ValueError("反馈内容不能为空。")
    columns = ", ".join(["tender_id", *FEEDBACK_FIELDS])
    placeholders = ", ".join("?" for _ in ["tender_id", *FEEDBACK_FIELDS])
    values = [tender_id, *[cleaned.get(field) for field in FEEDBACK_FIELDS]]
    with conn:
        cur = conn.execute(
            f"INSERT INTO feedback_items ({columns}) VALUES ({placeholders})",
            values,
        )
    item = get_feedback_item(int(cur.lastrowid), conn=conn)
    if own_conn:
        conn.close()
    return item


def get_feedback_item(item_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    item = row_to_dict(conn.execute("SELECT * FROM feedback_items WHERE id = ?", (item_id,)).fetchone())
    if not item:
        raise ValueError(f"Feedback item not found: {item_id}")
    if own_conn:
        conn.close()
    return item


def list_feedback_items(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM feedback_items
            WHERE tender_id = ?
            ORDER BY
                CASE status WHEN '待处理' THEN 0 WHEN '处理中' THEN 1 WHEN '已解决' THEN 2 ELSE 3 END,
                created_at DESC,
                id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def update_feedback_item(
    item_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = get_feedback_item(item_id, conn=conn)
    cleaned = _clean_payload(data)
    if cleaned.get("status") == "已解决" and not current.get("resolved_at"):
        cleaned["resolved_at"] = datetime.now().isoformat(timespec="seconds")
    elif cleaned.get("status") and cleaned.get("status") != "已解决":
        cleaned["resolved_at"] = ""
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        values = [*cleaned.values(), item_id]
        with conn:
            conn.execute(
                f"""
                UPDATE feedback_items
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values,
            )
    item = get_feedback_item(item_id, conn=conn)
    if own_conn:
        conn.close()
    return item


def feedback_summary(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    counts = rows_to_dicts(
        conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM feedback_items
            WHERE tender_id = ?
            GROUP BY status
            """,
            (tender_id,),
        ).fetchall()
    )
    total = sum(int(item["count"]) for item in counts)
    open_count = sum(int(item["count"]) for item in counts if item.get("status") != "已解决")
    latest_open = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM feedback_items
            WHERE tender_id = ? AND status <> '已解决'
            ORDER BY created_at DESC, id DESC
            LIMIT 5
            """,
            (tender_id,),
        ).fetchall()
    )
    result = {
        "total": total,
        "open": open_count,
        "resolved": total - open_count,
        "by_status": counts,
        "latest_open": latest_open,
    }
    if own_conn:
        conn.close()
    return result
