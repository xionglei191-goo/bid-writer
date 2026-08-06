from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .enterprise_profiles import get_enterprise_profile
from .materials import material_summary
from .payments import payment_summary
from .production_tasks import get_production_task
from .project_profiles import get_project_profile
from .quality_gate import build_quality_gate
from .workflow import build_workflow_status


def _count(conn: sqlite3.Connection, table: str, tender_id: int, extra_where: str = "", params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE tender_id = ? {extra_where}",
        (tender_id, *params),
    ).fetchone()
    return int(row[0] or 0)


def _latest_row(conn: sqlite3.Connection, table: str, tender_id: int, order_by: str = "created_at DESC, id DESC") -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            f"""
            SELECT *
            FROM {table}
            WHERE tender_id = ?
            ORDER BY {order_by}
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    ) or {}


def _communication_summary(conn: sqlite3.Connection, tender_id: int) -> dict[str, Any]:
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT status, stage, COUNT(*) AS count
            FROM customer_communications
            WHERE tender_id = ?
            GROUP BY status, stage
            ORDER BY count DESC, stage
            """,
            (tender_id,),
        ).fetchall()
    )
    total = _count(conn, "customer_communications", tender_id)
    pending = _count(conn, "customer_communications", tender_id, "AND status IN (?, ?)", ("待发送", "需跟进"))
    latest = _latest_row(conn, "customer_communications", tender_id)
    return {
        "total": total,
        "pending": pending,
        "latest": latest,
        "by_status_stage": rows,
    }


def _risk(level: str, title: str, detail: str, action: str) -> dict[str, str]:
    return {"level": level, "title": title, "detail": detail, "action": action}


def _action(title: str, detail: str, target: str) -> dict[str, str]:
    return {"title": title, "detail": detail, "target": target}


def _readiness_label(workflow: dict[str, Any], quality: dict[str, Any], communications: dict[str, Any]) -> str:
    summary = workflow.get("summary", {})
    if summary.get("feedback", {}).get("open"):
        return "返工处理中"
    if summary.get("closure_records"):
        return "已结案归档"
    if summary.get("delivered_records"):
        return "已交付待结案"
    if quality.get("status") == "pass" and summary.get("export_ready"):
        return "可进入交付终审"
    if communications.get("pending"):
        return "沟通待跟进"
    next_key = str((workflow.get("next_step") or {}).get("key") or "")
    return {
        "task": "待补生产信息",
        "materials": "待补客户资料",
        "profile": "待补项目资料",
        "parse": "待解析招标文件",
        "plan": "待生成目录",
        "drafts": "章节生产中",
        "review": "待处理审查问题",
        "export": "待导出交付包",
        "delivery": "待客户确认交付",
        "feedback": "返工处理中",
        "closure": "待结案确认",
        "retrospective": "待项目复盘",
    }.get(next_key, "生产跟进中")


