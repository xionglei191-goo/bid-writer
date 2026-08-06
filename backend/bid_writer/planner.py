from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .generator import generate_draft
from .requirement_responses import rebuild_requirement_responses
from .requirement_scope import requirement_scope
from .section_templates import DEFAULT_TEMPLATE, STANDARD_TEMPLATE_CATALOG, SectionTemplate, template_for, template_terms
from .text_utils import keywords


BASE_SECTION_TITLES = (
    "工程概况",
    "施工总体部署",
    "施工工艺及主要施工方法",
    "工程重点难点分析及对策",
    "施工进度计划及保证措施",
    "质量保证措施",
    "安全文明施工及环境保护",
    "施工总平面布置",
    "BIM及智慧建造应用",
    "新技术应用",
    "总承包管理与协调",
)


def _requirement_matches_template(requirement: dict[str, Any], template: SectionTemplate, section_title: str) -> bool:
    content = str(requirement.get("content") or "")
    terms = set(template_terms(template.name)) | set(keywords(section_title))
    return any(term and term in content for term in terms)


def _load_tender_requirements(conn: sqlite3.Connection, tender_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    requirements = rows_to_dicts(
        conn.execute(
            """
            SELECT * FROM requirements
            WHERE tender_id = ?
            ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, id
            """,
            (tender_id,),
        ).fetchall()
    )
    return tender, requirements


def build_section_plan(
    tender_id: int,
    reset: bool = True,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    _, requirements = _load_tender_requirements(conn, tender_id)

    sections: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for title in BASE_SECTION_TITLES:
        template = template_for(title)
        sections[title] = {
            "section_title": title,
            "template": template,
            "requirement_ids": [],
            "rationale": "基础技术标章节",
        }

    for req in requirements:
        content = str(req.get("content") or "")
        detected = template_for(content)
        if detected is not DEFAULT_TEMPLATE:
            title = detected.name
            sections.setdefault(
                title,
                {
                    "section_title": title,
                    "template": detected,
                    "requirement_ids": [],
                    "rationale": "根据招标要求自动补充",
                },
            )

    for section in sections.values():
        template = section["template"]
        matched_ids = [
            int(req["id"])
            for req in requirements
            if _requirement_matches_template(req, template, section["section_title"])
        ]
        if matched_ids:
            section["requirement_ids"] = matched_ids
            section["rationale"] = f"命中招标要求 {len(matched_ids)} 条"

    with conn:
        if reset:
            conn.execute("DELETE FROM section_plans WHERE tender_id = ?", (tender_id,))
        for index, section in enumerate(sections.values(), 1):
            template = section["template"]
            conn.execute(
                """
                INSERT INTO section_plans (
                    tender_id, order_no, section_title, template_name,
                    requirement_ids_json, rationale, status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'planned')
                """,
                (
                    tender_id,
                    index,
                    section["section_title"],
                    template.name,
                    json.dumps(section["requirement_ids"], ensure_ascii=False),
                    section["rationale"],
                ),
            )
    plans = list_section_plans(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return plans


def list_section_plans(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT sp.*, d.section_title AS draft_section_title
            FROM section_plans sp
            LEFT JOIN drafts d ON d.id = sp.draft_id
            WHERE sp.tender_id = ?
            ORDER BY sp.order_no, sp.id
            """,
            (tender_id,),
        ).fetchall()
    )
    for row in rows:
        row["requirement_ids"] = json.loads(row.get("requirement_ids_json") or "[]")
    if own_conn:
        conn.close()
    return rows


def add_section_plan(
    tender_id: int,
    section_title: str,
    template_name: str = "",
    requirement_ids: list[int] | None = None,
    order_no: int | None = None,
    rationale: str = "人工补充章节",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    if not section_title.strip():
        raise ValueError("Section title is required")
    if order_no is None:
        row = conn.execute("SELECT COALESCE(MAX(order_no), 0) + 1 FROM section_plans WHERE tender_id = ?", (tender_id,)).fetchone()
        order_no = int(row[0])
    template = template_for(template_name or section_title)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO section_plans (
                tender_id, order_no, section_title, template_name,
                requirement_ids_json, rationale, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'planned')
            """,
            (
                tender_id,
                int(order_no),
                section_title.strip(),
                template.name,
                json.dumps(requirement_ids or [], ensure_ascii=False),
                rationale,
            ),
        )
    plan = row_to_dict(conn.execute("SELECT * FROM section_plans WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    plan["requirement_ids"] = json.loads(plan.get("requirement_ids_json") or "[]")
    if own_conn:
        conn.close()
    return plan


def _normal_text(value: Any) -> str:
    return re_sub_non_word(str(value or "")).lower()


def re_sub_non_word(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _plan_matches_expected(plan: dict[str, Any], expected: dict[str, Any]) -> bool:
    expected_name = str(expected.get("name") or "")
    aliases = {expected_name, *[str(item) for item in expected.get("aliases") or []]}
    plan_title = str(plan.get("section_title") or "")
    plan_template = str(plan.get("template_name") or "")
    if plan_template == expected_name or plan_title == expected_name:
        return True
    normalized_aliases = {_normal_text(alias) for alias in aliases}
    if _normal_text(plan_title) in normalized_aliases or _normal_text(plan_template) in normalized_aliases:
        return True
    return template_for(plan_title).name == expected_name


def audit_section_plan(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender, requirements = _load_tender_requirements(conn, tender_id)
    plans = list_section_plans(tender_id, conn=conn)
    planned_requirement_ids = {
        int(req_id)
        for plan in plans
        for req_id in plan.get("requirement_ids", [])
        if str(req_id).isdigit()
    }
    generated_count = sum(1 for plan in plans if plan.get("draft_id"))
    standard_items: list[dict[str, Any]] = []
    missing_standard: list[dict[str, Any]] = []
    for expected in STANDARD_TEMPLATE_CATALOG:
        template = template_for(str(expected.get("name") or ""))
        matches = [plan for plan in plans if _plan_matches_expected(plan, expected)]
        matched_ids = [
            int(req["id"])
            for req in requirements
            if _requirement_matches_template(req, template, str(expected.get("name") or ""))
        ]
        item = {
            "name": expected.get("name"),
            "group": expected.get("group"),
            "aliases": list(expected.get("aliases") or []),
            "covered": bool(matches),
            "plan_id": int(matches[0]["id"]) if matches else None,
            "order_no": int(matches[0]["order_no"]) if matches else None,
            "draft_id": int(matches[0]["draft_id"]) if matches and matches[0].get("draft_id") else None,
            "matched_requirement_ids": matched_ids,
            "matched_requirement_count": len(matched_ids),
            "severity": "high" if not matches and expected.get("name") in BASE_SECTION_TITLES else ("medium" if not matches else "ok"),
        }
        standard_items.append(item)
        if not matches:
            missing_standard.append(item)

    unplanned_requirements = [
        {
            "id": int(req["id"]),
            "kind": req.get("kind"),
            "priority": req.get("priority"),
            "content": req.get("content"),
            "suggested_template": template_for(str(req.get("content") or "")).name,
            "response_scope": requirement_scope(req),
        }
        for req in requirements
        if int(req["id"]) not in planned_requirement_ids
    ]
    high_unplanned = [
        item for item in unplanned_requirements if item.get("priority") == "high" and item.get("response_scope") == "chapter"
    ]
    compliance_unplanned = [item for item in unplanned_requirements if item.get("response_scope") == "compliance"]
    recommendations: list[str] = []
    if missing_standard:
        names = "、".join(str(item.get("name") or "") for item in missing_standard)
        recommendations.append(f"建议补齐缺失标准章节：{names}。")
    if high_unplanned:
        recommendations.append(f"{len(high_unplanned)} 条高优先级要求未挂接到目录章节，建议补充章节或调整章节关联。")
    if compliance_unplanned:
        recommendations.append(f"{len(compliance_unplanned)} 条投标合规风险保留在人工核对清单，不强制挂接施工章节。")
    if not plans:
        recommendations.append("当前项目还没有目录规划，建议先根据招标要求生成目录。")
    if not recommendations:
        recommendations.append("目录标准章节完整，可继续生成章节和做覆盖审查。")

    summary = {
        "plans": len(plans),
        "generated_plans": generated_count,
        "standard_total": len(STANDARD_TEMPLATE_CATALOG),
        "standard_covered": len(standard_items) - len(missing_standard),
        "missing_standard": len(missing_standard),
        "unplanned_requirements": len(unplanned_requirements),
        "high_unplanned_requirements": len(high_unplanned),
        "compliance_unplanned_requirements": len(compliance_unplanned),
        "construction_method_present": any(
            item.get("name") == "施工工艺及主要施工方法" and item.get("covered") for item in standard_items
        ),
        "readiness": "needs_work" if missing_standard or high_unplanned or not plans else "ready",
    }
    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "summary": summary,
        "standard_items": standard_items,
        "missing_standard": missing_standard,
        "unplanned_requirements": unplanned_requirements,
        "recommendations": recommendations,
    }
    result["markdown"] = render_plan_audit_markdown(result)
    if own_conn:
        conn.close()
    return result


def repair_section_plan(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    before = audit_section_plan(tender_id, conn=conn)
    added: list[dict[str, Any]] = []
    order_row = conn.execute(
        "SELECT COALESCE(MAX(order_no), 0) AS max_order FROM section_plans WHERE tender_id = ?",
        (tender_id,),
    ).fetchone()
    order_no = int(order_row["max_order"] or 0)
    for item in before.get("missing_standard") or []:
        order_no += 1
        added.append(
            add_section_plan(
                tender_id,
                str(item.get("name") or ""),
                template_name=str(item.get("name") or ""),
                requirement_ids=[int(req_id) for req_id in item.get("matched_requirement_ids") or []],
                order_no=order_no,
                rationale="目录完整性审计自动补齐",
                conn=conn,
            )
        )
    after = audit_section_plan(tender_id, conn=conn)
    result = {
        "tender_id": tender_id,
        "added_count": len(added),
        "added": added,
        "before": before,
        "after": after,
    }
    if own_conn:
        conn.close()
    return result


def render_plan_audit_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 目录完整性审计报告",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 行业：{tender.get('industry') or '未登记'}",
        "",
        "## 审计概览",
        f"- 目录章节：{summary.get('plans', 0)}",
        f"- 已生成章节：{summary.get('generated_plans', 0)}",
        f"- 标准章节覆盖：{summary.get('standard_covered', 0)}/{summary.get('standard_total', 0)}",
        f"- 缺失标准章节：{summary.get('missing_standard', 0)}",
        f"- 未挂接要求：{summary.get('unplanned_requirements', 0)}",
        f"- 高优先级未挂接要求：{summary.get('high_unplanned_requirements', 0)}",
        f"- 施工工艺章节：{'已覆盖' if summary.get('construction_method_present') else '缺失'}",
        f"- 审计状态：{summary.get('readiness')}",
        "",
        "## 处理建议",
    ]
    lines.extend(f"- {item}" for item in report.get("recommendations") or [])
    lines.extend(["", "## 标准章节覆盖"])
    for item in report.get("standard_items") or []:
        status = "已覆盖" if item.get("covered") else "缺失"
        lines.append(
            f"- [{status}] {item.get('name')} / {item.get('group')} / "
            f"关联要求 {item.get('matched_requirement_count', 0)} 条"
        )
    lines.extend(["", "## 未挂接要求"])
    unplanned = report.get("unplanned_requirements") or []
    if not unplanned:
        lines.append("- 暂无未挂接要求。")
    for req in unplanned[:50]:
        lines.append(f"- #{req.get('id')} [{req.get('priority')}] {req.get('kind')}：{req.get('content')}")
    return "\n".join(lines).strip() + "\n"


def update_section_plan(
    plan_id: int,
    section_title: str | None = None,
    order_no: int | None = None,
    requirement_ids: list[int] | None = None,
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    existing = row_to_dict(conn.execute("SELECT * FROM section_plans WHERE id = ?", (plan_id,)).fetchone())
    if not existing:
        raise ValueError(f"Section plan not found: {plan_id}")

    next_title = (section_title or existing["section_title"]).strip()
    if not next_title:
        raise ValueError("Section title is required")
    next_order = int(order_no if order_no is not None else existing["order_no"])
    next_status = status or existing.get("status") or "planned"
    next_requirements = (
        requirement_ids
        if requirement_ids is not None
        else json.loads(existing.get("requirement_ids_json") or "[]")
    )
    next_template = template_for(next_title).name
    with conn:
        conn.execute(
            """
            UPDATE section_plans
            SET order_no = ?, section_title = ?, template_name = ?,
                requirement_ids_json = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                next_order,
                next_title,
                next_template,
                json.dumps(next_requirements, ensure_ascii=False),
                next_status,
                plan_id,
            ),
        )
    plan = row_to_dict(conn.execute("SELECT * FROM section_plans WHERE id = ?", (plan_id,)).fetchone()) or {}
    plan["requirement_ids"] = json.loads(plan.get("requirement_ids_json") or "[]")
    if own_conn:
        conn.close()
    return plan


def delete_section_plan(plan_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        cur = conn.execute("DELETE FROM section_plans WHERE id = ?", (plan_id,))
    if own_conn:
        conn.close()
    return {"plan_id": plan_id, "deleted": cur.rowcount > 0}


def generate_from_plan(plan_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    plan = row_to_dict(conn.execute("SELECT * FROM section_plans WHERE id = ?", (plan_id,)).fetchone())
    if not plan:
        raise ValueError(f"Section plan not found: {plan_id}")
    requirement_ids = json.loads(plan.get("requirement_ids_json") or "[]")
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (plan["tender_id"],)).fetchone()) or {}
    draft = generate_draft(
        tender_id=int(plan["tender_id"]),
        section_title=str(plan["section_title"]),
        requirement_ids=[int(item) for item in requirement_ids],
        category=str(tender.get("industry") or ""),
        conn=conn,
    )
    with conn:
        conn.execute(
            """
            UPDATE section_plans
            SET status = 'generated', draft_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (draft["id"], plan_id),
        )
    rebuild_requirement_responses(int(plan["tender_id"]), conn=conn)
    draft["plan"] = row_to_dict(conn.execute("SELECT * FROM section_plans WHERE id = ?", (plan_id,)).fetchone())
    if own_conn:
        conn.close()
    return draft


def generate_all_from_plan(
    tender_id: int,
    regenerate: bool = False,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    plans = list_section_plans(tender_id, conn=conn)
    if not plans:
        plans = build_section_plan(tender_id, conn=conn)

    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for plan in plans:
        plan_id = int(plan["id"])
        draft_id = plan.get("draft_id")
        if draft_id and not regenerate:
            exists = conn.execute("SELECT 1 FROM drafts WHERE id = ?", (draft_id,)).fetchone()
            if exists:
                skipped.append(
                    {
                        "plan_id": plan_id,
                        "draft_id": int(draft_id),
                        "section_title": plan["section_title"],
                        "reason": "已存在草稿",
                    }
                )
                continue

        draft = generate_from_plan(plan_id, conn=conn)
        generated.append(
            {
                "plan_id": plan_id,
                "draft_id": int(draft["id"]),
                "section_title": draft["section_title"],
                "char_count": len(str(draft.get("content") or "")),
            }
        )

    plans = list_section_plans(tender_id, conn=conn)
    result = {
        "tender_id": tender_id,
        "generated_count": len(generated),
        "skipped_count": len(skipped),
        "generated": generated,
        "skipped": skipped,
        "plans": plans,
    }
    if own_conn:
        conn.close()
    return result
