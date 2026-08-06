from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect, row_to_dict


TASK_FIELDS = (
    "customer_name",
    "source_platform",
    "order_no",
    "contact",
    "deadline",
    "budget",
    "deliverable_format",
    "delivery_status",
    "delivery_notes",
    "internal_owner",
)

TASK_REQUIRED_FIELDS = (
    "customer_name",
    "deadline",
    "deliverable_format",
)

TASK_FIELD_LABELS = {
    "customer_name": "客户名称",
    "source_platform": "来源平台",
    "order_no": "订单号",
    "contact": "联系方式",
    "deadline": "交付期限",
    "budget": "预算金额",
    "deliverable_format": "交付格式",
    "delivery_status": "生产状态",
    "delivery_notes": "交付备注",
    "internal_owner": "内部负责人",
}


def _default_task() -> dict[str, Any]:
    return {
        "customer_name": "",
        "source_platform": "",
        "order_no": "",
        "contact": "",
        "deadline": "",
        "budget": "",
        "deliverable_format": "DOCX + ZIP 交付包",
        "delivery_status": "待生产",
        "delivery_notes": "",
        "internal_owner": "",
    }


def ensure_production_task(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM production_tasks WHERE tender_id = ?", (tender_id,)).fetchone())
    if row:
        if own_conn:
            conn.close()
        return row

    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    task = _default_task()
    columns = ", ".join(["tender_id", *TASK_FIELDS])
    placeholders = ", ".join("?" for _ in ["tender_id", *TASK_FIELDS])
    values = [tender_id, *[task[field] for field in TASK_FIELDS]]
    with conn:
        cur = conn.execute(
            f"INSERT INTO production_tasks ({columns}) VALUES ({placeholders})",
            values,
        )
    row = row_to_dict(conn.execute("SELECT * FROM production_tasks WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def get_production_task(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    return ensure_production_task(tender_id, conn=conn)


def update_production_task(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    ensure_production_task(tender_id, conn=conn)
    cleaned: dict[str, Any] = {}
    for field in TASK_FIELDS:
        if field not in data:
            continue
        cleaned[field] = str(data[field] or "").strip()
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        values = [*cleaned.values(), tender_id]
        with conn:
            conn.execute(
                f"""
                UPDATE production_tasks
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE tender_id = ?
                """,
                values,
            )
    task = row_to_dict(conn.execute("SELECT * FROM production_tasks WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return task


def missing_task_fields(task: dict[str, Any]) -> list[str]:
    return [field for field in TASK_REQUIRED_FIELDS if task.get(field) in ("", None)]


def task_summary(task: dict[str, Any]) -> str:
    lines = []
    for field in TASK_FIELDS:
        value = task.get(field)
        if value not in ("", None):
            lines.append(f"- {TASK_FIELD_LABELS[field]}：{value}")
    return "\n".join(lines)
