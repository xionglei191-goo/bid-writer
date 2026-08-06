from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .delivery_records import latest_delivery_record, update_delivery_record
from .delivery_review import build_delivery_review
from .feedback import feedback_summary, list_feedback_items
from .order_confirmation import build_order_confirmation
from .production_tasks import get_production_task, update_production_task


CONFIRMED_STATUSES = {"已交付", "已结案"}


def _text(value: Any, default: str = "未登记") -> str:
    text = str(value or "").strip()
    return text or default


def _delivery_confirmed(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    return str(record.get("status") or "") in CONFIRMED_STATUSES or bool(record.get("delivered_at"))


def _package_exists(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    package_path = str(record.get("package_path") or "")
    return bool(package_path and Path(package_path).exists())


def list_closure_records(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM closure_records
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def latest_closure_record(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM closure_records
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    )
    if own_conn:
        conn.close()
    return row


def _pseudo_record_from_package(package_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": None,
        "package_path": package_result.get("path") or "",
        "package_format": package_result.get("format") or "zip",
        "components": package_result.get("components") or {},
        "status": "已导出",
        "delivered_at": "",
    }


def _checklist(
    record: dict[str, Any] | None,
    feedback: dict[str, Any],
    order_confirmation: dict[str, Any],
    review: dict[str, Any],
    closure: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    confirmed = _delivery_confirmed(record)
    has_package = bool(record and record.get("package_path"))
    package_exists = _package_exists(record)
    open_feedback = int(feedback.get("open") or 0)
    scope = order_confirmation.get("scope") or {}
    blockers = review.get("blockers") or []
    closed = str((closure or {}).get("status") or "") == "客户已确认"
    return [
        {
            "title": "交付包归档",
            "status": "complete" if package_exists else ("warning" if has_package else "pending"),
            "detail": Path(str((record or {}).get("package_path") or "")).name if has_package else "尚未导出 ZIP 交付包",
            "action": "" if package_exists else "先导出交付包并确认文件存在",
        },
        {
            "title": "客户收货状态",
            "status": "complete" if confirmed else "pending",
            "detail": str((record or {}).get("status") or "尚未交付"),
            "action": "" if confirmed else "发送给客户后在交付记录中标记为已交付",
        },
        {
            "title": "客户反馈返工",
            "status": "complete" if open_feedback == 0 else "warning",
            "detail": f"未处理反馈 {open_feedback} 条",
            "action": "" if open_feedback == 0 else "先处理反馈并标记为已解决",
        },
        {
            "title": "订单范围确认",
            "status": "complete" if order_confirmation.get("customer_message") else "warning",
            "detail": f"交付范围：{_text(scope.get('deliverables'), '按订单确认单')}",
            "action": "" if order_confirmation.get("customer_message") else "补齐订单确认单",
        },
        {
            "title": "交付审查留痕",
            "status": "complete" if not blockers else "warning",
            "detail": "暂无阻碍项" if not blockers else f"仍有 {len(blockers)} 个交付审查关注项",
            "action": "" if not blockers else "结案前确认这些关注项已人工接受或处理",
        },
        {
            "title": "结案确认记录",
            "status": "complete" if closed else "pending",
            "detail": f"最新状态：{_text((closure or {}).get('status'), '未记录')}",
            "action": "" if closed else "收到客户确认后记录结案",
        },
    ]


def _blockers(
    record: dict[str, Any] | None,
    feedback: dict[str, Any],
    closure: dict[str, Any] | None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not record or not record.get("package_path"):
        items.append({"severity": "high", "title": "尚未导出交付包", "detail": "没有可追溯的 ZIP 交付包记录。"})
    elif not _delivery_confirmed(record):
        items.append({"severity": "high", "title": "尚未确认客户收货", "detail": "交付记录还没有标记为已交付。"})
    if int(feedback.get("open") or 0):
        items.append(
            {
                "severity": "high",
                "title": "仍有客户反馈未解决",
                "detail": f"当前还有 {feedback.get('open')} 条反馈或返工事项未关闭。",
            }
        )
    return items


def _closure_status(
    record: dict[str, Any] | None,
    feedback: dict[str, Any],
    closure: dict[str, Any] | None,
) -> str:
    if not record or not record.get("package_path"):
        return "待导出"
    if not _delivery_confirmed(record):
        return "待客户确认"
    if int(feedback.get("open") or 0):
        return "需返工处理"
    if str((closure or {}).get("status") or "") == "客户已确认":
        return "已结案"
    return "可结案"


def _customer_message(
    tender: dict[str, Any],
    task: dict[str, Any],
    record: dict[str, Any] | None,
    status: str,
    data: dict[str, Any],
    closure: dict[str, Any] | None,
) -> str:
    customer = task.get("customer_name") or "您好"
    project_name = tender.get("name") or task.get("project_name") or "本项目"
    package_name = Path(str((record or {}).get("package_path") or "")).name or "技术标交付包.zip"
    reply_deadline = str(data.get("reply_deadline") or (closure or {}).get("reply_deadline") or "").strip()
    extra_note = str(data.get("extra_note") or "").strip()
    deadline_text = f"请在 {reply_deadline} 前反馈" if reply_deadline else "请在约定修改期内反馈"

    if status == "已结案":
        lines = [
            f"{customer}，您好。",
            f"{project_name} 的技术标交付文件已按您的确认结案归档。",
            f"最终交付文件：{package_name}。",
            "后续如有新增章节、招标文件重大变更、商务报价资料或超出原订单范围的调整，可以另行确认费用和工期后继续处理。",
        ]
    elif status == "可结案":
        lines = [
            f"{customer}，您好。",
            f"{project_name} 的技术标文件已按本次确认范围完成交付。",
            f"交付文件：{package_name}。",
            f"请您确认文件已收到，且本次交付版本可以作为本单最终交付版本；如仍有本次范围内修改意见，{deadline_text}。",
            "确认无误后，本单将按已完成结案归档。后续新增章节、招标文件重大变更、商务报价资料或超出原订单范围的调整，将另行确认费用和工期。",
        ]
    else:
        lines = [
            f"{customer}，您好。",
            f"{project_name} 当前状态为“{status}”，暂不建议直接结案。",
            "我会先把交付确认、反馈处理或补充资料事项处理完，再向您发起最终结案确认。",
        ]
        if record and record.get("package_path"):
            lines.insert(2, f"当前交付文件：{package_name}。")
    if extra_note:
        lines.append(f"补充说明：{extra_note}")
    return "\n".join(lines)


def render_closure_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    task = report.get("task") or {}
    latest_record = report.get("latest_delivery") or {}
    latest_closure = report.get("latest_closure") or {}
    lines = [
        "# 结案确认单",
        "",
        "## 基本信息",
        f"- 项目名称：{_text(tender.get('name'))}",
        f"- 客户：{_text(task.get('customer_name'))}",
        f"- 来源平台：{_text(task.get('source_platform'))}",
        f"- 订单号：{_text(task.get('order_no'))}",
        f"- 交付包：{_text(Path(str(latest_record.get('package_path') or '')).name, '未生成')}",
        f"- 最新交付状态：{_text(latest_record.get('status'), '未交付')}",
        f"- 最新结案状态：{_text(latest_closure.get('status'), '未记录')}",
        "",
        "## 结案判断",
        f"- 当前状态：{summary.get('closure_status')}",
        f"- 是否可结案：{'是' if summary.get('can_close') else '否'}",
        f"- 未处理反馈：{summary.get('open_feedback', 0)} 条",
        "",
        "## 检查清单",
    ]
    for item in report.get("checklist", []):
        lines.append(f"- [{item.get('status')}] {item.get('title')}：{item.get('detail')}；动作：{item.get('action') or '无'}")
    blockers = report.get("blockers") or []
    lines.extend(["", "## 未满足事项"])
    if blockers:
        for item in blockers:
            lines.append(f"- [{item.get('severity')}] {item.get('title')}：{item.get('detail')}")
    else:
        lines.append("- 暂无阻碍事项。")
    lines.extend(["", "## 客户结案话术", "", report.get("customer_message") or ""])
    records = report.get("closure_records") or []
    lines.extend(["", "## 结案记录"])
    if records:
        for item in records:
            lines.append(
                f"- {item.get('created_at')} / {item.get('status')} / 确认人：{_text(item.get('confirmed_by'))} / {item.get('confirmation_note') or ''}"
            )
    else:
        lines.append("- 尚未记录客户结案确认。")
    return "\n".join(lines).strip() + "\n"


def build_closure_confirmation(
    tender_id: int,
    data: dict[str, Any] | None = None,
    package_result: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    payload = data or {}
    task = get_production_task(tender_id, conn=conn)
    review = build_delivery_review(tender_id, conn=conn)
    order_confirmation = build_order_confirmation(tender_id, conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    record = latest_delivery_record(tender_id, conn=conn)
    if package_result:
        record = {**_pseudo_record_from_package(package_result), **(record or {})}
        if not record.get("package_path"):
            record["package_path"] = package_result.get("path") or ""
    latest_closure = latest_closure_record(tender_id, conn=conn)
    closure_records = list_closure_records(tender_id, conn=conn)
    status = _closure_status(record, feedback, latest_closure)
    blockers = _blockers(record, feedback, latest_closure)
    can_close = status in {"可结案", "已结案"}
    checklist = _checklist(record, feedback, order_confirmation, review, latest_closure)
    pending_actions = [item["detail"] for item in blockers]
    if status == "可结案":
        pending_actions.append("向客户发送结案确认话术，收到确认后记录为客户已确认。")
    elif status == "已结案":
        pending_actions.append("保留结案确认和最终交付包，项目进入归档。")
    customer_message = _customer_message(tender, task, record, status, payload, latest_closure)
    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "task": task,
        "latest_delivery": record or {},
        "latest_closure": latest_closure or {},
        "closure_records": closure_records,
        "summary": {
            "closure_status": status,
            "can_close": can_close,
            "can_record_closure": can_close and status != "已结案",
            "has_package": bool(record and record.get("package_path")),
            "package_exists": _package_exists(record),
            "delivery_confirmed": _delivery_confirmed(record),
            "delivery_status": (record or {}).get("status") or "未交付",
            "open_feedback": int(feedback.get("open") or 0),
            "resolved_feedback": int(feedback.get("resolved") or 0),
        },
        "feedback": feedback,
        "latest_feedback": list_feedback_items(tender_id, conn=conn)[:5],
        "order_confirmation": order_confirmation,
        "delivery_review": {"summary": review.get("summary") or {}, "blockers": review.get("blockers") or []},
        "checklist": checklist,
        "blockers": blockers,
        "pending_actions": pending_actions,
        "customer_message": customer_message,
    }
    result["markdown"] = render_closure_markdown(result)
    if own_conn:
        conn.close()
    return result


def record_closure_confirmation(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    payload = data or {}
    report = build_closure_confirmation(tender_id, payload, conn=conn)
    status = str(payload.get("status") or "客户已确认").strip() or "客户已确认"
    if status == "客户已确认" and not report["summary"].get("can_close"):
        reasons = "；".join(item.get("detail", "") for item in report.get("blockers", [])) or "当前状态不满足结案条件"
        raise ValueError(f"暂不能记录客户已确认结案：{reasons}")

    latest_record = report.get("latest_delivery") or {}
    confirmed_at = datetime.now().isoformat(timespec="seconds") if status == "客户已确认" else ""
    note = str(payload.get("confirmation_note") or "").strip()
    message = str(payload.get("customer_message") or report.get("customer_message") or "")
    with conn:
        conn.execute(
            """
            INSERT INTO closure_records (
                tender_id, delivery_record_id, status, confirmed_by,
                reply_deadline, confirmation_note, customer_message, confirmed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                latest_record.get("id") or None,
                status,
                str(payload.get("confirmed_by") or "").strip(),
                str(payload.get("reply_deadline") or "").strip(),
                note,
                message,
                confirmed_at,
            ),
        )
    if status == "客户已确认":
        delivery_id = latest_record.get("id")
        if delivery_id:
            update_delivery_record(
                int(delivery_id),
                {
                    "status": "已结案",
                    "notes": note or "客户已确认最终交付版本，系统记录结案。",
                },
                conn=conn,
            )
        update_production_task(
            tender_id,
            {
                "delivery_status": "已结案",
                "delivery_notes": note or "客户已确认最终交付版本，项目结案归档。",
            },
            conn=conn,
        )
    result = build_closure_confirmation(tender_id, payload, conn=conn)
    if own_conn:
        conn.close()
    return result
