from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect, row_to_dict
from .delivery_review import build_delivery_review
from .materials import material_summary
from .package_validation import validate_latest_package, validate_package_path
from .payments import payment_summary
from .production_tasks import TASK_FIELD_LABELS, get_production_task, missing_task_fields
from .project_profiles import get_project_profile
from .quality_gate import build_quality_gate
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


def _count(conn: sqlite3.Connection, table: str, tender_id: int) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _check(
    key: str,
    title: str,
    status: str,
    detail: str,
    action: str = "",
    severity: str = "medium",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "action": action,
        "severity": severity if status in {"blocked", "warning", "pending"} else "info",
    }


def _phase(key: str, title: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [item for item in checks if item.get("status") == "blocked"]
    pending = [item for item in checks if item.get("status") == "pending"]
    warnings = [item for item in checks if item.get("status") == "warning"]
    readiness = "blocked" if blockers else ("needs_work" if pending or warnings else "ready")
    labels = {
        "intake": {"ready": "可接单", "needs_work": "谨慎接单", "blocked": "暂缓接单"},
        "production": {"ready": "可开工", "needs_work": "需补齐后开工", "blocked": "暂缓生产"},
        "delivery": {"ready": "可交付", "needs_work": "需人工复核", "blocked": "暂不交付"},
    }
    return {
        "key": key,
        "title": title,
        "readiness": readiness,
        "decision": labels.get(key, {}).get(readiness, readiness),
        "checks": checks,
        "blockers": blockers,
        "warnings": [*pending, *warnings],
    }


def _score(phases: list[dict[str, Any]]) -> int:
    penalty = 0
    for phase in phases:
        for item in phase.get("checks") or []:
            status = item.get("status")
            severity = item.get("severity")
            if status == "blocked":
                penalty += {"high": 22, "medium": 15, "low": 8}.get(severity, 12)
            elif status == "pending":
                penalty += {"high": 14, "medium": 9, "low": 4}.get(severity, 7)
            elif status == "warning":
                penalty += {"high": 10, "medium": 6, "low": 3}.get(severity, 5)
    return max(0, 100 - penalty)


def _overall(phases: list[dict[str, Any]]) -> tuple[str, str]:
    phase_by_key = {phase["key"]: phase for phase in phases}
    delivery = phase_by_key.get("delivery", {})
    production = phase_by_key.get("production", {})
    intake = phase_by_key.get("intake", {})
    if delivery.get("readiness") == "ready":
        return "ready_to_deliver", "可承诺交付"
    if delivery.get("readiness") == "needs_work" and production.get("readiness") == "ready":
        return "ready_for_final_review", "可进入终审"
    if production.get("readiness") == "ready":
        return "ready_to_produce", "可开始生产"
    if intake.get("readiness") == "blocked" or production.get("readiness") == "blocked":
        return "blocked", "暂缓承接"
    return "needs_information", "需补充信息"


def _labels(fields: list[str], labels: dict[str, str]) -> list[str]:
    return [labels.get(field, field) for field in fields]


def _final_document_status(conn: sqlite3.Connection, tender_id: int) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM final_documents
            WHERE tender_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    ) or {}


