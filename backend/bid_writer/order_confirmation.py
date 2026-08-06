from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict
from .intake_assistant import build_intake_assistant
from .materials import material_summary
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


DEFAULT_DELIVERABLES = (
    "技术标 Word 初稿",
    "Markdown 备份稿",
    "响应覆盖检查",
    "质量门禁报告",
    "交付审查报告",
    "ZIP 归档交付包",
)

DEFAULT_EXCLUSIONS = (
    "不承诺中标结果",
    "不代做报价、清单组价和商务资质原件扫描",
    "不代替投标人最终盖章、签字和平台递交",
    "客户补充资料或招标文件范围变化较大时，需要重新确认工期和费用",
)


def _split_items(text: str) -> list[str]:
    parts = [item.strip(" ，,；;、\n\t") for item in text.replace("\n", "、").replace(";", "、").replace("；", "、").split("、")]
    return [item for item in parts if item]


def build_order_confirmation(
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
    profile = get_project_profile(tender_id, conn=conn)
    intake = build_intake_assistant(tender_id, conn=conn)
    materials = material_summary(tender_id, conn=conn)
    estimate = intake.get("estimate", {})
    acceptance = intake.get("acceptance", {})

    agreed_price = str(payload.get("agreed_price") or task.get("budget") or estimate.get("suggested_price") or "").strip()
    deadline = str(payload.get("deadline") or task.get("deadline") or intake.get("input", {}).get("deadline") or "待确认").strip()
    revision_rounds = str(payload.get("revision_rounds") or "2").strip()
    deliverables = _split_items(str(payload.get("deliverables") or "")) or list(DEFAULT_DELIVERABLES)
    exclusions = _split_items(str(payload.get("exclusions") or "")) or list(DEFAULT_EXCLUSIONS)
    pending_material_names = [str(item.get("name") or "") for item in materials.get("pending_required_items", [])]

    project_name = str(profile.get("project_name") or tender.get("name") or "")
    customer = str(task.get("customer_name") or "客户").strip()
    confirmation = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender_id": tender_id,
        "project": {
            "name": project_name,
            "industry": profile.get("industry") or tender.get("industry") or "",
            "region": profile.get("region") or tender.get("region") or "",
            "project_type": profile.get("project_type") or "",
        },
        "customer": {
            "name": customer,
            "contact": task.get("contact") or "",
            "source_platform": task.get("source_platform") or "",
            "order_no": task.get("order_no") or "",
        },
        "commercial": {
            "agreed_price": agreed_price or "待确认",
            "deadline": deadline,
            "deliverable_format": task.get("deliverable_format") or "DOCX + ZIP 交付包",
            "revision_rounds": revision_rounds,
        },
        "scope": {
            "deliverables": deliverables,
            "preconditions": [
                "以客户提供的最终招标文件、评分办法、项目资料和企业格式要求为准。",
                "客户需在生成正式稿前补齐资料清单中的必要资料。",
                "系统生成内容需经过人工复核后再用于正式投标。",
            ],
            "pending_materials": pending_material_names,
            "exclusions": exclusions,
        },
        "acceptance": acceptance,
        "estimate": estimate,
    }
    confirmation["customer_message"] = render_order_confirmation_message(confirmation)
    confirmation["markdown"] = render_order_confirmation_markdown(confirmation)
    if own_conn:
        conn.close()
    return confirmation


def render_order_confirmation_message(report: dict[str, Any]) -> str:
    project = report.get("project", {})
    customer = report.get("customer", {})
    commercial = report.get("commercial", {})
    scope = report.get("scope", {})
    pending = scope.get("pending_materials") or []
    pending_text = "、".join(pending) if pending else "暂无必要资料缺口"
    deliverable_text = "、".join(scope.get("deliverables") or [])
    exclusions = "；".join(scope.get("exclusions") or [])
    return "\n".join(
        [
            f"{customer.get('name') or '您好'}，下面是 {project.get('name') or '本项目'} 技术标编制的订单确认内容：",
            f"1. 交付内容：{deliverable_text}。",
            f"2. 费用/预算：{commercial.get('agreed_price') or '待确认'}。",
            f"3. 交付时间：{commercial.get('deadline') or '待确认'}。",
            f"4. 修改范围：包含 {commercial.get('revision_rounds') or '2'} 轮基于原招标范围内的合理修改。",
            f"5. 资料前提：{pending_text}；如后续招标文件或范围变化较大，需要重新确认工期和费用。",
            f"6. 边界说明：{exclusions}。",
            "确认以上范围后，我再按这个口径进入正式生产。",
        ]
    )


def render_order_confirmation_markdown(report: dict[str, Any]) -> str:
    project = report.get("project", {})
    customer = report.get("customer", {})
    commercial = report.get("commercial", {})
    scope = report.get("scope", {})
    lines = [
        "# 订单确认单",
        "",
        f"- 项目名称：{project.get('name') or ''}",
        f"- 客户名称：{customer.get('name') or ''}",
        f"- 来源平台：{customer.get('source_platform') or ''}",
        f"- 订单号：{customer.get('order_no') or ''}",
        f"- 费用/预算：{commercial.get('agreed_price') or ''}",
        f"- 交付期限：{commercial.get('deadline') or ''}",
        f"- 交付格式：{commercial.get('deliverable_format') or ''}",
        f"- 修改轮次：{commercial.get('revision_rounds') or ''}",
        "",
        "## 交付范围",
    ]
    for item in scope.get("deliverables", []):
        lines.append(f"- {item}")
    lines.extend(["", "## 资料前提"])
    for item in scope.get("preconditions", []):
        lines.append(f"- {item}")
    pending = scope.get("pending_materials") or []
    if pending:
        lines.append("")
        lines.append("## 待补资料")
        for item in pending:
            lines.append(f"- {item}")
    lines.extend(["", "## 不包含范围"])
    for item in scope.get("exclusions", []):
        lines.append(f"- {item}")
    lines.extend(["", "## 客户确认话术", "", report.get("customer_message") or ""])
    return "\n".join(lines).strip() + "\n"
