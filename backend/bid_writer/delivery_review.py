from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect
from .feedback import feedback_summary
from .materials import material_summary
from .payments import payment_summary
from .production_tasks import TASK_FIELD_LABELS, get_production_task, missing_task_fields
from .project_profiles import get_project_profile
from .workflow import PROFILE_REQUIRED_FIELDS, build_workflow_status


PROFILE_FIELD_LABELS = {
    "project_name": "项目名称",
    "project_type": "项目类型",
    "structure_type": "结构形式",
    "building_area": "建设规模",
    "duration_days": "工期天数",
    "quality_target": "质量目标",
    "safety_target": "安全目标",
}


def _check_item(key: str, title: str, status: str, detail: str, action: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "action": action,
    }


def _blocker(severity: str, title: str, detail: str) -> dict[str, str]:
    return {"severity": severity, "title": title, "detail": detail}


def _status_label(status: str) -> str:
    return {
        "ready": "可进入交付终审",
        "needs_review": "需要人工复核",
        "needs_work": "需要继续补齐",
        "not_ready": "尚未具备交付条件",
    }.get(status, status)


def _check_status_label(status: str) -> str:
    return {
        "complete": "已完成",
        "warning": "需关注",
        "pending": "待处理",
    }.get(status, status)


def _percent(value: Any) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "0%"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def build_delivery_review(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    coverage = build_coverage_report(tender_id, conn=conn)
    workflow = build_workflow_status(tender_id, conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    materials = material_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)

    coverage_summary = coverage.get("summary", {})
    workflow_summary = workflow.get("summary", {})
    sections = coverage.get("sections", [])
    findings = coverage.get("findings", [])
    requirements = coverage.get("requirements", [])

    missing_profile_fields = [
        field for field in PROFILE_REQUIRED_FIELDS if profile.get(field) in ("", None)
    ]
    missing_task = missing_task_fields(task)
    missing_task_labels = [TASK_FIELD_LABELS.get(field, field) for field in missing_task]
    missing_profile_labels = [PROFILE_FIELD_LABELS.get(field, field) for field in missing_profile_fields]
    generated_sections = int(coverage_summary.get("generated_sections") or 0)
    total_sections = int(coverage_summary.get("total_sections") or 0)
    missing_sections = int(coverage_summary.get("missing_sections") or 0)
    total_requirements = int(coverage_summary.get("total_requirements") or 0)
    high_priority_missing = int(coverage_summary.get("high_priority_missing") or 0)
    delivery_count = int(
        conn.execute("SELECT COUNT(*) FROM delivery_records WHERE tender_id = ?", (tender_id,)).fetchone()[0]
    )
    delivered_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM delivery_records WHERE tender_id = ? AND status = ?",
            (tender_id, "已交付"),
        ).fetchone()[0]
    )
    citation_missing_sections = sum(
        1 for item in sections if item.get("draft_id") and int(item.get("citations_count") or 0) == 0
    )
    high_findings = sum(1 for item in findings if item.get("severity") == "high")
    export_ready = bool(workflow_summary.get("export_ready"))

    if not total_requirements:
        readiness = "not_ready"
    elif missing_task or missing_profile_fields or missing_sections or high_priority_missing or feedback.get("open") or materials["pending_required"]:
        readiness = "needs_work"
    elif payment.get("requires_payment_confirmation") or high_findings or citation_missing_sections:
        readiness = "needs_review"
    elif export_ready:
        readiness = "ready"
    else:
        readiness = "needs_review"

    checklist = [
        _check_item(
            "production_task",
            "生产任务登记",
            "complete" if not missing_task else ("warning" if task.get("customer_name") or task.get("deadline") else "pending"),
            "客户、期限和交付格式已登记" if not missing_task else f"缺少 {len(missing_task)} 项：{', '.join(missing_task_labels)}",
            "补充客户名称、交付期限和交付格式" if missing_task else "",
        ),
        _check_item(
            "materials",
            "客户资料清单",
            "complete" if not materials["pending_required"] else "warning",
            f"必要资料 {materials['required_completed']}/{materials['required']}，待补 {materials['pending_required']} 项",
            "补齐资料清单中的必要资料" if materials["pending_required"] else "",
        ),
        _check_item(
            "project_profile",
            "项目资料收集",
            "complete" if not missing_profile_fields else ("warning" if profile.get("project_name") else "pending"),
            "关键项目资料已补齐" if not missing_profile_fields else f"缺少 {len(missing_profile_fields)} 项：{', '.join(missing_profile_labels)}",
            "补齐项目类型、结构、规模、工期、质量和安全目标" if missing_profile_fields else "",
        ),
        _check_item(
            "requirements",
            "招标要求解析",
            "complete" if total_requirements else "pending",
            f"已形成 {total_requirements} 条响应要求" if total_requirements else "尚未形成响应矩阵",
            "上传或粘贴招标文件后执行解析" if not total_requirements else "",
        ),
        _check_item(
            "section_plan",
            "技术标目录规划",
            "complete" if total_sections else "pending",
            f"已规划 {total_sections} 个章节" if total_sections else "尚未生成技术标目录",
            "根据招标要求生成目录规划" if not total_sections else "",
        ),
        _check_item(
            "draft_generation",
            "章节初稿生成",
            "complete" if total_sections and missing_sections == 0 else ("warning" if generated_sections else "pending"),
            f"已生成 {generated_sections}/{total_sections} 个规划章节" if total_sections else "等待目录规划",
            "批量生成未完成章节" if missing_sections else "",
        ),
        _check_item(
            "coverage_review",
            "条款覆盖审查",
            "complete" if total_requirements and high_priority_missing == 0 else ("warning" if total_requirements else "pending"),
            f"高优先级缺口 {high_priority_missing} 条，审查问题 {coverage_summary.get('review_findings', 0)} 个",
            "优先处理高优先级条款缺口" if high_priority_missing else "",
        ),
        _check_item(
            "citations",
            "来源追溯",
            "complete" if generated_sections and citation_missing_sections == 0 else ("warning" if generated_sections else "pending"),
            f"{citation_missing_sections} 个已生成章节缺少来源引用" if citation_missing_sections else "已生成章节均保留来源引用",
            "重新检索参考片段或人工补充来源说明" if citation_missing_sections else "",
        ),
        _check_item(
            "manual_confirmation",
            "人工终审确认",
            "warning",
            "正式投标前仍需人工核对项目参数、专用条款、格式和页码",
            "按招标文件逐条复核后再盖章提交",
        ),
        _check_item(
            "payment_confirmation",
            "收款确认",
            "complete" if not payment.get("requires_payment_confirmation") else ("warning" if payment.get("received_amount") else "pending"),
            f"订单金额 {payment.get('expected_amount', 0)} 元，已确认 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
            "交付正式文件前人工确认收款、定金或客户约定。" if payment.get("requires_payment_confirmation") else "",
        ),
        _check_item(
            "export_package",
            "交付包导出",
            "complete" if export_ready else "pending",
            "已具备导出 Word/Markdown/ZIP 交付包条件" if export_ready else "需先完成目录章节和高优先级条款响应",
            "导出交付包并保存审查报告" if export_ready else "",
        ),
        _check_item(
            "delivery_archive",
            "交付记录归档",
            "complete" if delivered_count else ("warning" if delivery_count else "pending"),
            f"已交付 {delivered_count} 次，交付记录 {delivery_count} 条"
            if delivery_count
            else "尚未形成交付记录",
            "确认客户接收后标记为已交付" if delivery_count and not delivered_count else "",
        ),
        _check_item(
            "feedback",
            "客户反馈返工",
            "complete" if feedback["total"] and not feedback["open"] else ("warning" if feedback["open"] else "pending"),
            f"反馈 {feedback['total']} 条，未处理 {feedback['open']} 条"
            if feedback["total"]
            else "暂无客户反馈或返工记录",
            "处理客户反馈并标记为已解决" if feedback["open"] else "",
        ),
    ]

    blockers: list[dict[str, str]] = []
    if missing_task:
        blockers.append(_blocker("medium", "生产任务未登记完整", f"缺少：{', '.join(missing_task_labels)}"))
    if materials["pending_required"]:
        names = "、".join(str(item.get("name") or "") for item in materials["pending_required_items"][:8])
        blockers.append(_blocker("medium", "必要资料未补齐", f"待补：{names}"))
    if missing_profile_fields:
        blockers.append(_blocker("medium", "项目资料未补齐", f"缺少：{', '.join(missing_profile_labels)}"))
    if not total_requirements:
        blockers.append(_blocker("high", "未解析招标要求", "系统尚未形成评分点、技术要求和响应矩阵。"))
    if not total_sections:
        blockers.append(_blocker("high", "未生成技术标目录", "还没有可用于批量生成章节的目录规划。"))
    if missing_sections:
        blockers.append(_blocker("high", "存在未生成章节", f"仍有 {missing_sections} 个目录章节没有初稿。"))
    if high_priority_missing:
        blockers.append(_blocker("high", "高优先级条款未响应", f"仍有 {high_priority_missing} 条高优先级要求未形成草稿响应。"))
    if high_findings:
        blockers.append(_blocker("high", "审查发现高风险问题", f"审查发现 {high_findings} 个高风险问题，需要先处理。"))
    if citation_missing_sections:
        blockers.append(_blocker("medium", "来源引用缺失", f"{citation_missing_sections} 个章节缺少历史来源引用。"))
    if feedback.get("open"):
        blockers.append(_blocker("medium", "客户反馈未处理", f"仍有 {feedback['open']} 条客户反馈或返工事项未解决。"))
    if payment.get("requires_payment_confirmation"):
        blockers.append(
            _blocker(
                "medium",
                "收款状态未确认",
                f"订单金额 {payment.get('expected_amount', 0)} 元，已确认收款 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
            )
        )

    recommendations = list(coverage.get("recommendations", []))
    next_action = (workflow.get("next_step") or {}).get("action")
    if next_action:
        recommendations.append(f"下一步：{next_action}")
    if high_findings:
        recommendations.append("先处理高风险审查问题，再导出正式稿。")
    if citation_missing_sections:
        recommendations.append("对缺少引用的章节重新检索历史素材，确保内容可追溯。")
    if readiness == "ready":
        recommendations.append("可以导出交付包，并进入人工终审、格式整理和盖章前检查。")
    if payment.get("requires_payment_confirmation"):
        recommendations.append("发送正式交付文件前，请人工确认收款、定金或客户约定，避免先发货后回款风险。")
    recommendations = _dedupe(recommendations)

    summary = {
        "readiness": readiness,
        "readiness_label": _status_label(readiness),
        "export_ready": export_ready,
        "total_requirements": total_requirements,
        "draft_coverage_rate": coverage_summary.get("draft_coverage_rate", 0),
        "total_sections": total_sections,
        "generated_sections": generated_sections,
        "missing_sections": missing_sections,
        "high_priority_missing": high_priority_missing,
        "review_findings": int(coverage_summary.get("review_findings") or 0),
        "high_findings": high_findings,
        "citation_missing_sections": citation_missing_sections,
        "task_missing": missing_task,
        "task_missing_labels": missing_task_labels,
        "profile_missing": missing_profile_fields,
        "profile_missing_labels": missing_profile_labels,
        "delivery_records": delivery_count,
        "delivered_records": delivered_count,
        "feedback_open": feedback.get("open", 0),
        "materials_pending_required": materials["pending_required"],
        "payment_status": payment.get("status"),
        "payment_status_label": payment.get("status_label"),
        "payment_received_amount": payment.get("received_amount", 0),
        "payment_outstanding_amount": payment.get("outstanding_amount", 0),
        "blockers_count": len(blockers),
    }

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": coverage.get("tender", {}),
        "summary": summary,
        "task": task,
        "checklist": checklist,
        "blockers": blockers,
        "recommendations": recommendations,
        "coverage": coverage,
        "workflow": workflow,
        "feedback": feedback,
        "materials": materials,
        "payment": payment,
    }
    report["markdown"] = render_delivery_review_markdown(report)
    if own_conn:
        conn.close()
    return report