def build_production_readiness(
    tender_id: int,
    package_path: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    materials = material_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)
    workflow = build_workflow_status(tender_id, conn=conn)
    coverage = build_coverage_report(tender_id, conn=conn)
    quality = build_quality_gate(tender_id, conn=conn)
    delivery = build_delivery_review(tender_id, conn=conn)
    if package_path:
        package = validate_package_path(package_path, tender_id=tender_id, include_readiness=False)
    else:
        package = validate_latest_package(tender_id, conn=conn)
    final_document = _final_document_status(conn, tender_id)

    raw_text = str(tender.get("raw_text") or "").strip()
    has_source = bool(raw_text or tender.get("file_path"))
    task_missing = missing_task_fields(task)
    profile_missing = [field for field in PROFILE_REQUIRED_FIELDS if profile.get(field) in ("", None)]
    coverage_summary = coverage.get("summary", {})
    quality_summary = quality.get("summary", {})
    delivery_summary = delivery.get("summary", {})
    package_summary = package.get("summary", {})
    requirement_count = int(coverage_summary.get("total_requirements") or _count(conn, "requirements", tender_id))
    total_sections = int(coverage_summary.get("total_sections") or _count(conn, "section_plans", tender_id))
    generated_sections = int(coverage_summary.get("generated_sections") or 0)
    missing_sections = int(coverage_summary.get("missing_sections") or max(0, total_sections - generated_sections))
    high_priority_missing = int(coverage_summary.get("high_priority_missing") or 0)
    high_quality_tasks = int(quality_summary.get("high") or 0)

    intake_checks = [
        _check(
            "source",
            "招标资料来源",
            "complete" if has_source else "blocked",
            "已具备招标文本或上传文件。" if has_source else "尚未录入招标文件或客户需求文本。",
            "先粘贴客户原始消息，或上传招标文件后再评估接单。",
            "high",
        ),
        _check(
            "customer",
            "客户与期限",
            "complete" if task.get("customer_name") and task.get("deadline") else "warning",
            "客户和交付期限已登记。"
            if task.get("customer_name") and task.get("deadline")
            else "客户名称或交付期限尚未完整登记。",
            "补充客户名称、来源平台和交付期限，避免急单边界不清。",
            "medium",
        ),
        _check(
            "price",
            "价格与交付范围",
            "complete" if task.get("budget") and task.get("deliverable_format") else "warning",
            "预算和交付格式已登记。"
            if task.get("budget") and task.get("deliverable_format")
            else "预算或交付格式尚未明确。",
            "先生成报价测算和订单确认单，再向客户承诺范围。",
            "medium",
        ),
    ]

    production_checks = [
        _check(
            "requirements",
            "招标要求解析",
            "complete" if requirement_count else "blocked",
            f"已形成 {requirement_count} 条响应要求。" if requirement_count else "尚未形成响应矩阵。",
            "解析招标文件，或先人工补充评分点、技术要求和废标风险。",
            "high",
        ),
        _check(
            "materials",
            "必要资料",
            "complete" if materials.get("pending_required") == 0 else "blocked",
            f"必要资料完成 {materials.get('required_completed')}/{materials.get('required')}，待补 {materials.get('pending_required')} 项。",
            "在资料清单中补齐完整招标文件、评分办法、项目基础资料和目标要求。",
            "high",
        ),
        _check(
            "profile",
            "项目参数",
            "complete" if not profile_missing else "warning",
            "项目类型、规模、工期、质量安全目标已登记。"
            if not profile_missing
            else f"仍缺少 {len(profile_missing)} 项：{'、'.join(_labels(profile_missing, PROFILE_FIELD_LABELS))}。",
            "补齐项目资料，章节生成会使用这些信息做项目化改写。",
            "medium",
        ),
        _check(
            "plan",
            "技术标目录",
            "complete" if total_sections else ("pending" if requirement_count else "blocked"),
            f"已规划 {total_sections} 个章节。" if total_sections else "尚未生成技术标目录。",
            "生成目录规划并运行目录完整性审计。",
            "medium",
        ),
        _check(
            "payment_policy",
            "收款风险",
            "complete" if not payment.get("requires_payment_confirmation") else "warning",
            f"{payment.get('status_label')}，已收 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
            "内部可先生产，但交付前应确认定金或全款。",
            "low",
        ),
    ]

    delivery_checks = [
        _check(
            "drafts",
            "章节草稿",
            "complete" if total_sections and missing_sections == 0 else "blocked",
            f"已生成 {generated_sections}/{total_sections} 个规划章节。" if total_sections else "尚未形成目录和草稿。",
            "批量生成未完成章节，并人工补齐特殊章节。",
            "high",
        ),
        _check(
            "coverage",
            "高优先级条款响应",
            "complete" if high_priority_missing == 0 and requirement_count else "blocked",
            f"高优先级缺口 {high_priority_missing} 条，草稿覆盖率 {round(float(coverage_summary.get('draft_coverage_rate') or 0) * 100)}%。",
            "优先处理评分点、废标风险和高优先级技术要求。",
            "high",
        ),
        _check(
            "quality_gate",
            "质量门禁",
            "complete" if quality.get("status") == "pass" else ("blocked" if high_quality_tasks else "warning"),
            f"{quality.get('status_label')}，质量分 {quality.get('score', 0)}，高风险任务 {high_quality_tasks} 条。",
            "同步修订任务台账，处理高风险和中风险问题后再交付。",
            "high" if high_quality_tasks else "medium",
        ),
        _check(
            "final_document",
            "人工定稿确认",
            "complete" if final_document.get("status") == "approved" else "warning",
            f"成稿状态：{final_document.get('status') or '未确认'}。",
            "在整本成稿预览中确认项目名称、专用条款、格式和承诺边界。",
            "medium",
        ),
        _check(
            "payment",
            "交付收款",
            "complete" if not payment.get("requires_payment_confirmation") else "blocked",
            f"{payment.get('status_label')}，未收金额 {payment.get('outstanding_amount', 0)} 元。",
            "确认收款或在订单确认单中明确交付前置条件。",
            "high",
        ),
        _check(
            "package",
            "交付包",
            "complete" if package_summary.get("zip_readable") and package_summary.get("core_missing") == 0 else "blocked",
            f"交付包状态：{package_summary.get('present_files', 0)}/{package_summary.get('expected_files', 0)} 个文件齐全，核心缺失 {package_summary.get('core_missing', 0)} 项。",
            "导出 ZIP 交付包并执行交付包清单核验。",
            "high",
        ),
        _check(
            "delivery_review",
            "交付审查",
            "complete" if delivery_summary.get("readiness") == "ready" else ("blocked" if delivery_summary.get("readiness") in {"not_ready", "needs_work"} else "warning"),
            f"交付审查结论：{delivery_summary.get('readiness_label') or delivery_summary.get('readiness') or '待检查'}。",
            "处理交付审查报告中的主要阻碍和提醒项。",
            "high",
        ),
    ]

    phases = [
        _phase("intake", "接单判断", intake_checks),
        _phase("production", "开工判断", production_checks),
        _phase("delivery", "交付判断", delivery_checks),
    ]
    readiness, decision = _overall(phases)
    blockers = [item for phase in phases for item in phase["blockers"]]
    warnings = [item for phase in phases for item in phase["warnings"]]
    next_actions = [item["action"] for item in [*blockers, *warnings] if item.get("action")]
    if not next_actions:
        next_actions = ["可进入人工终审和客户交付确认。"]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "summary": {
            "readiness": readiness,
            "decision": decision,
            "score": _score(phases),
            "blockers": len(blockers),
            "warnings": len(warnings),
            "requirements": requirement_count,
            "total_sections": total_sections,
            "generated_sections": generated_sections,
            "missing_sections": missing_sections,
            "high_priority_missing": high_priority_missing,
            "quality_status": quality.get("status"),
            "quality_score": quality.get("score", 0),
            "payment_status": payment.get("status"),
            "payment_status_label": payment.get("status_label"),
            "package_readiness": package_summary.get("readiness"),
            "workflow_next_step": (workflow.get("next_step") or {}).get("title", ""),
        },
        "phases": phases,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": list(dict.fromkeys(next_actions))[:12],
        "snapshots": {
            "materials": materials,
            "payment": payment,
            "workflow": workflow.get("summary", {}),
            "coverage": coverage_summary,
            "quality": quality_summary,
            "delivery": delivery_summary,
            "package": package_summary,
            "package_path": str(Path(package_path)) if package_path else str((package.get("package") or {}).get("path") or ""),
        },
    }
    report["markdown"] = render_production_readiness_markdown(report)
    if own_conn:
        conn.close()
    return report


def _status_label(status: str) -> str:
    return {
        "complete": "已完成",
        "warning": "需关注",
        "pending": "待处理",
        "blocked": "阻断",
    }.get(status, status)


def render_production_readiness_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 项目可交付性评估",
        "",
        "## 基本结论",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        f"- 评估时间：{report.get('generated_at') or ''}",
        f"- 综合判断：{summary.get('decision') or ''}",
        f"- 评估分：{summary.get('score', 0)}",
        f"- 阻断项：{summary.get('blockers', 0)}",
        f"- 提醒项：{summary.get('warnings', 0)}",
        "",
        "## 下一步动作",
    ]
    for action in report.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.extend(["", "## 阶段判断"])
    for phase in report.get("phases") or []:
        lines.extend(["", f"### {phase.get('title')}：{phase.get('decision')}"])
        for item in phase.get("checks") or []:
            lines.append(f"- [{_status_label(str(item.get('status') or ''))}] {item.get('title')}：{item.get('detail')}")
            if item.get("action") and item.get("status") != "complete":
                lines.append(f"  - 建议：{item.get('action')}")
    return "\n".join(lines).strip() + "\n"
