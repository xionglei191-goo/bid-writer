from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict
from .delivery_records import latest_delivery_record
from .delivery_review import build_delivery_review
from .feedback import feedback_summary
from .payments import payment_summary
from .production_tasks import get_production_task


def _status_text(status: str) -> str:
    return {
        "ready": "可交付",
        "needs_review": "需人工复核后交付",
        "needs_work": "需补齐后交付",
        "not_ready": "暂不可交付",
    }.get(status, status or "待确认")


def _package_file(package_path: str) -> dict[str, Any]:
    path = Path(package_path) if package_path else None
    return {
        "name": path.name if path else "交付包 ZIP",
        "path": str(path) if path else "",
        "exists": bool(path and path.exists()),
        "purpose": "交付主文件，客户发货包仅包含成稿和说明；内部归档包用于留存生产记录。",
    }


def _component_files(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not record:
        return []
    components = record.get("components") or {}
    labels = {
        "docx": "Word 技术标初稿",
        "markdown": "Markdown 备份稿",
        "overview": "项目总览",
        "document_settings": "成稿格式设置",
        "bid_strategy": "投标响应策略",
        "payments": "收款记录",
        "task": "生产任务归档",
        "profile": "项目资料归档",
        "coverage": "响应覆盖报告",
        "workflow": "生产流程状态",
        "delivery_review": "交付审查报告",
        "delivery_release": "交付放行单",
        "delivery_instruction": "交付说明",
        "client_docx": "客户版 Word 技术标初稿",
        "client_markdown": "客户版 Markdown 备份稿",
        "customer_note": "客户发货说明",
        "file_list": "客户文件清单",
        "readme": "README",
        "intake_assistant": "接单评估",
        "communications": "客户沟通记录",
        "price_quote": "报价测算",
        "order_confirmation": "订单确认单",
        "materials": "资料清单",
        "quality_gate": "质量门禁报告",
        "final_checklist": "最终核对清单",
        "final_document": "成稿确认报告",
        "replacement_records": "项目化校正记录",
        "closure_confirmation": "结案确认单",
        "retrospective": "项目复盘",
        "case_assets": "案例资产",
    }
    files = [_package_file(str(record.get("package_path") or ""))]
    for key, value in components.items():
        files.append(
            {
                "name": str(value),
                "path": str(value) if key in {"docx", "markdown"} else "",
                "exists": True,
                "purpose": labels.get(key, key),
            }
        )
    return files


def _build_customer_message(
    tender: dict[str, Any],
    task: dict[str, Any],
    review: dict[str, Any],
    record: dict[str, Any] | None,
) -> str:
    customer = task.get("customer_name") or "您好"
    project_name = tender.get("name") or task.get("project_name") or "本项目"
    readiness = _status_text(str((review.get("summary") or {}).get("readiness") or ""))
    package_name = Path(str((record or {}).get("package_path") or "")).name or "技术标交付包.zip"
    deadline = task.get("deadline") or "按约定时间"
    deliverable_format = task.get("deliverable_format") or "DOCX + ZIP 交付包"
    notes = task.get("delivery_notes") or ""

    if str((record or {}).get("package_format") or "") == "client_zip":
        package_description = "交付包内包含客户版 Word 初稿、Markdown 备份稿和客户发货说明。"
    else:
        package_description = "我会另行整理客户发货包，仅发送客户可接收的 Word 初稿、Markdown 备份稿和发货说明。"

    lines = [
        f"{customer}，您好。",
        f"{project_name} 的技术标初稿已整理完成，本次交付格式为 {deliverable_format}。",
        f"交付文件：{package_name}。",
        f"当前系统交付结论：{readiness}；交付期限：{deadline}。",
        package_description,
        "正式投标前，请结合最终招标文件核对项目名称、工期、质量安全目标、专用条款、页码目录和签章格式。",
    ]
    if notes:
        lines.append(f"备注：{notes}")
    lines.append("如需调整目录、补充专项章节或修改格式，可以继续发我，我会按反馈处理。")
    return "\n".join(lines)


def _build_internal_note(
    task: dict[str, Any],
    review: dict[str, Any],
    record: dict[str, Any] | None,
    feedback: dict[str, Any],
    payment: dict[str, Any],
) -> str:
    blockers = review.get("blockers") or []
    recommendations = review.get("recommendations") or []
    lines = [
        "# 内部交付检查",
        "",
        f"- 客户：{task.get('customer_name') or '未登记'}",
        f"- 来源平台：{task.get('source_platform') or '未登记'}",
        f"- 订单号：{task.get('order_no') or '未登记'}",
        f"- 交付期限：{task.get('deadline') or '未登记'}",
        f"- 交付状态：{(record or {}).get('status') or task.get('delivery_status') or '待生产'}",
        f"- 收款状态：{payment.get('status_label') or '未登记'}，已收 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元",
        "",
        "## 交付前待确认",
    ]
    if blockers:
        for item in blockers:
            lines.append(f"- [{item.get('severity')}] {item.get('title')}：{item.get('detail')}")
    else:
        lines.append("- 暂无阻碍项，仍需人工终审格式和投标专用条款。")
    if feedback.get("open"):
        lines.extend(["", "## 客户反馈待处理"])
        for item in feedback.get("latest_open", []):
            lines.append(f"- [{item.get('priority')}] {item.get('feedback_text')}；处理计划：{item.get('action_plan') or '待补充'}")
    if payment.get("requires_payment_confirmation"):
        lines.extend(["", "## 收款提醒", "- 正式发货前请人工确认收款、定金或客户约定，避免先发货后回款风险。"])
    lines.extend(["", "## 处理建议"])
    if recommendations:
        for item in recommendations:
            lines.append(f"- {item}")
    else:
        lines.append("- 无额外建议。")
    return "\n".join(lines).strip() + "\n"


def render_delivery_instruction(
    tender_id: int,
    package_result: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    own_conn = conn is None
    conn = conn or connect()
    report = build_delivery_assistant(tender_id, package_result=package_result, conn=conn)
    lines = [
        "# 交付说明",
        "",
        "## 客户发货说明",
        "",
        report["customer_message"],
        "",
        "## 交付文件清单",
    ]
    for item in report.get("files", []):
        lines.append(f"- {item.get('name')}：{item.get('purpose')}")
    lines.extend(["", report["internal_note"]])
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"


def build_delivery_assistant(
    tender_id: int,
    package_result: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    task = get_production_task(tender_id, conn=conn)
    review = build_delivery_review(tender_id, conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)
    record = latest_delivery_record(tender_id, conn=conn)
    if package_result:
        record = {
            **(record or {}),
            "package_path": package_result.get("path") or (record or {}).get("package_path") or "",
            "package_format": package_result.get("format") or "zip",
            "components": package_result.get("components") or (record or {}).get("components") or {},
            "status": (record or {}).get("status") or "已导出",
        }
    files = _component_files(record)
    has_package = bool(record and record.get("package_path"))
    summary = {
        "has_package": has_package,
        "package_exists": bool(files and files[0].get("exists")),
        "latest_record_id": record.get("id") if record else None,
        "delivery_status": record.get("status") if record else task.get("delivery_status") or "待生产",
        "readiness": (review.get("summary") or {}).get("readiness"),
        "readiness_text": _status_text(str((review.get("summary") or {}).get("readiness") or "")),
        "payment_status": payment.get("status"),
        "payment_status_label": payment.get("status_label"),
        "payment_received_amount": payment.get("received_amount", 0),
        "payment_outstanding_amount": payment.get("outstanding_amount", 0),
        "payment_requires_confirmation": payment.get("requires_payment_confirmation"),
    }
    actions = []
    if not has_package:
        actions.append("先导出 ZIP 交付包，形成可追溯交付记录。")
    if review.get("blockers"):
        actions.append("处理交付审查报告中的阻碍项，再发送给客户。")
    if feedback.get("open"):
        actions.append(f"当前还有 {feedback['open']} 条客户反馈未解决，建议处理后再交付新版本。")
    if payment.get("requires_payment_confirmation"):
        actions.append("正式发货前请人工确认收款、定金或客户约定。")
    if has_package and summary["delivery_status"] != "已交付":
        actions.append("发送给客户后，在交付记录中标记为已交付。")
    if not actions:
        actions.append("保留交付记录和客户确认信息，进入归档。")

    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "task": task,
        "latest_record": record or {},
        "summary": summary,
        "feedback": feedback,
        "payment": payment,
        "files": files,
        "actions": actions,
        "customer_message": _build_customer_message(tender, task, review, record),
        "internal_note": _build_internal_note(task, review, record, feedback, payment),
    }
    if own_conn:
        conn.close()
    return result
