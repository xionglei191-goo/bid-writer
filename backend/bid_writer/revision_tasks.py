from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .quality_gate import build_quality_gate


EDITABLE_FIELDS = ("status", "owner", "due_at", "notes")
OPEN_STATUSES = {"待处理", "处理中", "需复核"}
DONE_STATUSES = {"已处理", "已消除", "无需处理"}


def _task_key(task: dict[str, Any]) -> str:
    parts = [
        str(task.get("severity") or ""),
        str(task.get("title") or ""),
        str(task.get("scope") or ""),
        str(task.get("section_title") or ""),
        str(task.get("draft_id") or ""),
        str(task.get("requirement_id") or ""),
        str(task.get("detail") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _clean_status(value: Any, fallback: str = "待处理") -> str:
    text = str(value or "").strip()
    return text or fallback


def _row_with_flags(row: dict[str, Any]) -> dict[str, Any]:
    row["active"] = bool(row.get("active"))
    row["is_done"] = str(row.get("status") or "") in DONE_STATUSES
    row["is_open"] = bool(row.get("active")) and not row["is_done"]
    return row


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    active = [item for item in items if item.get("active")]
    open_items = [item for item in active if item.get("is_open")]
    return {
        "total": len(items),
        "active": len(active),
        "open": len(open_items),
        "done": sum(1 for item in items if item.get("is_done")),
        "resolved_by_sync": sum(1 for item in items if not item.get("active")),
        "high_open": sum(1 for item in open_items if item.get("severity") == "high"),
        "medium_open": sum(1 for item in open_items if item.get("severity") == "medium"),
        "low_open": sum(1 for item in open_items if item.get("severity") == "low"),
        "readiness": "needs_work" if open_items else "ready",
    }


def list_revision_tasks(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM revision_tasks
            WHERE tender_id = ?
            ORDER BY
                active DESC,
                CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END,
                CASE status WHEN '待处理' THEN 0 WHEN '处理中' THEN 1 WHEN '需复核' THEN 2 ELSE 3 END,
                id
            """,
            (tender_id,),
        ).fetchall()
    )
    items = [_row_with_flags(row) for row in rows]
    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "summary": _summary(items),
        "items": items,
    }
    result["markdown"] = render_revision_tasks_markdown(result)
    if own_conn:
        conn.close()
    return result


def sync_revision_tasks(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    gate = build_quality_gate(tender_id, conn=conn)
    source_tasks = gate.get("revision_tasks") or []
    seen_keys: set[str] = set()
    inserted = 0
    updated = 0
    now = datetime.now().isoformat(timespec="seconds")

    with conn:
        for task in source_tasks:
            task_key = _task_key(task)
            seen_keys.add(task_key)
            existing = row_to_dict(
                conn.execute(
                    "SELECT id, status, resolved_at FROM revision_tasks WHERE tender_id = ? AND task_key = ?",
                    (tender_id, task_key),
                ).fetchone()
            )
            values = {
                "source": "quality_gate",
                "severity": str(task.get("severity") or "medium"),
                "title": str(task.get("title") or "修订任务"),
                "scope": str(task.get("scope") or ""),
                "detail": str(task.get("detail") or ""),
                "action": str(task.get("action") or ""),
                "section_title": str(task.get("section_title") or ""),
                "draft_id": int(task["draft_id"]) if task.get("draft_id") else None,
                "requirement_id": int(task["requirement_id"]) if task.get("requirement_id") else None,
            }
            if existing:
                status = _clean_status(existing.get("status"))
                resolved_at = existing.get("resolved_at")
                if status == "已消除":
                    status = "待处理"
                    resolved_at = None
                conn.execute(
                    """
                    UPDATE revision_tasks
                    SET source = ?, severity = ?, title = ?, scope = ?, detail = ?, action = ?,
                        section_title = ?, draft_id = ?, requirement_id = ?,
                        active = 1, status = ?, resolved_at = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        values["source"],
                        values["severity"],
                        values["title"],
                        values["scope"],
                        values["detail"],
                        values["action"],
                        values["section_title"],
                        values["draft_id"],
                        values["requirement_id"],
                        status,
                        resolved_at,
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO revision_tasks (
                        tender_id, task_key, source, severity, title, scope, detail, action,
                        section_title, draft_id, requirement_id, status, active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '待处理', 1)
                    """,
                    (
                        tender_id,
                        task_key,
                        values["source"],
                        values["severity"],
                        values["title"],
                        values["scope"],
                        values["detail"],
                        values["action"],
                        values["section_title"],
                        values["draft_id"],
                        values["requirement_id"],
                    ),
                )
                inserted += 1

        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT id, task_key, status
                FROM revision_tasks
                WHERE tender_id = ? AND active = 1
                """,
                (tender_id,),
            ).fetchall()
        )
        resolved = 0
        for row in rows:
            if row.get("task_key") in seen_keys:
                continue
            status = _clean_status(row.get("status"))
            next_status = status if status not in OPEN_STATUSES else "已消除"
            conn.execute(
                """
                UPDATE revision_tasks
                SET active = 0, status = ?, resolved_at = COALESCE(resolved_at, ?), updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_status, now, row["id"]),
            )
            resolved += 1

    report = list_revision_tasks(tender_id, conn=conn)
    report["sync"] = {
        "inserted": inserted,
        "updated": updated,
        "resolved": resolved,
        "source_task_count": len(source_tasks),
    }
    report["quality_gate"] = {"status": gate.get("status"), "score": gate.get("score"), "summary": gate.get("summary", {})}
    if own_conn:
        conn.close()
    return report


def update_revision_task(task_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    existing = row_to_dict(conn.execute("SELECT * FROM revision_tasks WHERE id = ?", (task_id,)).fetchone())
    if not existing:
        raise ValueError(f"Revision task not found: {task_id}")
    cleaned: dict[str, str] = {}
    for field in EDITABLE_FIELDS:
        if field in data:
            cleaned[field] = str(data.get(field) or "").strip()
    status = _clean_status(cleaned.get("status"), existing.get("status") or "待处理")
    resolved_at = existing.get("resolved_at")
    if status in DONE_STATUSES and not resolved_at:
        resolved_at = datetime.now().isoformat(timespec="seconds")
    if status not in DONE_STATUSES:
        resolved_at = None
    with conn:
        if cleaned:
            assignments = ", ".join(f"{field} = ?" for field in cleaned)
            conn.execute(
                f"""
                UPDATE revision_tasks
                SET {assignments}, resolved_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [*cleaned.values(), resolved_at, task_id],
            )
    row = row_to_dict(conn.execute("SELECT * FROM revision_tasks WHERE id = ?", (task_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return _row_with_flags(row)


def render_revision_tasks_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 修订任务台账",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        "",
        "## 台账概览",
        f"- 全部任务：{summary.get('total', 0)}",
        f"- 当前有效：{summary.get('active', 0)}",
        f"- 待处理：{summary.get('open', 0)}",
        f"- 已处理/无需处理：{summary.get('done', 0)}",
        f"- 同步消除：{summary.get('resolved_by_sync', 0)}",
        f"- 高风险待处理：{summary.get('high_open', 0)}",
        f"- 台账状态：{summary.get('readiness')}",
        "",
        "## 任务明细",
    ]
    items = report.get("items") or []
    if not items:
        lines.append("- 暂无修订任务。")
    for index, item in enumerate(items, 1):
        active = "有效" if item.get("active") else "已消除"
        section = f" / {item.get('section_title')}" if item.get("section_title") else ""
        lines.append(
            f"{index}. [{item.get('severity')}] {item.get('title')}（{item.get('scope')}{section} / {active} / {item.get('status')}）"
        )
        lines.append(f"   - 问题：{item.get('detail')}")
        lines.append(f"   - 动作：{item.get('action')}")
        if item.get("owner") or item.get("due_at") or item.get("notes"):
            lines.append(
                f"   - 处理：负责人 {item.get('owner') or '未指定'} / 截止 {item.get('due_at') or '未指定'} / 备注 {item.get('notes') or '无'}"
            )
    return "\n".join(lines).strip() + "\n"
