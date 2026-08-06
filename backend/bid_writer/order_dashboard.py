from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from .db import connect, rows_to_dicts
from .payments import payment_summary


DEADLINE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d",
)


def _parse_deadline(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("T", " ").strip()
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in DEADLINE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def _stage(row: dict[str, Any]) -> str:
    if int(row.get("feedback_open") or 0):
        return "返工处理"
    if int(row.get("closure_count") or 0):
        return "已结案"
    if int(row.get("delivered_count") or 0):
        return "已交付"
    if int(row.get("delivery_count") or 0):
        return "待客户确认"
    plan_count = int(row.get("plan_count") or 0)
    generated_plan_count = int(row.get("generated_plan_count") or 0)
    if plan_count and generated_plan_count >= plan_count:
        return "待导出"
    if plan_count:
        return "生产中"
    if int(row.get("requirement_count") or 0):
        return "待生成目录"
    return "待解析"


def _next_action(stage: str, row: dict[str, Any]) -> str:
    if row.get("payment_requires_confirmation") and stage in {"待导出", "待客户确认", "已交付"}:
        return "确认收款或定金后再发送正式交付文件"
    actions = {
        "返工处理": "处理客户反馈并标记为已解决",
        "已结案": "保留最终交付包和结案确认",
        "已交付": "发送结案确认话术，收到确认后记录结案",
        "待客户确认": "确认客户接收后标记为已交付",
        "待导出": "导出 ZIP 交付包并进行人工终审",
        "生产中": "继续生成未完成章节",
        "待生成目录": "根据招标要求生成目录规划",
        "待解析": "录入或上传招标文件并解析要求",
    }
    if not row.get("customer_name"):
        return "补充客户名称和生产任务信息"
    return actions.get(stage, "检查项目状态")


def _urgency(row: dict[str, Any], now: datetime) -> str:
    if int(row.get("closure_count") or 0) and not int(row.get("feedback_open") or 0):
        return "已结案"
    if int(row.get("delivered_count") or 0):
        return "已交付"
    deadline = _parse_deadline(row.get("deadline"))
    if not deadline:
        return "未登记期限"
    if deadline < now:
        return "逾期"
    if deadline <= now + timedelta(hours=48):
        return "48小时内到期"
    if deadline <= now + timedelta(days=7):
        return "7天内到期"
    return "正常"


def build_order_dashboard(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT
                t.id,
                t.name,
                t.industry,
                t.region,
                t.created_at,
                COALESCE(pt.customer_name, '') AS customer_name,
                COALESCE(pt.source_platform, '') AS source_platform,
                COALESCE(pt.order_no, '') AS order_no,
                COALESCE(pt.deadline, '') AS deadline,
                COALESCE(pt.budget, '') AS budget,
                COALESCE(pt.delivery_status, '待生产') AS delivery_status,
                COALESCE(pt.internal_owner, '') AS internal_owner,
                (SELECT COUNT(*) FROM requirements r WHERE r.tender_id = t.id) AS requirement_count,
                (SELECT COUNT(*) FROM section_plans sp WHERE sp.tender_id = t.id) AS plan_count,
                (SELECT COUNT(*) FROM section_plans sp WHERE sp.tender_id = t.id AND sp.draft_id IS NOT NULL) AS generated_plan_count,
                (SELECT COUNT(*) FROM drafts d WHERE d.tender_id = t.id) AS draft_count,
                (SELECT COUNT(*) FROM delivery_records dr WHERE dr.tender_id = t.id) AS delivery_count,
                (SELECT COUNT(*) FROM delivery_records dr WHERE dr.tender_id = t.id AND dr.status IN ('已交付', '已结案')) AS delivered_count,
                (SELECT COUNT(*) FROM closure_records cr WHERE cr.tender_id = t.id AND cr.status = '客户已确认') AS closure_count,
                (SELECT COUNT(*) FROM feedback_items fi WHERE fi.tender_id = t.id AND fi.status <> '已解决') AS feedback_open
            FROM tenders t
            LEFT JOIN production_tasks pt ON pt.tender_id = t.id
            ORDER BY t.id DESC
            """
        ).fetchall()
    )
    now = datetime.now()
    items: list[dict[str, Any]] = []
    stages: Counter[str] = Counter()
    urgencies: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for row in rows:
        stage = _stage(row)
        urgency = _urgency(row, now)
        stages[stage] += 1
        urgencies[urgency] += 1
        statuses[str(row.get("delivery_status") or "待生产")] += 1
        plan_count = int(row.get("plan_count") or 0)
        generated_plan_count = int(row.get("generated_plan_count") or 0)
        payment = payment_summary(int(row["id"]), conn=conn)
        row_for_action = {**row, "payment_requires_confirmation": payment["requires_payment_confirmation"]}
        item = {
            **row,
            "stage": stage,
            "urgency": urgency,
            "payment_status": payment["status"],
            "payment_status_label": payment["status_label"],
            "payment_received_amount": payment["received_amount"],
            "payment_outstanding_amount": payment["outstanding_amount"],
            "payment_requires_confirmation": payment["requires_payment_confirmation"],
            "next_action": _next_action(stage, row_for_action),
            "plan_progress": f"{generated_plan_count}/{plan_count}" if plan_count else "0/0",
            "deadline_at": _parse_deadline(row.get("deadline")).isoformat(timespec="minutes")
            if _parse_deadline(row.get("deadline"))
            else "",
        }
        items.append(item)

    action_rank = {"逾期": 0, "48小时内到期": 1, "返工处理": 2, "待导出": 3}
    next_items = sorted(
        items,
        key=lambda item: (
            action_rank.get(item["urgency"], action_rank.get(item["stage"], 9)),
            item.get("deadline_at") or "9999-12-31",
            -int(item["id"]),
        ),
    )[:8]
    result = {
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": {
            "total": len(items),
            "overdue": urgencies.get("逾期", 0),
            "due_soon": urgencies.get("48小时内到期", 0),
            "due_this_week": urgencies.get("7天内到期", 0),
            "feedback_open": sum(int(item.get("feedback_open") or 0) for item in items),
            "pending_delivery": stages.get("待客户确认", 0) + stages.get("待导出", 0),
            "delivered": stages.get("已交付", 0),
            "closed": stages.get("已结案", 0),
            "payment_unpaid": sum(1 for item in items if item.get("payment_status") == "unpaid"),
            "payment_partial": sum(1 for item in items if item.get("payment_status") == "partial"),
            "payment_paid": sum(1 for item in items if item.get("payment_status") == "paid"),
            "payment_pending_amount": round(sum(float(item.get("payment_outstanding_amount") or 0) for item in items), 2),
        },
        "by_stage": [{"name": key, "count": value} for key, value in stages.most_common()],
        "by_urgency": [{"name": key, "count": value} for key, value in urgencies.most_common()],
        "by_delivery_status": [{"name": key, "count": value} for key, value in statuses.most_common()],
        "next_items": next_items,
        "items": items,
    }
    if own_conn:
        conn.close()
    return result
