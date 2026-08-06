from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .construction_methods import method_outline_for
from .db import connect, row_to_dict, rows_to_dicts
from .project_profiles import get_project_profile
from .section_templates import SectionTemplate
from .section_templates import template_for
from .template_assets import industry_template_for


CONSTRUCTION_METHOD_STRUCTURE = (
    "适用范围",
    "施工准备",
    "工艺流程",
    "控制参数与操作要点",
    "质量检查",
    "安全环保措施",
    "检查验收",
    "成品保护",
)

FORBIDDEN_ASSUMPTIONS = (
    "未提供的人员姓名、证书编号和履历",
    "未提供的机械型号、数量和进场日期",
    "未提供的楼层、标高、构件尺寸和工程数量",
    "未提供的开竣工日期和阶段节点",
    "未提供的企业资质、业绩、奖项和履约承诺",
)


def build_chapter_contract(
    section_title: str,
    profile: dict[str, Any],
    requirements: list[dict[str, Any]],
    template: SectionTemplate,
) -> dict[str, Any]:
    facts = {
        key: profile.get(key)
        for key in (
            "project_name",
            "industry",
            "region",
            "project_type",
            "structure_type",
            "building_area",
            "floor_info",
            "duration_days",
            "quality_target",
            "safety_target",
            "contract_scope",
            "site_conditions",
            "key_constraints",
            "special_requirements",
        )
        if profile.get(key) not in {None, ""}
    }
    is_construction = template.name == "施工工艺及主要施工方法"
    industry_template = industry_template_for(profile)
    methods = method_outline_for(profile) if is_construction else []
    required_subsections = list(template.outline)
    table_slots: list[str] = []
    visual_slots: list[str] = []
    if is_construction:
        required_subsections = list(methods)
        table_slots = ["主要工艺控制参数表", "质量检查与验收表"]
        visual_slots = ["主要工艺流程图", "关键施工工序示意图"]
    elif "进度" in section_title:
        table_slots = ["主要节点计划表"]
        visual_slots = ["施工总进度横道图"]
    elif "总体部署" in section_title:
        table_slots = ["劳动力配置表", "主要机械设备配置表"]
        visual_slots = ["项目管理组织架构图", "项目总体实施流程图"]
    elif "总平面" in section_title:
        table_slots = ["临时设施配置表"]
        visual_slots = ["施工总平面功能分区示意图"]
    elif any(term in section_title for term in ("质量", "安全", "BIM", "总承包")):
        visual_slots = [f"{section_title}管理流程图"]
    return {
        "section_title": section_title,
        "template_name": template.name,
        "project_facts": facts,
        "requirement_ids": [int(item["id"]) for item in requirements if item.get("id")],
        "requirements": [
            {
                "id": item.get("id"),
                "priority": item.get("priority"),
                "score_weight": item.get("score_weight") or 0,
                "content": item.get("content") or "",
            }
            for item in requirements
        ],
        "required_subsections": required_subsections,
        "construction_method_structure": list(CONSTRUCTION_METHOD_STRUCTURE) if is_construction else [],
        "table_slots": table_slots,
        "visual_slots": visual_slots,
        "forbidden_assumptions": list(FORBIDDEN_ASSUMPTIONS),
        "minimum_chars": 3200 if is_construction else 1800,
        "industry_template": industry_template,
    }


def contract_prompt(contract: dict[str, Any]) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2)


def validate_chapter_contract(content: str, contract: dict[str, Any]) -> dict[str, Any]:
    missing_subsections: list[str] = []
    for title in contract.get("required_subsections") or []:
        if str(title) not in content:
            missing_subsections.append(str(title))
    missing_method_fields: list[str] = []
    if contract.get("construction_method_structure"):
        for field in contract["construction_method_structure"]:
            if str(field) not in content:
                missing_method_fields.append(str(field))
    placeholder_count = len(re.findall(r"【待确认[^】]*】", content))
    char_count = len(re.sub(r"\s+", "", content))
    return {
        "char_count": char_count,
        "minimum_chars": int(contract.get("minimum_chars") or 0),
        "length_ok": char_count >= int(contract.get("minimum_chars") or 0),
        "missing_subsections": missing_subsections,
        "missing_method_fields": missing_method_fields,
        "placeholder_count": placeholder_count,
        "table_slots": contract.get("table_slots") or [],
        "visual_slots": contract.get("visual_slots") or [],
        "ready_for_review": not missing_subsections and not missing_method_fields and char_count >= int(contract.get("minimum_chars") or 0),
    }


def structured_generation_result(content: str, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "markdown": content,
        "requirement_ids": contract.get("requirement_ids") or [],
        "pending_items": re.findall(r"【待确认[^】]*】", content),
        "table_suggestions": contract.get("table_slots") or [],
        "visual_suggestions": contract.get("visual_slots") or [],
        "validation": validate_chapter_contract(content, contract),
    }


def backfill_chapter_contracts(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    profile = get_project_profile(tender_id, conn=conn)
    requirements = {
        int(row["id"]): row
        for row in rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ?", (tender_id,)).fetchall())
    }
    plans = rows_to_dicts(conn.execute("SELECT * FROM section_plans WHERE tender_id = ? ORDER BY order_no, id", (tender_id,)).fetchall())
    updated = 0
    with conn:
        for plan in plans:
            if not plan.get("draft_id"):
                continue
            draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (plan["draft_id"],)).fetchone())
            if not draft:
                continue
            try:
                requirement_ids = json.loads(plan.get("requirement_ids_json") or "[]")
            except json.JSONDecodeError:
                requirement_ids = []
            linked_requirements = [requirements[int(item)] for item in requirement_ids if str(item).isdigit() and int(item) in requirements]
            selected_template = template_for(str(plan.get("template_name") or plan.get("section_title") or ""))
            contract = build_chapter_contract(str(draft.get("section_title") or ""), profile, linked_requirements, selected_template)
            try:
                current_review = json.loads(draft.get("review_json") or "[]")
            except json.JSONDecodeError:
                current_review = []
            findings = current_review.get("findings") if isinstance(current_review, dict) else current_review
            payload = {
                "findings": findings or [],
                "chapter_contract": contract,
                "contract_validation": validate_chapter_contract(str(draft.get("content") or ""), contract),
                "structured_result": structured_generation_result(str(draft.get("content") or ""), contract),
            }
            conn.execute(
                "UPDATE drafts SET review_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), draft["id"]),
            )
            updated += 1
    result = {"tender_id": tender_id, "updated_drafts": updated}
    if own_conn:
        conn.close()
    return result
