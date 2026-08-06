from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .client_package_validation import validate_latest_client_package
from .db import connect, row_to_dict
from .delivery_records import latest_delivery_record, update_delivery_record
from .delivery_release import build_delivery_release
from .feedback import feedback_summary
from .payments import payment_summary
from .production_tasks import get_production_task, update_production_task


CONFIRMED_DELIVERY_STATUSES = {"已交付", "已结案"}


def _text(value: Any, default: str = "未登记") -> str:
    text = str(value or "").strip()
    return text or default


def _package_name(record: dict[str, Any] | None) -> str:
    path = Path(str((record or {}).get("package_path") or ""))
    return path.name if path.name else "客户发货包.zip"


def _delivery_confirmed(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    return str(record.get("status") or "") in CONFIRMED_DELIVERY_STATUSES or bool(record.get("delivered_at"))


def _client_package_ready(validation: dict[str, Any]) -> bool:
    summary = validation.get("summary") or {}
    return bool(
        summary.get("package_exists")
        and summary.get("zip_readable")
        and str(summary.get("readiness") or "") == "ready"
        and int(summary.get("missing_files") or 0) == 0
        and int(summary.get("forbidden_files") or 0) == 0
        and int(summary.get("content_findings") or 0) == 0
    )


def _status_label(status: str) -> str:
    return {
        "ready": "可发货",
        "blocked": "暂不可发货",
        "sent": "已发出",
    }.get(status, status or "待确认")


def _checklist(
    record: dict[str, Any] | None,
    validation: dict[str, Any],
    feedback: dict[str, Any],
    payment: dict[str, Any],
    release: dict[str, Any],
) -> list[dict[str, Any]]:
    validation_summary = validation.get("summary") or {}
    release_summary = release.get("summary") or {}
    payment_requires_confirmation = bool(payment.get("requires_payment_confirmation"))
    open_feedback = int(feedback.get("open") or 0)
    return [
        {
            "title": "客户发货包",
            "status": "complete" if record and record.get("package_path") else "pending",
            "detail": _package_name(record) if record and record.get("package_path") else "尚未导出客户发货包",
            "action": "" if record and record.get("package_path") else "先导出客户发货包",
        },
        {
            "title": "客户包安全核验",
            "status": "complete" if _client_package_ready(validation) else "pending",
            "detail": (
                f"状态 {validation_summary.get('readiness') or 'unknown'}，"
                f"缺失 {validation_summary.get('missing_files', 0)}，"
                f"内部文件 {validation_summary.get('forbidden_files', 0)}，"
                f"内容风险 {validation_summary.get('content_findings', 0)}"
            ),
            "action": "" if _client_package_ready(validation) else "重新导出或修正客户发货包",
        },
        {
            "title": "客户反馈返工",
            "status": "complete" if open_feedback == 0 else "pending",
            "detail": f"未处理反馈 {open_feedback} 条",
            "action": "" if open_feedback == 0 else "先处理客户反馈并标记解决",
        },
        {
            "title": "收款确认",
            "status": "complete" if not payment_requires_confirmation else "pending",
            "detail": (
                f"{payment.get('status_label') or '未登记'}，"
                f"已收 {payment.get('received_amount', 0)} 元，"
                f"未收 {payment.get('outstanding_amount', 0)} 元"
            ),
            "action": "" if not payment_requires_confirmation else "发货前人工确认收款或约定",
        },
        {
            "title": "交付放行单",
            "status": "complete" if release_summary.get("release_status") in {"ready", "conditional"} else "warning",
            "detail": f"放行状态：{release_summary.get('release_status') or '未生成'}",
            "action": "" if release_summary.get("release_status") in {"ready", "conditional"} else "人工确认放行单阻断项是否已接受",
        },
        {
            "title": "发货记录",
            "status": "complete" if _delivery_confirmed(record) else "pending",
            "detail": str((record or {}).get("status") or "尚未记录客户包已发出"),
            "action": "" if _delivery_confirmed(record) else "发给客户后点击记录客户包已发出",
        },
    ]


def _blockers(
    record: dict[str, Any] | None,
    validation: dict[str, Any],
    feedback: dict[str, Any],
    payment: dict[str, Any],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    validation_summary = validation.get("summary") or {}
    if not record or not record.get("package_path"):
        items.append({"severity": "high", "title": "尚未导出客户发货包", "detail": "没有 client_zip 交付记录可用于外发。"})
    elif not validation_summary.get("package_exists"):
        items.append({"severity": "high", "title": "客户发货包文件不存在", "detail": str(record.get("package_path") or "")})
    if not _client_package_ready(validation):
        for item in validation.get("blockers") or []:
            items.append(
                {
                    "severity": "high",
                    "title": str(item.get("title") or "客户包安全核验未通过"),
                    "detail": str(item.get("detail") or ""),
                }
            )
        if not (validation.get("blockers") or []):
            items.append(
                {
                    "severity": "high",
                    "title": "客户包安全核验未通过",
                    "detail": (
                        f"核验状态 {validation_summary.get('readiness') or 'unknown'}，"
                        f"缺失 {validation_summary.get('missing_files', 0)}，"
                        f"内部文件 {validation_summary.get('forbidden_files', 0)}，"
                        f"内容风险 {validation_summary.get('content_findings', 0)}。"
                    ),
                }
            )
    if int(feedback.get("open") or 0):
        items.append(
            {
                "severity": "high",
                "title": "仍有客户反馈未解决",
                "detail": f"当前还有 {feedback.get('open')} 条反馈或返工事项未关闭。",
            }
        )
    if payment.get("requires_payment_confirmation"):
        items.append(
            {
                "severity": "high",
                "title": "收款仍需确认",
                "detail": f"当前收款状态为 {payment.get('status_label') or '未登记'}，未收 {payment.get('outstanding_amount', 0)} 元。",
            }
        )
    return items


def _warnings(
    validation: dict[str, Any],
    release: dict[str, Any],
    payment: dict[str, Any],
    record: dict[str, Any] | None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in validation.get("warnings") or []:
        items.append({"title": str(item.get("title") or "客户包提醒"), "detail": str(item.get("detail") or "")})
    release_summary = release.get("summary") or {}
    if release_summary.get("release_status") == "blocked":
        items.append(
            {
                "title": "交付放行单仍为阻断",
                "detail": "客户包安全和收款反馈已单独校验，但建议发货前人工复核交付放行单。",
            }
        )
    if payment.get("status") == "unknown":
        items.append({"title": "订单金额未登记", "detail": "系统无法自动判断是否已收齐，默认交由人工确认。"})
    if _delivery_confirmed(record):
        items.append({"title": "客户包已记录发出", "detail": "再次确认会更新渠道、接收人和备注。"})
    return items


def _customer_message(
    tender: dict[str, Any],
    task: dict[str, Any],
    record: dict[str, Any] | None,
    payload: dict[str, Any],
) -> str:
    customer = _text(task.get("customer_name"), "您好")
    project_name = tender.get("name") or task.get("project_name") or "本项目"
    package_name = _package_name(record)
    deadline = task.get("deadline") or "按约定时间"
    extra_note = str(payload.get("extra_note") or "").strip()
    lines = [
        f"{customer}，您好。",
        f"{project_name} 的技术标客户版文件已整理完成。",
        f"本次发送文件：{package_name}。",
        "压缩包内包含客户版 Word 初稿、Markdown 备份稿、客户发货说明和文件清单。",
        f"交付时间要求：{deadline}。",
        "正式投标前，请结合最终招标文件核对项目名称、工期、质量安全目标、专用条款、页码目录和签章格式。",
        "如需调整目录、补充专项章节或修改格式，可以继续发我，我会按反馈处理。",
    ]
    if extra_note:
        lines.append(f"补充说明：{extra_note}")
    return "\n".join(lines)


def render_client_delivery_confirmation_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    task = report.get("task") or {}
    summary = report.get("summary") or {}
    package = report.get("latest_client_package") or {}
    lines = [
        "# 客户发货确认单",
        "",
        "## 基本信息",
        f"- 项目名称：{_text(tender.get('name'))}",
        f"- 客户：{_text(task.get('customer_name'))}",
        f"- 来源平台：{_text(task.get('source_platform'))}",
        f"- 订单号：{_text(task.get('order_no'))}",
        f"- 客户包：{_text(Path(str(package.get('package_path') or '')).name, '未生成')}",
        f"- 发货状态：{summary.get('send_label') or '待确认'}",
        "",
        "## 发货判断",
        f"- 是否可发货：{'是' if summary.get('can_send') else '否'}",
        f"- 客户包安全：{'通过' if summary.get('client_package_ready') else '未通过'}",
        f"- 未处理反馈：{summary.get('open_feedback', 0)} 条",
        f"- 收款状态：{summary.get('payment_status_label') or '未登记'}",
        "",
        "## 检查清单",
    ]
    for item in report.get("checklist") or []:
        lines.append(f"- [{item.get('status')}] {item.get('title')}：{item.get('detail')}；动作：{item.get('action') or '无'}")
    lines.extend(["", "## 阻断项"])
    blockers = report.get("blockers") or []
    if blockers:
        for item in blockers:
            lines.append(f"- [{item.get('severity')}] {item.get('title')}：{item.get('detail')}")
    else:
        lines.append("- 暂无阻断项。")
    lines.extend(["", "## 提醒项"])
    warnings = report.get("warnings") or []
    if warnings:
        for item in warnings:
            lines.append(f"- {item.get('title')}：{item.get('detail')}")
    else:
        lines.append("- 暂无提醒项。")
    lines.extend(["", "## 客户发货话术", "", report.get("customer_message") or ""])
    return "\n".join(lines).strip() + "\n"


def build_client_delivery_confirmation(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    payload = data or {}
    task = get_production_task(tender_id, conn=conn)
    record = latest_delivery_record(tender_id, conn=conn, package_formats=("client_zip",))
    validation = validate_latest_client_package(tender_id, conn=conn)
    release = build_delivery_release(tender_id, conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)
    blockers = _blockers(record, validation, feedback, payment)
    warnings = _warnings(validation, release, payment, record)
    confirmed = _delivery_confirmed(record)
    can_send = not blockers
    send_status = "sent" if confirmed else ("ready" if can_send else "blocked")
    report = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "task": task,
        "latest_client_package": record or {},
        "client_package_validation": validation,
        "delivery_release": {"summary": release.get("summary") or {}, "checks": release.get("checks") or []},
        "feedback": feedback,
        "payment": payment,
        "summary": {
            "send_status": send_status,
            "send_label": _status_label(send_status),
            "can_send": can_send,
            "can_record_delivery": can_send and not confirmed,
            "has_client_package": bool(record and record.get("package_path")),
            "package_exists": bool((validation.get("summary") or {}).get("package_exists")),
            "client_package_ready": _client_package_ready(validation),
            "delivery_confirmed": confirmed,
            "latest_client_record_id": record.get("id") if record else None,
            "latest_client_delivery_status": (record or {}).get("status") or "未交付",
            "open_feedback": int(feedback.get("open") or 0),
            "payment_status": payment.get("status"),
            "payment_status_label": payment.get("status_label"),
            "payment_requires_confirmation": bool(payment.get("requires_payment_confirmation")),
            "release_status": (release.get("summary") or {}).get("release_status"),
        },
        "checklist": _checklist(record, validation, feedback, payment, release),
        "blockers": blockers,
        "warnings": warnings,
        "customer_message": _customer_message(tender, task, record, payload),
    }
    report["markdown"] = render_client_delivery_confirmation_markdown(report)
    if own_conn:
        conn.close()
    return report


def confirm_client_delivery(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    payload = data or {}
    report = build_client_delivery_confirmation(tender_id, payload, conn=conn)
    if not report["summary"].get("can_send"):
        reasons = "；".join(item.get("detail", "") for item in report.get("blockers", [])) or "当前状态不满足客户发货条件"
        raise ValueError(f"暂不能记录客户包已发出：{reasons}")

    latest_record = report.get("latest_client_package") or {}
    record_id = latest_record.get("id")
    if not record_id:
        raise ValueError("没有可记录发货的客户发货包。")

    task = report.get("task") or {}
    channel = str(payload.get("delivery_channel") or task.get("source_platform") or "").strip()
    recipient = str(payload.get("recipient") or task.get("customer_name") or "").strip()
    note = str(payload.get("confirmation_note") or "").strip()
    message = str(payload.get("customer_message") or report.get("customer_message") or "").strip()
    notes = note or "客户发货包已由人工确认发出。"
    if message:
        notes = f"{notes}\n\n客户发货话术：\n{message}"
    update_delivery_record(
        int(record_id),
        {
            "delivery_channel": channel,
            "recipient": recipient,
            "status": "已交付",
            "notes": notes,
        },
        conn=conn,
    )
    update_production_task(
        tender_id,
        {
            "delivery_status": "已交付",
            "delivery_notes": note or "客户发货包已确认发出，等待客户反馈或验收。",
        },
        conn=conn,
    )
    result = build_client_delivery_confirmation(tender_id, payload, conn=conn)
    if own_conn:
        conn.close()
    return result
