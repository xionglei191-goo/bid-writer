from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .planner import build_section_plan, list_section_plans, update_section_plan
from .requirement_scope import requirement_scope
from .requirement_responses import list_requirement_responses, rebuild_requirement_responses
from .section_templates import template_for, template_terms
from .text_utils import keywords


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _int_list(value: Any) -> list[int]:
    items = value if isinstance(value, list) else _json_list(str(value or "[]"))
    result: list[int] = []
    for item in items:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _plan_matches_template(plan: dict[str, Any], template_name: str) -> bool:
    return (
        str(plan.get("template_name") or "") == template_name
        or str(plan.get("section_title") or "") == template_name
        or template_for(str(plan.get("section_title") or "")).name == template_name
    )


def _plan_score(requirement: dict[str, Any], plan: dict[str, Any], template_name: str) -> int:
    content = str(requirement.get("content") or "")
    section_title = str(plan.get("section_title") or "")
    plan_template = str(plan.get("template_name") or "")
    if _plan_matches_template(plan, template_name):
        return 100
    terms = set(template_terms(plan_template or section_title)) | set(keywords(section_title))
    return sum(1 for term in terms if term and term in content)


def _suggest_plan(requirement: dict[str, Any], plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not plans:
        return None
    template = template_for(str(requirement.get("content") or ""))
    scored = [
        (_plan_score(requirement, plan, template.name), int(plan.get("order_no") or 9999), plan)
        for plan in plans
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2] if scored and scored[0][0] > 0 else None


def build_response_matrix(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    requirements = rows_to_dicts(
        conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall()
    )
    rebuild_requirement_responses(tender_id, conn=conn)
    response_rows = list_requirement_responses(tender_id, conn=conn)
    responses_by_req: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for response in response_rows:
        responses_by_req[int(response["requirement_id"])].append(response)
    plans = list_section_plans(tender_id, conn=conn)
    drafts = rows_to_dicts(
        conn.execute(
            """
            SELECT id, section_title, requirements_json, LENGTH(content) AS char_count
            FROM drafts
            WHERE tender_id = ?
            ORDER BY id
            """,
            (tender_id,),
        ).fetchall()
    )

    plans_by_req: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for plan in plans:
        for req_id in _int_list(plan.get("requirement_ids", [])):
            plans_by_req[req_id].append(
                {
                    "plan_id": int(plan["id"]),
                    "order_no": int(plan.get("order_no") or 0),
                    "section_title": plan.get("section_title") or "",
                    "template_name": plan.get("template_name") or "",
                    "draft_id": int(plan["draft_id"]) if plan.get("draft_id") else None,
                }
            )

    drafts_by_req: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for draft in drafts:
        for req in _json_list(draft.get("requirements_json")):
            if isinstance(req, dict) and req.get("id"):
                drafts_by_req[int(req["id"])].append(
                    {
                        "draft_id": int(draft["id"]),
                        "section_title": draft.get("section_title") or "",
                        "char_count": int(draft.get("char_count") or 0),
                    }
                )

    requirement_items: list[dict[str, Any]] = []
    for req in requirements:
        req_id = int(req["id"])
        planned_sections = sorted(plans_by_req.get(req_id, []), key=lambda item: item["order_no"])
        draft_sections = drafts_by_req.get(req_id, [])
        suggested_template = template_for(str(req.get("content") or "")).name
        response_scope = requirement_scope(req)
        suggested_plan = _suggest_plan(req, plans) if response_scope == "chapter" else None
        evidence = responses_by_req.get(req_id, [])
        best_evidence = max(evidence, key=lambda item: float(item.get("coverage_score") or 0), default=None)
        if not int(req.get("applicable", 1)):
            status = "not_applicable"
        elif any(item.get("response_status") == "verified" for item in evidence):
            status = "verified"
        elif evidence:
            status = str(best_evidence.get("response_status") or "needs_review")
        elif response_scope in {"compliance", "business"}:
            status = "manual_check"
        else:
            status = "unlinked"
        requirement_items.append(
            {
                "id": req_id,
                "kind": req.get("kind") or "",
                "priority": req.get("priority") or "",
                "status": req.get("status") or "",
                "content": req.get("content") or "",
                "source_hint": req.get("source_hint") or "",
                "source_page": req.get("source_page"),
                "score_weight": float(req.get("score_weight") or 0),
                "applicable": bool(req.get("applicable", 1)),
                "classification_source": req.get("classification_source") or "auto",
                "classification_review_status": req.get("review_status") or "pending",
                "classification_review_notes": req.get("review_notes") or "",
                "response_status": status,
                "response_scope": response_scope,
                "planned_sections": planned_sections,
                "draft_sections": draft_sections,
                "evidence": evidence,
                "best_evidence": best_evidence,
                "suggested_template": suggested_template,
                "suggested_plan_id": int(suggested_plan["id"]) if suggested_plan else None,
                "suggested_section": suggested_plan.get("section_title") if suggested_plan else "",
                "auto_linkable": bool(response_scope == "chapter" and suggested_plan and not planned_sections),
            }
        )

    section_items: list[dict[str, Any]] = []
    req_by_id = {int(req["id"]): req for req in requirements}
    for plan in plans:
        linked_ids = _int_list(plan.get("requirement_ids", []))
        linked_requirements = [req_by_id[req_id] for req_id in linked_ids if req_id in req_by_id]
        section_items.append(
            {
                "plan_id": int(plan["id"]),
                "order_no": int(plan.get("order_no") or 0),
                "section_title": plan.get("section_title") or "",
                "template_name": plan.get("template_name") or "",
                "draft_id": int(plan["draft_id"]) if plan.get("draft_id") else None,
                "linked_requirement_ids": linked_ids,
                "linked_requirement_count": len(linked_requirements),
                "high_linked_requirement_count": sum(1 for req in linked_requirements if req.get("priority") == "high"),
            }
        )

    applicable_chapter = [item for item in requirement_items if item["response_scope"] == "chapter" and item["applicable"]]
    verified_chapter = [item for item in applicable_chapter if item["response_status"] == "verified"]
    located_chapter = [item for item in applicable_chapter if item["response_status"] in {"verified", "needs_review"}]
    scoring_items = [item for item in applicable_chapter if item["kind"] == "scoring" or item["score_weight"] > 0]
    high_items = [item for item in applicable_chapter if item["priority"] == "high"]
    summary = {
        "requirements": len(requirement_items),
        "planned_requirements": sum(1 for item in requirement_items if item["planned_sections"]),
        "generated_requirements": sum(1 for item in requirement_items if item["draft_sections"]),
        "unplanned_requirements": sum(
            1 for item in applicable_chapter if not item["planned_sections"]
        ),
        "manual_check_requirements": sum(
            1
            for item in requirement_items
            if item["response_scope"] in {"compliance", "business", "project_fact"} and item["applicable"]
        ),
        "high_unplanned_requirements": sum(
            1
            for item in requirement_items
            if item.get("response_scope") == "chapter" and item.get("priority") == "high" and not item["planned_sections"]
        ),
        "chapter_requirements": sum(1 for item in requirement_items if item.get("response_scope") == "chapter"),
        "compliance_requirements": sum(1 for item in requirement_items if item.get("response_scope") == "compliance"),
        "business_requirements": sum(1 for item in requirement_items if item.get("response_scope") == "business"),
        "project_fact_requirements": sum(1 for item in requirement_items if item.get("response_scope") == "project_fact"),
        "verified_chapter_requirements": len(verified_chapter),
        "located_chapter_requirements": len(located_chapter),
        "chapter_evidence_rate": round(len(verified_chapter) / len(applicable_chapter), 4) if applicable_chapter else 0,
        "automatic_evidence_rate": round(len(located_chapter) / len(applicable_chapter), 4) if applicable_chapter else 0,
        "scoring_requirements": len(scoring_items),
        "verified_scoring_requirements": sum(1 for item in scoring_items if item["response_status"] == "verified"),
        "high_requirements": len(high_items),
        "verified_high_requirements": sum(1 for item in high_items if item["response_status"] == "verified"),
        "requirements_needing_review": sum(1 for item in applicable_chapter if item["response_status"] in {"needs_review", "missing", "unlinked"}),
        "auto_linkable_requirements": sum(1 for item in requirement_items if item["auto_linkable"]),
        "sections": len(section_items),
        "sections_without_requirements": sum(1 for item in section_items if not item["linked_requirement_ids"]),
        "readiness": "ready"
        if requirement_items
        and all(item["response_status"] == "verified" for item in high_items)
        and (len(verified_chapter) / len(applicable_chapter) if applicable_chapter else 0) >= 0.95
        else ("pending" if not requirement_items else "needs_work"),
    }

    recommendations: list[str] = []
    if not section_items:
        recommendations.append("当前项目还没有目录规划，建议先生成目录或执行自动挂接生成基础目录。")
    if summary["high_unplanned_requirements"]:
        recommendations.append(f"有 {summary['high_unplanned_requirements']} 条高优先级要求未挂接目录，建议立即自动挂接或手工调整。")
    if summary["auto_linkable_requirements"]:
        recommendations.append(f"有 {summary['auto_linkable_requirements']} 条要求可按模板自动挂接到建议章节。")
    if summary["sections_without_requirements"]:
        recommendations.append(f"有 {summary['sections_without_requirements']} 个目录章节暂未关联具体条款，可人工复核是否为通用章节。")
    if summary["requirements_needing_review"]:
        recommendations.append(
            f"有 {summary['requirements_needing_review']} 条技术要求尚未形成足够正文证据，需补写或人工确认。"
        )
    if not recommendations:
        recommendations.append("响应矩阵与目录章节已经建立挂接关系，可继续生成章节草稿。")

    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "summary": summary,
        "requirements": requirement_items,
        "sections": section_items,
        "recommendations": recommendations,
    }
    result["markdown"] = render_response_matrix_markdown(result)
    if own_conn:
        conn.close()
    return result


def auto_link_response_matrix(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    built_plan_count = 0
    if not list_section_plans(tender_id, conn=conn):
        built_plan_count = len(build_section_plan(tender_id, conn=conn))
    before = build_response_matrix(tender_id, conn=conn)
    links: list[dict[str, Any]] = []
    plans = list_section_plans(tender_id, conn=conn)
    plans_by_id = {int(plan["id"]): plan for plan in plans}
    for item in before.get("requirements") or []:
        if item.get("response_scope") != "chapter" or not item.get("applicable", True):
            continue
        plan_id = item.get("suggested_plan_id")
        if item.get("planned_sections") or not plan_id or int(plan_id) not in plans_by_id:
            continue
        plan = plans_by_id[int(plan_id)]
        linked_ids = _int_list(plan.get("requirement_ids", []))
        req_id = int(item["id"])
        if req_id not in linked_ids:
            linked_ids.append(req_id)
            updated = update_section_plan(int(plan_id), requirement_ids=linked_ids, conn=conn)
            plans_by_id[int(plan_id)] = updated
            links.append(
                {
                    "requirement_id": req_id,
                    "plan_id": int(plan_id),
                    "section_title": updated.get("section_title") or "",
                    "suggested_template": item.get("suggested_template") or "",
                }
            )
    after = build_response_matrix(tender_id, conn=conn)
    result = {
        "tender_id": tender_id,
        "built_plan_count": built_plan_count,
        "linked_count": len(links),
        "links": links,
        "before": before,
        "after": after,
    }
    if own_conn:
        conn.close()
    return result


def realign_response_matrix(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Rebuild automatic chapter links while preserving manually classified requirements."""
    own_conn = conn is None
    conn = conn or connect()
    before = build_response_matrix(tender_id, conn=conn)
    plans = list_section_plans(tender_id, conn=conn)
    requirements = rows_to_dicts(
        conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall()
    )
    requirements_by_id = {int(item["id"]): item for item in requirements}
    manual_ids = {
        int(item["id"])
        for item in requirements
        if str(item.get("classification_source") or "auto") == "manual"
    }
    next_ids: dict[int, list[int]] = {}
    for plan in plans:
        next_ids[int(plan["id"])] = [
            req_id for req_id in _int_list(plan.get("requirement_ids", [])) if req_id in manual_ids
        ]

    assignments: list[dict[str, Any]] = []
    for requirement in requirements:
        req_id = int(requirement["id"])
        if req_id in manual_ids:
            continue
        if requirement_scope(requirement) != "chapter" or not int(requirement.get("applicable", 1)):
            continue
        plan = _suggest_plan(requirement, plans)
        if not plan:
            continue
        plan_id = int(plan["id"])
        if req_id not in next_ids[plan_id]:
            next_ids[plan_id].append(req_id)
        assignments.append(
            {
                "requirement_id": req_id,
                "plan_id": plan_id,
                "section_title": plan.get("section_title") or "",
                "suggested_template": template_for(str(requirement.get("content") or "")).name,
            }
        )

    with conn:
        for plan in plans:
            plan_id = int(plan["id"])
            ids = next_ids[plan_id]
            conn.execute(
                "UPDATE section_plans SET requirement_ids_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(ids, ensure_ascii=False), plan_id),
            )
            if plan.get("draft_id"):
                payload = [requirements_by_id[req_id] for req_id in ids if req_id in requirements_by_id]
                conn.execute(
                    "UPDATE drafts SET requirements_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False), int(plan["draft_id"])),
                )
    rebuild_requirement_responses(tender_id, conn=conn)
    after = build_response_matrix(tender_id, conn=conn)
    result = {
        "tender_id": tender_id,
        "assignment_count": len(assignments),
        "assignments": assignments,
        "before": before,
        "after": after,
    }
    if own_conn:
        conn.close()
    return result


def render_response_matrix_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 响应矩阵挂接报告",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 行业：{tender.get('industry') or '未登记'}",
        "",
        "## 挂接概览",
        f"- 招标要求：{summary.get('requirements', 0)}",
        f"- 已挂接目录：{summary.get('planned_requirements', 0)}",
        f"- 已生成草稿响应：{summary.get('generated_requirements', 0)}",
        f"- 未挂接要求：{summary.get('unplanned_requirements', 0)}",
        f"- 高优先级未挂接：{summary.get('high_unplanned_requirements', 0)}",
        f"- 可自动挂接：{summary.get('auto_linkable_requirements', 0)}",
        f"- 审计状态：{summary.get('readiness')}",
        "",
        "## 处理建议",
    ]
    lines.extend(f"- {item}" for item in report.get("recommendations") or [])
    lines.extend(["", "## 要求挂接明细"])
    for item in report.get("requirements") or []:
        sections = "、".join(section.get("section_title") or "" for section in item.get("planned_sections") or []) or "未挂接"
        drafts = "、".join(section.get("section_title") or "" for section in item.get("draft_sections") or []) or "未生成"
        lines.append(
            f"- #{item.get('id')} [{item.get('priority')}] {item.get('kind')} / {item.get('response_status')}："
            f"{item.get('content')} / 目录：{sections} / 草稿：{drafts} / 建议：{item.get('suggested_section') or item.get('suggested_template')}"
        )
    lines.extend(["", "## 章节挂接概览"])
    for item in report.get("sections") or []:
        lines.append(
            f"- {item.get('order_no')}. {item.get('section_title')}："
            f"关联 {item.get('linked_requirement_count', 0)} 条，高优先级 {item.get('high_linked_requirement_count', 0)} 条"
        )
    return "\n".join(lines).strip() + "\n"
