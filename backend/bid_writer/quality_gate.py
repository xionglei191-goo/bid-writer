from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect
from .draft_scope import active_drafts
from .enterprise_profiles import get_enterprise_profile
from .feedback import feedback_summary
from .materials import material_summary
from .payments import payment_summary
from .production_tasks import TASK_FIELD_LABELS, get_production_task, missing_task_fields
from .project_consistency import project_consistency_findings
from .project_profiles import get_project_profile
from .response_matrix import build_response_matrix
from .visual_assets import visual_review_summary
from .workflow import PROFILE_REQUIRED_FIELDS


PROFILE_FIELD_LABELS = {
    "project_name": "项目名称",
    "project_type": "项目类型",
    "structure_type": "结构形式",
    "building_area": "建设规模",
    "duration_days": "工期天数",
    "quality_target": "质量目标",
    "safety_target": "安全目标",
}

ENTERPRISE_REQUIRED_FIELDS = {
    "bidder_name": "投标单位",
    "qualification_summary": "资质能力",
    "key_personnel": "拟投入人员",
    "equipment_resources": "机械设备与资源",
}


def _task(
    severity: str,
    title: str,
    scope: str,
    detail: str,
    action: str,
    section_title: str = "",
    draft_id: int | None = None,
    requirement_id: int | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "scope": scope,
        "detail": detail,
        "action": action,
        "section_title": section_title,
        "draft_id": draft_id,
        "requirement_id": requirement_id,
        "status": "待处理",
    }


def _status_item(key: str, title: str, status: str, detail: str) -> dict[str, str]:
    return {"key": key, "title": title, "status": status, "detail": detail}


def _status_label(status: str) -> str:
    return {
        "pass": "可进入人工终审",
        "needs_review": "需要人工复核",
        "needs_fix": "需要修改后交付",
        "blocked": "暂不建议交付",
    }.get(status, status)


def _severity_score(severity: str) -> int:
    return {"high": 20, "medium": 5, "low": 2}.get(severity, 5)


def _quality_score(tasks: list[dict[str, Any]]) -> int:
    penalty = sum(_severity_score(str(item.get("severity") or "")) for item in tasks)
    return max(0, 100 - penalty)


