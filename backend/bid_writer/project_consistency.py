from __future__ import annotations

import re
from typing import Any

from .text_utils import keywords, summarize


def _text(value: Any) -> str:
    return str(value or "").strip()


def _section_has(section_title: str, *terms: str) -> bool:
    title = _text(section_title)
    return any(term in title for term in terms)


def _important_terms(value: str, limit: int = 4) -> list[str]:
    terms: list[str] = []
    for term in keywords(value):
        if len(term) >= 2 and term not in terms:
            terms.append(term)
        if len(terms) >= limit:
            break
    if terms:
        return terms
    return [part for part in re.split(r"[，,；;\s、]+", value) if len(part) >= 2][:limit]


def _has_any(content: str, terms: list[str]) -> bool:
    return any(term and term in content for term in terms)


def _finding(severity: str, field: str, title: str, detail: str, action: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "type": "project_consistency",
        "field": field,
        "message": title,
        "detail": detail,
        "action": action,
    }


def project_consistency_findings(
    profile: dict[str, Any],
    section_title: str,
    content: str,
) -> list[dict[str, Any]]:
    text = _text(content)
    title = _text(section_title)
    findings: list[dict[str, Any]] = []

    duration = profile.get("duration_days")
    if duration and _section_has(title, "施工总体部署", "施工部署", "进度", "工期", "总体部署"):
        duration_text = str(duration)
        if duration_text not in text:
            findings.append(
                _finding(
                    "medium",
                    "duration_days",
                    "未体现工期目标",
                    f"项目资料登记工期为 {duration_text} 日历天，但《{title}》未体现该工期目标。",
                    "补充总体工期、阶段节点、资源保障和纠偏措施。",
                )
            )

    quality = _text(profile.get("quality_target"))
    if quality and _section_has(title, "质量", "工程概况", "施工总体部署", "施工部署"):
        terms = _important_terms(quality, limit=3)
        if not _has_any(text, terms):
            findings.append(
                _finding(
                    "medium",
                    "quality_target",
                    "未体现质量目标",
                    f"项目资料登记质量目标为“{quality}”，但《{title}》未体现关键口径。",
                    "补充质量目标、样板引路、过程检查、验收标准和整改闭环。",
                )
            )

    safety = _text(profile.get("safety_target"))
    if safety and _section_has(title, "安全", "文明", "环境保护", "施工总体部署", "施工部署"):
        terms = _important_terms(safety, limit=3)
        if not _has_any(text, terms):
            findings.append(
                _finding(
                    "medium",
                    "safety_target",
                    "未体现安全文明目标",
                    f"项目资料登记安全目标为“{safety}”，但《{title}》未体现关键口径。",
                    "补充安全文明目标、重大危险源、检查频次、应急和整改闭环。",
                )
            )

    scope = _text(profile.get("contract_scope"))
    if scope and _section_has(title, "工程概况", "施工总体部署", "施工部署", "总承包", "施工工艺", "施工方法"):
        terms = _important_terms(scope, limit=5)
        if terms and sum(1 for term in terms if term in text) < min(2, len(terms)):
            findings.append(
                _finding(
                    "low",
                    "contract_scope",
                    "承包范围响应不足",
                    f"承包范围包含“{summarize(scope, 120)}”，但《{title}》体现不足。",
                    "补充本章涉及的承包界面、专业接口和移交条件。",
                )
            )

    site = _text(profile.get("site_conditions"))
    if site and _section_has(title, "施工总体部署", "施工部署", "总平面", "重难点", "难点", "施工工艺", "施工方法"):
        terms = _important_terms(site, limit=4)
        if terms and not _has_any(text, terms):
            findings.append(
                _finding(
                    "medium",
                    "site_conditions",
                    "未体现现场条件",
                    f"项目资料登记现场条件为“{summarize(site, 140)}”，但《{title}》未体现。",
                    "补充场地、交通、周边环境、运输组织、噪声扬尘和成品保护措施。",
                )
            )

    special = _text(profile.get("special_requirements"))
    if special and _section_has(title, "施工工艺", "施工方法", "重难点", "难点", "质量", "BIM", "智慧"):
        terms = _important_terms(special, limit=5)
        if terms and not _has_any(text, terms):
            findings.append(
                _finding(
                    "high",
                    "special_requirements",
                    "未体现专项要求",
                    f"项目资料登记专项要求为“{summarize(special, 140)}”，但《{title}》未体现。",
                    "补充专项深化、样板、旁站、检测、联动调试和验收控制。",
                )
            )

    scale = _text(profile.get("building_area"))
    structure = _text(profile.get("structure_type"))
    floor = _text(profile.get("floor_info"))
    if _section_has(title, "工程概况", "施工总体部署", "施工部署") and any((scale, structure, floor)):
        expected_terms = [term for term in [*_important_terms(scale, 2), *_important_terms(structure, 2), *_important_terms(floor, 2)] if term]
        if expected_terms and not _has_any(text, expected_terms):
            findings.append(
                _finding(
                    "low",
                    "project_parameters",
                    "工程参数体现不足",
                    "项目资料已登记建设规模、结构或层数，但章节未明显体现这些参数。",
                    "补充建设规模、结构形式、层数信息及对部署、资源或工艺的影响。",
                )
            )

    return findings