def build_project_overview(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    enterprise = get_enterprise_profile(conn=conn)
    materials = material_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)
    workflow = build_workflow_status(tender_id, conn=conn)
    quality = build_quality_gate(tender_id, conn=conn)
    communications = _communication_summary(conn, tender_id)
    summary = workflow.get("summary", {})
    quality_summary = quality.get("summary", {})
    latest_delivery = summary.get("latest_delivery") or {}

    risks: list[dict[str, str]] = []
    task_missing = summary.get("task_missing") or []
    if task_missing:
        risks.append(_risk("medium", "生产任务缺项", f"仍缺 {len(task_missing)} 项生产任务信息。", "补齐客户名称、交付期限和交付格式。"))
    if materials.get("pending_required"):
        names = "、".join(str(item.get("name") or "") for item in materials.get("pending_required_items", [])[:5])
        risks.append(_risk("medium", "必要资料待补", f"仍有 {materials['pending_required']} 项必要资料待补：{names}。", "在资料清单中更新资料状态，或生成资料催补话术。"))
    if not summary.get("requirements"):
        risks.append(_risk("high", "尚未解析招标要求", "项目还没有形成响应矩阵。", "补充完整招标文本或上传招标文件后解析。"))
    enterprise_missing = [
        label
        for field, label in (
            ("bidder_name", "投标单位"),
            ("qualification_summary", "资质能力"),
            ("key_personnel", "拟投入人员"),
            ("equipment_resources", "机械设备与资源"),
        )
        if not str(enterprise.get(field) or "").strip()
    ]
    if enterprise_missing:
        risks.append(
            _risk(
                "medium",
                "投标单位资料待补",
                f"仍缺 {len(enterprise_missing)} 项核心企业资料：{'、'.join(enterprise_missing)}。",
                "在投标单位资料中补齐固定能力信息，生成和导出时会自动引用。",
            )
        )
    if summary.get("missing_plans"):
        risks.append(_risk("high", "目录章节未生成完", f"仍有 {summary.get('missing_plans')} 个规划章节没有草稿。", "执行批量生成或逐章生成未完成章节。"))
    if int(quality_summary.get("high") or 0):
        risks.append(_risk("high", "存在高风险修订任务", f"质量门禁发现 {quality_summary.get('high')} 条高风险任务。", "优先处理质量门禁中的高风险任务。"))
    if communications.get("pending"):
        risks.append(_risk("low", "客户沟通待跟进", f"仍有 {communications['pending']} 条沟通记录处于待发送或需跟进。", "复制话术并人工发送后更新沟通状态。"))
    feedback = summary.get("feedback") or {}
    if feedback.get("open"):
        risks.append(_risk("high", "客户反馈未解决", f"仍有 {feedback.get('open')} 条反馈未处理。", "处理返工反馈并标记为已解决。"))
    if payment.get("requires_payment_confirmation"):
        risks.append(
            _risk(
                "medium",
                "收款状态待确认",
                f"订单金额 {payment.get('expected_amount', 0)} 元，已确认 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
                "发出正式交付文件前人工确认收款、定金或客户约定。",
            )
        )
    if not risks:
        risks.append(_risk("low", "暂无阻碍项", "自动检查未发现当前阶段的关键阻碍。", "继续按下一步动作推进，并保留人工终审。"))

    next_step = workflow.get("next_step") or {}
    actions = [
        _action(str(next_step.get("title") or "检查项目状态"), str(next_step.get("action") or next_step.get("detail") or ""), "workflow")
    ]
    if materials.get("pending_required"):
        actions.append(_action("生成资料催补话术", "向客户确认完整招标文件、评分办法、项目基础资料和目标要求。", "communications"))
    if enterprise_missing:
        actions.append(_action("补齐投标单位资料", "维护投标单位、资质能力、拟投入人员和机械设备资源，避免生成时缺少企业能力依据。", "enterprise"))
    if int(quality_summary.get("task_count") or 0):
        top_task = (quality.get("revision_tasks") or [{}])[0]
        actions.append(_action("处理质量门禁任务", str(top_task.get("action") or "按质量门禁清单逐项修订。"), "quality"))
    if summary.get("export_ready") and not latest_delivery:
        actions.append(_action("导出交付包", "生成 DOCX、Markdown 和 ZIP 归档包，随后做人工终审。", "export"))
    if communications.get("pending"):
        actions.append(_action("更新沟通状态", "客户回复已发送或客户已确认后，更新沟通记录状态。", "communications"))
    if payment.get("requires_payment_confirmation"):
        actions.append(_action("确认收款状态", "记录客户付款、定金或尾款确认情况，再进入正式发货。", "payments"))

    overview = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": {
            "id": tender["id"],
            "name": tender["name"],
            "industry": tender.get("industry") or "",
            "region": tender.get("region") or "",
        },
        "task": {
            "customer_name": task.get("customer_name") or "",
            "source_platform": task.get("source_platform") or "",
            "order_no": task.get("order_no") or "",
            "deadline": task.get("deadline") or "",
            "budget": task.get("budget") or "",
            "delivery_status": task.get("delivery_status") or "",
            "internal_owner": task.get("internal_owner") or "",
        },
        "profile": {
            "project_name": profile.get("project_name") or tender["name"],
            "project_type": profile.get("project_type") or "",
            "structure_type": profile.get("structure_type") or "",
            "building_area": profile.get("building_area") or "",
            "duration_days": profile.get("duration_days") or "",
        },
        "metrics": {
            "requirements": summary.get("requirements", 0),
            "plans": summary.get("plans", 0),
            "generated_plans": summary.get("generated_plans", 0),
            "drafts": summary.get("drafts", 0),
            "draft_coverage_rate": summary.get("draft_coverage_rate", 0),
            "quality_score": quality.get("score", 0),
            "quality_status": quality.get("status_label", ""),
            "materials_required": materials.get("required", 0),
            "materials_ready": materials.get("required_completed", 0),
            "communications": communications.get("total", 0),
            "communications_pending": communications.get("pending", 0),
            "payment_received_amount": payment.get("received_amount", 0),
            "payment_outstanding_amount": payment.get("outstanding_amount", 0),
            "payment_status_label": payment.get("status_label", ""),
            "delivery_records": summary.get("delivery_records", 0),
            "feedback_open": feedback.get("open", 0),
            "closure_records": summary.get("closure_records", 0),
        },
        "readiness": {
            "label": _readiness_label(workflow, quality, communications),
            "export_ready": bool(summary.get("export_ready")),
            "quality_status": quality.get("status", ""),
            "workflow_next_key": next_step.get("key") or "",
        },
        "risks": risks,
        "next_actions": actions[:6],
        "communications": communications,
        "workflow": {
            "next_step": next_step,
            "steps": workflow.get("steps", []),
        },
        "quality": {
            "status": quality.get("status", ""),
            "status_label": quality.get("status_label", ""),
            "score": quality.get("score", 0),
            "summary": quality_summary,
            "top_revision_tasks": (quality.get("revision_tasks") or [])[:8],
        },
        "materials": materials,
        "payment": payment,
    }
    overview["markdown"] = render_project_overview_markdown(overview)
    if own_conn:
        conn.close()
    return overview


