from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .draft_scope import active_drafts
from .planner import list_section_plans
from .requirement_scope import requirement_scope
from .review import review_tender


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_coverage_report(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    requirements = rows_to_dicts(
        conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall()
    )
    plans = list_section_plans(tender_id, conn=conn)
    drafts = active_drafts(conn, tender_id)
    for draft in drafts:
        draft["char_count"] = len(str(draft.get("content") or ""))

    plan_by_req: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for plan in plans:
        for req_id in plan.get("requirement_ids", []):
            plan_by_req[int(req_id)].append(
                {
                    "plan_id": int(plan["id"]),
                    "order_no": int(plan["order_no"]),
                    "section_title": plan["section_title"],
                    "draft_id": plan.get("draft_id"),
                }
            )

    draft_by_req: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for draft in drafts:
        for req in _json_list(draft.get("requirements_json")):
            if isinstance(req, dict) and req.get("id"):
                draft_by_req[int(req["id"])].append(
                    {
                        "draft_id": int(draft["id"]),
                        "section_title": draft["section_title"],
                        "char_count": int(draft.get("char_count") or 0),
                    }
                )

    findings = review_tender(tender_id, conn=conn)
    findings_by_draft: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if finding.get("draft_id"):
            findings_by_draft[int(finding["draft_id"])].append(finding)

    requirement_items: list[dict[str, Any]] = []
    covered_by_plan = 0
    covered_by_draft = 0
    high_priority_missing = 0
    chapter_requirements = 0
    compliance_pending = 0
    for req in requirements:
        req_id = int(req["id"])
        response_scope = requirement_scope(req)
        planned_sections = plan_by_req.get(req_id, [])
        draft_sections = draft_by_req.get(req_id, [])
        status = "missing"
        if draft_sections:
            status = "generated"
            if response_scope == "chapter":
                covered_by_draft += 1
        elif planned_sections:
            status = "planned"
        if planned_sections and response_scope == "chapter":
            covered_by_plan += 1
        if response_scope == "chapter":
            chapter_requirements += 1
        elif not draft_sections:
            compliance_pending += 1
        if response_scope == "chapter" and req.get("priority") == "high" and not draft_sections:
            high_priority_missing += 1
        requirement_items.append(
            {
                "id": req_id,
                "kind": req["kind"],
                "priority": req["priority"],
                "response_scope": response_scope,
                "content": req["content"],
                "status": status,
                "planned_sections": planned_sections,
                "draft_sections": draft_sections,
            }
        )

    draft_by_id = {int(draft["id"]): draft for draft in drafts}
    section_items: list[dict[str, Any]] = []
    for plan in plans:
        draft = draft_by_id.get(int(plan["draft_id"])) if plan.get("draft_id") else None
        citations_count = len(_json_list(draft.get("citations_json"))) if draft else 0
        section_findings = findings_by_draft.get(int(draft["id"]), []) if draft else []
        section_items.append(
            {
                "plan_id": int(plan["id"]),
                "order_no": int(plan["order_no"]),
                "section_title": plan["section_title"],
                "template_name": plan.get("template_name") or "",
                "status": "generated" if draft else plan.get("status", "planned"),
                "draft_id": int(draft["id"]) if draft else None,
                "requirement_count": len(plan.get("requirement_ids", [])),
                "char_count": int(draft.get("char_count") or 0) if draft else 0,
                "citations_count": citations_count,
                "findings_count": len(section_findings),
                "high_findings_count": sum(1 for item in section_findings if item.get("severity") == "high"),
            }
        )

    generated_sections = sum(1 for item in section_items if item["draft_id"])
    missing_sections = sum(1 for item in section_items if not item["draft_id"])
    total_requirements = len(requirements)
    total_sections = len(section_items)
    recommendations = []
    if missing_sections:
        recommendations.append(f"还有 {missing_sections} 个目录章节未生成，建议先执行批量生成。")
    if high_priority_missing:
        recommendations.append(f"还有 {high_priority_missing} 条高优先级条款未形成草稿响应。")
    if compliance_pending:
        recommendations.append(f"另有 {compliance_pending} 条投标合规风险需在外发前人工核对，不计入施工章节覆盖率。")
    if any(item["high_findings_count"] for item in section_items):
        recommendations.append("审查发现高风险问题，请先处理历史项目名、引用缺失等事项。")
    if not recommendations:
        recommendations.append("目录章节和条款响应已形成草稿，可进入人工复核和格式整理。")

    summary = {
        "total_requirements": total_requirements,
        "chapter_requirements": chapter_requirements,
        "compliance_requirements": total_requirements - chapter_requirements,
        "compliance_pending": compliance_pending,
        "covered_by_plan": covered_by_plan,
        "covered_by_draft": covered_by_draft,
        "plan_coverage_rate": round(covered_by_plan / chapter_requirements, 4) if chapter_requirements else 1,
        "draft_coverage_rate": round(covered_by_draft / chapter_requirements, 4) if chapter_requirements else 1,
        "total_sections": total_sections,
        "generated_sections": generated_sections,
        "missing_sections": missing_sections,
        "high_priority_missing": high_priority_missing,
        "review_findings": len(findings),
        "overall_status": "ready" if not missing_sections and not high_priority_missing and not findings else "needs_review",
    }

    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "summary": summary,
        "requirements": requirement_items,
        "sections": section_items,
        "findings": findings,
        "recommendations": recommendations,
    }
    if own_conn:
        conn.close()
    return result
