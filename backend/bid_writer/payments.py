from __future__ import annotations

import re
import sqlite3
from datetime import date
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .production_tasks import get_production_task


PAYMENT_FIELDS = (
    "amount",
    "currency",
    "payment_stage",
    "payment_method",
    "status",
    "received_at",
    "proof",
    "notes",
)

PAID_STATUSES = {"已收款", "已确认", "已到账", "paid", "confirmed"}
REFUND_STATUSES = {"已退款", "退款", "refunded"}


def parse_amount(value: Any) -> float:
    text = str(value or "").replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else 0.0


def _clean_payment_payload(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field in PAYMENT_FIELDS:
        if field not in data:
            continue
        value = data.get(field)
        if field == "amount":
            cleaned[field] = parse_amount(value)
        else:
            cleaned[field] = str(value or "").strip()
    if "currency" in cleaned and not cleaned["currency"]:
        cleaned["currency"] = "CNY"
    if "payment_stage" in cleaned and not cleaned["payment_stage"]:
        cleaned["payment_stage"] = "定金"
    if "status" in cleaned and not cleaned["status"]:
        cleaned["status"] = "待确认"
    return cleaned


def list_payment_records(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM payment_records
            WHERE tender_id = ?
            ORDER BY COALESCE(received_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def payment_summary(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    task = get_production_task(tender_id, conn=conn)
    expected_amount = parse_amount(task.get("budget"))
    records = list_payment_records(tender_id, conn=conn)
    paid_amount = 0.0
    refunded_amount = 0.0
    pending_amount = 0.0
    for record in records:
        amount = float(record.get("amount") or 0)
        status = str(record.get("status") or "")
        if status in PAID_STATUSES:
            paid_amount += amount
        elif status in REFUND_STATUSES:
            refunded_amount += amount
        else:
            pending_amount += amount
    net_received = max(0.0, paid_amount - refunded_amount)
    outstanding = max(0.0, expected_amount - net_received) if expected_amount else 0.0
    if expected_amount and net_received >= expected_amount:
        status = "paid"
        status_label = "已收齐"
    elif net_received > 0:
        status = "partial"
        status_label = "部分收款"
    elif records:
        status = "pending"
        status_label = "待确认收款"
    elif expected_amount:
        status = "unpaid"
        status_label = "未收款"
    else:
        status = "unknown"
        status_label = "未登记价格"
    result = {
        "expected_amount": round(expected_amount, 2),
        "received_amount": round(net_received, 2),
        "paid_amount": round(paid_amount, 2),
        "refunded_amount": round(refunded_amount, 2),
        "pending_amount": round(pending_amount, 2),
        "outstanding_amount": round(outstanding, 2),
        "records_count": len(records),
        "status": status,
        "status_label": status_label,
        "currency": "CNY",
        "delivery_authorized": bool(expected_amount and net_received >= expected_amount),
        "requires_payment_confirmation": bool(expected_amount and net_received < expected_amount),
        "records": records,
    }
    if own_conn:
        conn.close()
    return result


def create_payment_record(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = conn.execute("SELECT id FROM tenders WHERE id = ?", (tender_id,)).fetchone()
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    cleaned = {
        "amount": 0.0,
        "currency": "CNY",
        "payment_stage": "定金",
        "payment_method": "",
        "status": "待确认",
        "received_at": date.today().isoformat(),
        "proof": "",
        "notes": "",
        **_clean_payment_payload(data),
    }
    columns = ", ".join(["tender_id", *PAYMENT_FIELDS])
    placeholders = ", ".join("?" for _ in ["tender_id", *PAYMENT_FIELDS])
    values = [tender_id, *[cleaned[field] for field in PAYMENT_FIELDS]]
    with conn:
        cur = conn.execute(f"INSERT INTO payment_records ({columns}) VALUES ({placeholders})", values)
    row = row_to_dict(conn.execute("SELECT * FROM payment_records WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def update_payment_record(
    payment_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM payment_records WHERE id = ?", (payment_id,)).fetchone())
    if not row:
        raise ValueError(f"Payment record not found: {payment_id}")
    cleaned = _clean_payment_payload(data)
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE payment_records
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*cleaned.values(), payment_id),
            )
    row = row_to_dict(conn.execute("SELECT * FROM payment_records WHERE id = ?", (payment_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def delete_payment_record(payment_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM payment_records WHERE id = ?", (payment_id,)).fetchone())
    if not row:
        if own_conn:
            conn.close()
        return {"deleted": False, "id": payment_id}
    with conn:
        conn.execute("DELETE FROM payment_records WHERE id = ?", (payment_id,))
    if own_conn:
        conn.close()
    return {"deleted": True, "id": payment_id}


def render_payments_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    summary = payment_summary(tender_id, conn=conn)
    lines = [
        "# 收款记录",
        "",
        f"- 订单金额：{summary['expected_amount']} 元",
        f"- 已确认收款：{summary['received_amount']} 元",
        f"- 待确认金额：{summary['pending_amount']} 元",
        f"- 未收金额：{summary['outstanding_amount']} 元",
        f"- 收款状态：{summary['status_label']}",
        "",
        "## 明细",
    ]
    if summary["records"]:
        for item in summary["records"]:
            lines.append(
                f"- #{item.get('id')} {item.get('payment_stage') or ''}：{item.get('amount') or 0} 元 / "
                f"{item.get('payment_method') or '未填方式'} / {item.get('status') or '待确认'} / "
                f"{item.get('received_at') or item.get('created_at') or ''}"
            )
            if item.get("proof") or item.get("notes"):
                lines.append(f"  备注：{item.get('proof') or ''} {item.get('notes') or ''}".strip())
    else:
        lines.append("- 暂无收款记录。交付前请人工确认收款或定金状态。")
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