def render_project_overview_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender", {})
    task = report.get("task", {})
    metrics = report.get("metrics", {})
    lines = [
        "# 项目总览",
        "",
        f"- 项目名称：{tender.get('name') or ''}",
        f"- 项目 ID：{tender.get('id') or ''}",
        f"- 客户：{task.get('customer_name') or '未登记'}",
        f"- 来源平台：{task.get('source_platform') or '未登记'}",
        f"- 交付期限：{task.get('deadline') or '未登记'}",
        f"- 当前判断：{(report.get('readiness') or {}).get('label') or ''}",
        "",
        "## 关键指标",
        "",
        f"- 响应条款：{metrics.get('requirements', 0)}",
        f"- 章节进度：{metrics.get('generated_plans', 0)}/{metrics.get('plans', 0)}",
        f"- 草稿数量：{metrics.get('drafts', 0)}",
        f"- 质量分：{metrics.get('quality_score', 0)}（{metrics.get('quality_status', '')}）",
        f"- 必要资料：{metrics.get('materials_ready', 0)}/{metrics.get('materials_required', 0)}",
        f"- 沟通记录：{metrics.get('communications', 0)}，待跟进 {metrics.get('communications_pending', 0)}",
        f"- 收款状态：{metrics.get('payment_status_label', '未登记')}，已收 {metrics.get('payment_received_amount', 0)} 元，未收 {metrics.get('payment_outstanding_amount', 0)} 元",
        f"- 未处理反馈：{metrics.get('feedback_open', 0)}",
        "",
        "## 主要风险",
    ]
    for item in report.get("risks", []):
        lines.append(f"- [{item.get('level')}] {item.get('title')}：{item.get('detail')}；建议：{item.get('action')}")
    lines.extend(["", "## 下一步动作"])
    for item in report.get("next_actions", []):
        lines.append(f"- {item.get('title')}：{item.get('detail')}")
    return "\n".join(lines).strip() + "\n"