def render_delivery_review_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender", {})
    summary = report.get("summary", {})
    checklist = report.get("checklist", [])
    blockers = report.get("blockers", [])
    recommendations = report.get("recommendations", [])

    lines = [
        "# 交付审查报告",
        "",
        f"- 项目名称：{tender.get('name', '')}",
        f"- 项目 ID：{tender.get('id', '')}",
        f"- 生成时间：{report.get('generated_at', '')}",
        f"- 审查结论：{summary.get('readiness_label', '')}",
        f"- 条款草稿覆盖率：{_percent(summary.get('draft_coverage_rate'))}",
        f"- 目录章节完成度：{summary.get('generated_sections', 0)}/{summary.get('total_sections', 0)}",
        f"- 高优先级缺口：{summary.get('high_priority_missing', 0)}",
        f"- 审查问题：{summary.get('review_findings', 0)}",
        f"- 收款状态：{summary.get('payment_status_label', '未登记')}，已收 {summary.get('payment_received_amount', 0)} 元，未收 {summary.get('payment_outstanding_amount', 0)} 元",
        "",
        "## 交付检查清单",
    ]
    for item in checklist:
        marker = "x" if item.get("status") == "complete" else " "
        status = _check_status_label(str(item.get("status") or ""))
        detail = item.get("detail") or ""
        action = item.get("action") or ""
        line = f"- [{marker}] {item.get('title', '')}（{status}）：{detail}"
        if action:
            line += f"；建议：{action}"
        lines.append(line)

    lines.extend(["", "## 主要阻碍"])
    if blockers:
        for item in blockers:
            lines.append(f"- [{item.get('severity')}] {item.get('title')}：{item.get('detail')}")
    else:
        lines.append("- 暂无阻碍项，可进入人工终审。")

    lines.extend(["", "## 处理建议"])
    if recommendations:
        for item in recommendations:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无额外建议。")

    return "\n".join(lines).strip() + "\n"
