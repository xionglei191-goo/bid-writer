from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .production_tasks import get_production_task, update_production_task


def _count(conn: sqlite3.Connection, table: str, tender_id: int, extra_where: str = "", params: tuple[Any, ...] = ()) -> int:
    where = f"WHERE tender_id = ? {extra_where}"
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} {where}", (tender_id, *params)).fetchone()[0])


def infer_production_status(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    requirement_count = _count(conn, "requirements", tender_id)
    plan_count = _count(conn, "section_plans", tender_id)
    generated_plan_count = _count(conn, "section_plans", tender_id, "AND draft_id IS NOT NULL")
    draft_count = _count(conn, "drafts", tender_id)
    delivery_count = _count(conn, "delivery_records", tender_id)
    delivered_count = _count(conn, "delivery_records", tender_id, "AND status IN (?, ?)", ("已交付", "已结案"))
    closed_count = _count(conn, "closure_records", tender_id, "AND status = ?", ("客户已确认",))
    feedback_open = _count(conn, "feedback_items", tender_id, "AND status <> ?", ("已解决",))

    status = "待解析"
    reason = "尚未形成招标要求响应矩阵。"
    next_action = "录入或上传招标文件并解析要求。"
    if feedback_open:
        status = "返工处理"
        reason = f"仍有 {feedback_open} 条客户反馈或返工事项未解决。"
        next_action = "处理反馈并标记为已解决。"
    elif closed_count:
        status = "已结案"
        reason = f"已有 {closed_count} 条客户结案确认记录。"
        next_action = "保留最终交付包和结案确认，项目归档。"
    elif delivered_count:
        status = "已交付"
        reason = f"已有 {delivered_count} 条交付记录标记为已交付。"
        next_action = "发送结案确认话术，收到客户确认后记录结案。"
    elif delivery_count:
        status = "待客户确认"
        reason = "交付包已导出，等待客户接收确认。"
        next_action = "确认客户接收后标记交付记录为已交付。"
    elif plan_count and generated_plan_count >= plan_count:
        status = "待导出"
        reason = f"规划章节已生成 {generated_plan_count}/{plan_count}，可进入导出与终审。"
        next_action = "导出 ZIP 交付包并进行人工终审。"
    elif plan_count:
        status = "生产中"
        reason = f"已规划 {plan_count} 个章节，已生成 {generated_plan_count} 个章节。"
        next_action = "继续生成未完成章节。"
    elif requirement_count:
        status = "待生成目录"
        reason = f"已解析 {requirement_count} 条要求，尚未形成目录规划。"
        next_action = "根据招标要求生成目录规划。"

    result = {
        "tender_id": tender_id,
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "counts": {
            "requirements": requirement_count,
            "plans": plan_count,
            "generated_plans": generated_plan_count,
            "drafts": draft_count,
            "delivery_records": delivery_count,
            "delivered_records": delivered_count,
            "closed_records": closed_count,
            "feedback_open": feedback_open,
        },
    }
    if own_conn:
        conn.close()
    return result


def sync_production_status(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    task = get_production_task(tender_id, conn=conn)
    inferred = infer_production_status(tender_id, conn=conn)
    previous_status = str(task.get("delivery_status") or "")
    if previous_status != inferred["status"]:
        task = update_production_task(tender_id, {"delivery_status": inferred["status"]}, conn=conn)
    result = {
        "tender_id": tender_id,
        "previous_status": previous_status,
        "current_status": task.get("delivery_status") or inferred["status"],
        "changed": previous_status != inferred["status"],
        "inferred": inferred,
        "task": task,
    }
    if own_conn:
        conn.close()
    return result


def sync_all_production_status(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tenders = rows_to_dicts(conn.execute("SELECT id, name FROM tenders ORDER BY id DESC").fetchall())
    results = [sync_production_status(int(tender["id"]), conn=conn) for tender in tenders]
    changed = [item for item in results if item["changed"]]
    result = {
        "total": len(results),
        "changed": len(changed),
        "items": results,
    }
    if own_conn:
        conn.close()
    return result