def _draft_quality_tasks(conn: sqlite3.Connection, tender_id: int, profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows = active_drafts(conn, tender_id)
    tasks: list[dict[str, Any]] = []
    vague_terms = ("根据实际情况", "结合实际", "适时", "必要时", "相关要求")
    forbidden_promises = ("确保中标", "保证中标", "必中", "包中")
    for row in rows:
        content = str(row.get("content") or "")
        char_count = len(content)
        section_title = str(row.get("section_title") or "")
        draft_id = int(row["id"])
        minimum_chars = 3000 if "施工工艺" in section_title or "施工方法" in section_title else 1200
        if char_count < minimum_chars:
            tasks.append(
                _task(
                    "medium",
                    "章节内容偏短",
                    "章节草稿",
                    f"{section_title} 当前约 {char_count} 字，建议不少于 {minimum_chars} 字。",
                    "补充项目化措施、资源配置、工艺步骤、检查标准和风险控制。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        generation_mode = str(row.get("generation_mode") or "unknown")
        generation_error = str(row.get("generation_error") or "").strip()
        if generation_mode != "llm":
            tasks.append(
                _task(
                    "high",
                    "章节仍为本地保底稿",
                    "生成质量",
                    f"{section_title} 的生成方式为 {generation_mode}，尚未经过已配置大模型的项目化改写。",
                    "使用当前大模型重新生成本章，并重新执行来源审计和质量门禁。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        elif generation_error:
            tasks.append(
                _task(
                    "medium",
                    "大模型二次终审未完成",
                    "生成质量",
                    f"{section_title}：{generation_error}",
                    "重新生成本章，确认初稿和二次终审均成功完成。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        meta_hits = [term for term in ("生成策略", "参考来源摘要", "需人工确认") if term in content]
        if meta_hits:
            tasks.append(
                _task(
                    "medium",
                    "章节含生成过程文字",
                    "生成质量",
                    f"{section_title} 仍包含：{'、'.join(meta_hits)}。",
                    "删除生成过程说明，只保留可直接进入投标文件的正文。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        placeholder_count = content.count("【待确认：")
        if placeholder_count:
            tasks.append(
                _task(
                    "medium",
                    "章节存在待确认字段",
                    "项目资料",
                    f"{section_title} 有 {placeholder_count} 个待确认字段。",
                    "补齐对应招标或项目资料后重新生成，或由编制人员逐项确认替换。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        if "\\n" in content:
            tasks.append(
                _task(
                    "medium",
                    "章节存在转义换行残留",
                    "生成质量",
                    f"{section_title} 出现字面量 \\n，可能来自未清洗的历史素材。",
                    "重新生成或清理该段，恢复正常段落和表格结构。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        vague_hits = sum(content.count(term) for term in vague_terms)
        if vague_hits >= 5:
            tasks.append(
                _task(
                    "low",
                    "空泛表述较多",
                    "章节草稿",
                    f"{section_title} 中空泛词累计出现 {vague_hits} 次。",
                    "将空泛承诺改为可执行动作、责任岗位、检查频次和验收标准。",
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
        for term in forbidden_promises:
            if term in content:
                tasks.append(
                    _task(
                        "high",
                        "存在不当承诺",
                        "章节草稿",
                        f"{section_title} 出现“{term}”类表述。",
                        "删除中标结果承诺，仅保留编制质量、响应完整性和修改配合承诺。",
                        section_title=section_title,
                        draft_id=draft_id,
                    )
                )
        for finding in project_consistency_findings(profile, section_title, content):
            tasks.append(
                _task(
                    str(finding.get("severity") or "medium"),
                    str(finding.get("message") or "项目一致性不足"),
                    "项目一致性",
                    str(finding.get("detail") or ""),
                    str(finding.get("action") or "按项目资料补充章节内容。"),
                    section_title=section_title,
                    draft_id=draft_id,
                )
            )
    return tasks


def build_quality_gate(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    coverage = build_coverage_report(tender_id, conn=conn)
    response_matrix = build_response_matrix(tender_id, conn=conn)
    visual_review = visual_review_summary(tender_id, conn=conn)
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    enterprise = get_enterprise_profile(conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    materials = material_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)

    summary = coverage.get("summary", {})
    sections = coverage.get("sections", [])
    requirements = response_matrix.get("requirements", [])
    findings = coverage.get("findings", [])
    matrix_summary = response_matrix.get("summary", {})
    tasks: list[dict[str, Any]] = []

    missing_task = missing_task_fields(task)
    if missing_task:
        labels = [TASK_FIELD_LABELS.get(field, field) for field in missing_task]
        tasks.append(
            _task(
                "medium",
                "生产任务信息不完整",
                "生产任务",
                f"缺少：{', '.join(labels)}。",
                "补齐客户名称、交付期限和交付格式，避免交付范围不清。",
            )
        )

    if materials["pending_required"]:
        names = "、".join(str(item.get("name") or "") for item in materials["pending_required_items"][:8])
        tasks.append(
            _task(
                "medium",
                "必要资料未补齐",
                "资料清单",
                f"仍有 {materials['pending_required']} 项必要资料待补：{names}。",
                "在资料清单中更新资料状态，或向客户补要完整招标文件、评分办法、项目资料和目标要求。",
            )
        )

    missing_profile = [field for field in PROFILE_REQUIRED_FIELDS if profile.get(field) in ("", None)]
    if missing_profile:
        labels = [PROFILE_FIELD_LABELS.get(field, field) for field in missing_profile]
        tasks.append(
            _task(
                "medium",
                "项目资料不完整",
                "项目资料",
                f"缺少：{', '.join(labels)}。",
                "补齐项目类型、结构形式、建设规模、工期、质量目标和安全目标。",
            )
        )

    missing_enterprise = [field for field in ENTERPRISE_REQUIRED_FIELDS if not str(enterprise.get(field) or "").strip()]
    if missing_enterprise:
        labels = [ENTERPRISE_REQUIRED_FIELDS[field] for field in missing_enterprise]
        tasks.append(
            _task(
                "medium",
                "投标单位资料不完整",
                "投标单位资料",
                f"缺少：{', '.join(labels)}。",
                "补齐投标单位、资质能力、拟投入人员和机械设备资源，避免章节生成时编造企业能力。",
            )
        )

    for section in sections:
        if not section.get("draft_id"):
            tasks.append(
                _task(
                    "high",
                    "目录章节未生成",
                    "目录规划",
                    f"{section.get('order_no')}. {section.get('section_title')} 还没有草稿。",
                    "在目录规划中生成本章，或确认本章不属于本次交付范围后删除。",
                    section_title=str(section.get("section_title") or ""),
                )
            )
        elif int(section.get("citations_count") or 0) == 0:
            tasks.append(
                _task(
                    "medium",
                    "章节来源缺失",
                    "来源追溯",
                    f"{section.get('section_title')} 没有引用历史素材来源。",
                    "重新检索知识库片段，或在人工补写后补充来源说明。",
                    section_title=str(section.get("section_title") or ""),
                    draft_id=int(section["draft_id"]),
                )
            )
        if int(section.get("high_findings_count") or 0):
            tasks.append(
                _task(
                    "high",
                    "章节存在高风险审查问题",
                    "审查问题",
                    f"{section.get('section_title')} 有 {section.get('high_findings_count')} 个高风险问题。",
                    "打开草稿并处理历史项目名、错误引用或严重未响应问题。",
                    section_title=str(section.get("section_title") or ""),
                    draft_id=int(section["draft_id"]) if section.get("draft_id") else None,
                )
            )

    for req in requirements:
        if req.get("response_scope") == "chapter" and req.get("priority") == "high" and req.get("response_status") != "verified":
            tasks.append(
                _task(
                    "high",
                    "高优先级条款缺少有效正文证据",
                    "响应矩阵",
                    str(req.get("content") or ""),
                    "打开对应章节补写明确响应，重新运行证据定位并完成复核。",
                    requirement_id=int(req["id"]),
                )
            )

    compliance_pending = [
        req
        for req in requirements
        if req.get("response_scope") == "compliance"
        and req.get("applicable", True)
        and req.get("classification_review_status") != "approved"
    ]
    if compliance_pending:
        tasks.append(
            _task(
                "medium",
                "投标合规风险待人工核对",
                "合规清单",
                f"仍有 {len(compliance_pending)} 条合规要求未确认，不写入施工章节。",
                "在响应矩阵中逐项确认签章、保证金、文件格式、递交和废标条件。",
            )
        )

    scoring_total = int(matrix_summary.get("scoring_requirements") or 0)
    scoring_verified = int(matrix_summary.get("verified_scoring_requirements") or 0)
    evidence_rate = float(matrix_summary.get("chapter_evidence_rate") or 0)
    if scoring_verified < scoring_total:
        tasks.append(
            _task(
                "high",
                "评分点未全部形成有效响应",
                "响应矩阵",
                f"评分点证据已验证 {scoring_verified}/{scoring_total} 条。",
                "按评分办法逐条补齐专门小节、表格或控制措施，并重新执行证据审查。",
            )
        )
    if evidence_rate < 0.95:
        tasks.append(
            _task(
                "medium",
                "普通技术要求证据覆盖不足",
                "响应矩阵",
                f"当前自动证据覆盖率为 {evidence_rate:.1%}，正式交付要求不低于95%。",
                "补写缺口条款，或由终审人员确认有效证据或不适用原因。",
            )
        )
    if not visual_review.get("ready"):
        tasks.append(
            _task(
                "medium",
                "使用中的视觉素材未完成复核",
                "图文配图",
                f"已通过 {visual_review.get('approved', 0)}/{visual_review.get('total_used', 0)} 项，缺失文件 {visual_review.get('missing_files', 0)} 项。",
                "仅保留适用于本项目的图表和示意图，逐项通过或禁止使用。",
            )
        )

    for finding in findings:
        severity = str(finding.get("severity") or "medium")
        if severity == "high":
            tasks.append(
                _task(
                    "high",
                    "高风险审查问题",
                    "审查问题",
                    str(finding.get("message") or ""),
                    "优先修改对应草稿后重新执行质量门禁。",
                    draft_id=int(finding["draft_id"]) if finding.get("draft_id") else None,
                )
            )

    if feedback.get("open"):
        tasks.append(
            _task(
                "medium",
                "客户反馈未处理",
                "返工反馈",
                f"仍有 {feedback['open']} 条客户反馈或返工事项未解决。",
                "处理反馈并标记为已解决后再交付终版。",
            )
        )

    if payment.get("requires_payment_confirmation"):
        tasks.append(
            _task(
                "medium",
                "收款状态未确认",
                "收款记录",
                f"订单金额 {payment.get('expected_amount', 0)} 元，已确认 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
                "正式发货前人工确认收款、定金或客户约定，并登记收款记录。",
            )
        )

    tasks.extend(_draft_quality_tasks(conn, tender_id, profile))

    high_count = sum(1 for item in tasks if item.get("severity") == "high")
    medium_count = sum(1 for item in tasks if item.get("severity") == "medium")
    low_count = sum(1 for item in tasks if item.get("severity") == "low")
    total_requirements = int(summary.get("total_requirements") or 0)
    total_sections = int(summary.get("total_sections") or 0)
    missing_sections = int(summary.get("missing_sections") or 0)
    high_priority_missing = int(summary.get("high_priority_missing") or 0)

    if not total_requirements or not total_sections or missing_sections or high_priority_missing or high_count:
        status = "blocked"
    elif medium_count:
        status = "needs_fix"
    elif low_count:
        status = "needs_review"
    else:
        status = "pass"

    gate_items = [
        _status_item(
            "requirements",
            "响应矩阵",
            "complete" if total_requirements else "blocked",
            f"已解析 {total_requirements} 条要求。" if total_requirements else "尚未解析招标要求。",
        ),
        _status_item(
            "sections",
            "章节完整性",
            "complete" if total_sections and not missing_sections else "blocked",
            f"已生成 {int(summary.get('generated_sections') or 0)}/{total_sections} 个规划章节。",
        ),
        _status_item(
            "coverage",
            "条款证据覆盖",
            "complete" if evidence_rate >= 0.95 and scoring_verified == scoring_total else "blocked",
            f"正文证据覆盖率 {evidence_rate:.1%}；评分点 {scoring_verified}/{scoring_total}。",
        ),
        _status_item(
            "visual_review",
            "视觉素材复核",
            "complete" if visual_review.get("ready") else "warning",
            f"使用中素材已通过 {visual_review.get('approved', 0)}/{visual_review.get('total_used', 0)} 项。",
        ),
        _status_item(
            "traceability",
            "来源追溯",
            "complete" if not any(item["title"] == "章节来源缺失" for item in tasks) else "warning",
            "检查生成章节是否保留历史来源引用。",
        ),
        _status_item(
            "enterprise_profile",
            "投标单位资料",
            "complete" if not missing_enterprise else "warning",
            "已维护投标单位核心资料。" if not missing_enterprise else f"仍缺 {len(missing_enterprise)} 项核心企业资料。",
        ),
        _status_item(
            "payment_confirmation",
            "收款确认",
            "complete" if not payment.get("requires_payment_confirmation") else "warning",
            f"{payment.get('status_label', '')}：已收 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
        ),
        _status_item(
            "manual_review",
            "人工终审",
            "warning",
            "交付前仍需人工核对项目名称、专用条款、格式、页码和承诺边界。",
        ),
    ]

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": coverage.get("tender", {}),
        "status": status,
        "status_label": _status_label(status),
        "score": _quality_score(tasks),
        "summary": {
            "task_count": len(tasks),
            "high": high_count,
            "medium": medium_count,
            "low": low_count,
            "total_requirements": total_requirements,
            "total_sections": total_sections,
            "missing_sections": missing_sections,
            "high_priority_missing": high_priority_missing,
            "draft_coverage_rate": summary.get("draft_coverage_rate", 0),
            "chapter_evidence_rate": evidence_rate,
            "scoring_requirements": scoring_total,
            "verified_scoring_requirements": scoring_verified,
            "high_requirements": matrix_summary.get("high_requirements", 0),
            "verified_high_requirements": matrix_summary.get("verified_high_requirements", 0),
            "compliance_requirements": matrix_summary.get("compliance_requirements", 0),
            "compliance_pending": len(compliance_pending),
            "visuals_used": visual_review.get("total_used", 0),
            "visuals_approved": visual_review.get("approved", 0),
            "materials_pending_required": materials["pending_required"],
            "payment_status": payment.get("status"),
            "payment_status_label": payment.get("status_label"),
            "payment_received_amount": payment.get("received_amount", 0),
            "payment_outstanding_amount": payment.get("outstanding_amount", 0),
        },
        "gate_items": gate_items,
        "revision_tasks": tasks,
        "coverage": coverage,
        "response_matrix": response_matrix,
        "visual_review": visual_review,
        "feedback": feedback,
        "materials": materials,
        "payment": payment,
    }
    result["markdown"] = render_quality_gate_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_quality_gate_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender", {})
    summary = report.get("summary", {})
    lines = [
        "# 质量门禁报告",
        "",
        f"- 项目名称：{tender.get('name', '')}",
        f"- 项目 ID：{tender.get('id', '')}",
        f"- 生成时间：{report.get('generated_at', '')}",
        f"- 门禁结论：{report.get('status_label', '')}",
        f"- 质量分：{report.get('score', 0)}",
        f"- 修订任务：{summary.get('task_count', 0)} 条，其中高风险 {summary.get('high', 0)} 条，中风险 {summary.get('medium', 0)} 条。",
        "",
        "## 分项检查",
    ]
    for item in report.get("gate_items", []):
        lines.append(f"- {item.get('title')}：{item.get('status')}。{item.get('detail')}")
    lines.extend(["", "## 修订任务清单"])
    tasks = report.get("revision_tasks", [])
    if tasks:
        for index, item in enumerate(tasks, 1):
            scope = item.get("scope") or ""
            section = f" / {item.get('section_title')}" if item.get("section_title") else ""
            lines.append(f"{index}. [{item.get('severity')}] {item.get('title')}（{scope}{section}）")
            lines.append(f"   - 问题：{item.get('detail')}")
            lines.append(f"   - 动作：{item.get('action')}")
    else:
        lines.append("- 暂无自动发现的修订任务，可进入人工终审。")
    return "\n".join(lines).strip() + "\n"
