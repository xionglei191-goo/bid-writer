from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .construction_methods import COMMON_METHODS, METHOD_LIBRARY


@dataclass(frozen=True)
class SectionTemplate:
    name: str
    intent: str
    outline: tuple[str, ...]
    quality_points: tuple[str, ...]


TEMPLATES: tuple[tuple[tuple[str, ...], SectionTemplate], ...] = (
    (
        ("工程概况", "项目概况"),
        SectionTemplate(
            name="工程概况",
            intent="说明项目建设背景、工程范围、现场条件和技术管理目标。",
            outline=("工程基本情况", "承包范围与界面", "现场条件分析", "管理目标与响应"),
            quality_points=("项目名称、建设地点、规模参数需人工复核", "不得沿用历史项目特征参数"),
        ),
    ),
    (
        ("施工总体部署", "施工部署", "总体部署", "资源配备", "资源配置", "项目管理班子", "流水段", "交叉作业"),
        SectionTemplate(
            name="施工总体部署",
            intent="形成项目实施的总体组织、施工区段、资源投入和阶段安排。",
            outline=("总体部署原则", "施工区段与流水组织", "资源配置计划", "关键阶段控制措施"),
            quality_points=("部署逻辑应与工期节点一致", "区段划分需结合总平面和现场条件"),
        ),
    ),
    (
        (
            "施工工艺",
            "施工方法",
            "主要施工方法",
            "分部分项",
            "专项施工方案",
            "工艺流程",
            "施工技术措施",
            "施工方案与技术措施",
            "测量放线",
            "土方",
            "基坑",
            "桩基",
            "主体结构",
            "钢筋",
            "模板",
            "混凝土",
            "砌体",
            "装饰装修",
            "屋面",
            "防水",
            "幕墙",
            "钢结构",
            "机电安装",
            "水性漆",
        ),
        SectionTemplate(
            name="施工工艺及主要施工方法",
            intent="系统说明主要分部分项工程的施工流程、操作要点、质量控制、验收标准和成品保护措施。",
            outline=(
                "总体工艺流程与施工顺序",
                "主要分部分项工程施工方法",
                "关键工序控制要点",
                "质量验收与成品保护",
                "专项工艺风险及旁站检查",
            ),
            quality_points=(
                "施工工艺应与工程类型、结构形式、现场条件和招标范围一致",
                "每项主要工艺需包含流程、操作要点、质量标准和验收控制",
                "涉及危大工程或专业分包内容时需人工复核专项方案边界",
            ),
        ),
    ),
    (
        ("重难点", "重点难点", "难点分析", "风险管理", "风险防控", "风险预控", "应急措施"),
        SectionTemplate(
            name="工程重点难点分析及对策",
            intent="识别项目实施风险，提出可执行的技术、组织和资源保障措施。",
            outline=("重点难点识别", "成因与影响分析", "专项应对措施", "过程监测与闭环管理"),
            quality_points=("每个难点必须有对应措施", "措施应包含责任、资源、节点和验收标准"),
        ),
    ),
    (
        ("质量", "质量保证", "质量管理"),
        SectionTemplate(
            name="质量保证措施",
            intent="建立质量目标、质量体系、过程控制和验收管理。",
            outline=("质量目标与管理体系", "样板引路与技术交底", "过程检查与实测实量", "质量通病防治"),
            quality_points=("质量目标需与招标文件一致", "避免只有制度表述而缺少过程动作"),
        ),
    ),
    (
        ("安全文明", "文明施工", "安全生产", "安全管理", "安全防护", "安全施工", "人身安全", "施工秩序", "环境保护", "扬尘", "建筑垃圾", "保通措施", "交通畅通", "非道路移动机械"),
        SectionTemplate(
            name="安全文明施工及环境保护",
            intent="建立安全生产、文明施工、绿色施工和应急管理措施。",
            outline=("安全管理目标与责任体系", "重大危险源管控", "文明施工与绿色施工", "应急处置与检查整改"),
            quality_points=("重大危险源需结合工程特点", "环保措施应覆盖扬尘、噪声、污水和固废"),
        ),
    ),
    (
        ("进度", "工期", "施工计划"),
        SectionTemplate(
            name="施工进度计划及保证措施",
            intent="说明总体进度安排、关键线路、资源保障和纠偏机制。",
            outline=("工期目标响应", "关键线路与节点计划", "资源保障措施", "进度监测与纠偏"),
            quality_points=("工期节点需人工复核", "措施应区分人材机、技术、协调和资金保障"),
        ),
    ),
    (
        ("总平面", "平面布置", "临设"),
        SectionTemplate(
            name="施工总平面布置",
            intent="规划临建、道路、材料堆场、加工区、临水临电和阶段转换。",
            outline=("布置原则", "临建设施与道路组织", "材料堆场及加工区", "临水临电与消防布置"),
            quality_points=("需结合现场红线、出入口和塔吊/机械位置", "阶段性布置应与施工部署对应"),
        ),
    ),
    (
        ("BIM", "智慧建造", "信息化"),
        SectionTemplate(
            name="BIM及智慧建造应用",
            intent="说明 BIM、信息化平台和数字化管理在技术标中的应用场景。",
            outline=("BIM组织与标准", "模型深化与碰撞检查", "进度质量安全协同", "成果交付与运维衔接"),
            quality_points=("应用点应服务施工管理目标", "避免泛泛描述软件名称"),
        ),
    ),
    (
        ("新技术", "新工艺", "新材料", "新设备"),
        SectionTemplate(
            name="新技术应用",
            intent="说明新技术、新工艺、新材料、新设备的应用计划和保障措施。",
            outline=("应用目标", "拟采用技术清单", "实施组织与过程控制", "效益评估与成果总结"),
            quality_points=("技术清单需匹配项目类型", "不得承诺不具备条件的技术应用"),
        ),
    ),
    (
        ("总承包", "协调管理", "组织管理"),
        SectionTemplate(
            name="总承包管理与协调",
            intent="说明总承包管理组织、专业协调、界面管理和对外协调。",
            outline=("总承包管理体系", "专业分包协调", "界面与计划管理", "沟通机制与问题闭环"),
            quality_points=("管理界面需与合同范围一致", "协调机制应体现会议、计划、问题台账和考核"),
        ),
    ),
)


DEFAULT_TEMPLATE = SectionTemplate(
    name="通用技术标章节",
    intent="围绕招标要求形成可审查、可落地、可追溯的技术措施。",
    outline=("目标响应", "组织安排", "实施措施", "检查验收"),
    quality_points=("需结合项目实际参数复核", "保留来源引用并完成项目化改写"),
)


STANDARD_TEMPLATE_CATALOG: tuple[dict[str, Any], ...] = (
    {"name": "工程概况", "aliases": ("工程概况", "项目概况"), "group": "基础响应"},
    {"name": "施工总体部署", "aliases": ("施工总体部署", "施工部署", "总体部署", "资源配备", "项目管理班子"), "group": "组织部署"},
    {
        "name": "施工工艺及主要施工方法",
        "aliases": ("施工工艺", "施工方法", "主要施工方法", "分部分项", "专项施工方案", "施工方案与技术措施"),
        "group": "施工工艺",
        "required_methods": True,
    },
    {"name": "工程重点难点分析及对策", "aliases": ("重难点", "重点难点", "难点分析", "风险管理", "风险防控"), "group": "技术响应"},
    {"name": "质量保证措施", "aliases": ("质量", "质量保证", "质量管理"), "group": "质量安全"},
    {"name": "安全文明施工及环境保护", "aliases": ("安全文明", "文明施工", "安全生产", "环境保护", "扬尘", "建筑垃圾", "保通措施", "非道路移动机械"), "group": "质量安全"},
    {"name": "施工进度计划及保证措施", "aliases": ("进度", "工期", "施工计划"), "group": "进度计划"},
    {"name": "施工总平面布置", "aliases": ("总平面", "平面布置", "临设"), "group": "现场组织"},
    {"name": "BIM及智慧建造应用", "aliases": ("BIM", "智慧建造", "信息化"), "group": "技术应用"},
    {"name": "新技术应用", "aliases": ("新技术", "新工艺", "新材料", "新设备"), "group": "技术应用"},
    {"name": "总承包管理与协调", "aliases": ("总承包", "协调管理", "组织管理"), "group": "协调管理"},
)


def _list_from_json(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _list_from_payload(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).replace("，", ",").replace("、", ",")
    if "\n" in text:
        parts = text.splitlines()
    elif "/" in text:
        parts = text.split("/")
    else:
        parts = text.split(",")
    return [part.strip() for part in parts if part.strip()]


def _custom_template_items(conn: sqlite3.Connection | None = None) -> list[tuple[tuple[str, ...], SectionTemplate, dict[str, Any]]]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM custom_section_templates
                WHERE enabled = 1
                ORDER BY id
                """
            ).fetchall()
        )
    except sqlite3.Error:
        rows = []
    if own_conn:
        conn.close()

    items: list[tuple[tuple[str, ...], SectionTemplate, dict[str, Any]]] = []
    for row in rows:
        keywords = tuple(_list_from_json(row.get("keywords_json")) or [str(row.get("name") or "")])
        template = SectionTemplate(
            name=str(row.get("name") or ""),
            intent=str(row.get("intent") or ""),
            outline=tuple(_list_from_json(row.get("outline_json"))),
            quality_points=tuple(_list_from_json(row.get("quality_points_json"))),
        )
        if not template.name:
            continue
        items.append(
            (
                keywords,
                template,
                {
                    "id": row.get("id"),
                    "source": "custom",
                    "enabled": row.get("enabled"),
                    "industry": row.get("industry") or "",
                    "project_type": row.get("project_type") or "",
                    "method_key": row.get("method_key") or "",
                    "version": row.get("version") or "1.0",
                    "review_status": row.get("review_status") or "approved",
                    "generation_rules": _json_object(row.get("generation_rules_json")),
                },
            )
        )
    return items


def _effective_items(conn: sqlite3.Connection | None = None) -> list[tuple[tuple[str, ...], SectionTemplate, dict[str, Any]]]:
    custom_items = _custom_template_items(conn=conn)
    custom_names = {template.name for _, template, _ in custom_items}
    static_items = [
        (terms, template, {"id": None, "source": "default", "enabled": 1})
        for terms, template in TEMPLATES
        if template.name not in custom_names
    ]
    return [*custom_items, *static_items]


def _template_dict(terms: tuple[str, ...], template: SectionTemplate, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": meta.get("id"),
        "source": meta.get("source") or "default",
        "enabled": int(meta.get("enabled") if meta.get("enabled") is not None else 1),
        "name": template.name,
        "keywords": list(terms),
        "intent": template.intent,
        "outline": list(template.outline),
        "quality_points": list(template.quality_points),
        "industry": meta.get("industry") or "",
        "project_type": meta.get("project_type") or "",
        "method_key": meta.get("method_key") or "",
        "version": meta.get("version") or ("builtin" if meta.get("source") == "default" else "1.0"),
        "review_status": meta.get("review_status") or "approved",
        "generation_rules": meta.get("generation_rules") or {},
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def template_for(section_title: str, conn: sqlite3.Connection | None = None) -> SectionTemplate:
    title = section_title.lower()
    for terms, template, _ in _effective_items(conn=conn):
        if any(term.lower() in title for term in terms):
            return template
    return DEFAULT_TEMPLATE


def template_terms(template_name: str, conn: sqlite3.Connection | None = None) -> tuple[str, ...]:
    for terms, template, _ in _effective_items(conn=conn):
        if template.name == template_name:
            return terms
    return (template_name,)


def all_templates(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    custom_by_name = {
        template.name: _template_dict(terms, template, meta)
        for terms, template, meta in _custom_template_items(conn=conn)
    }
    items: list[dict[str, Any]] = []
    for terms, template in TEMPLATES:
        items.append(custom_by_name.pop(template.name, _template_dict(terms, template, {"source": "default"})))
    items.extend(custom_by_name.values())
    return items


def template_coverage_report(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    templates = all_templates(conn=conn)
    by_name = {item["name"]: item for item in templates}
    coverage_items: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for expected in STANDARD_TEMPLATE_CATALOG:
        aliases = tuple(str(alias) for alias in expected.get("aliases") or ())
        matched = by_name.get(str(expected["name"]))
        if not matched:
            for item in templates:
                keywords = {str(keyword) for keyword in item.get("keywords") or []}
                if str(item.get("name") or "") in aliases or any(alias in keywords for alias in aliases):
                    matched = item
                    break
        item = {
            "name": expected["name"],
            "group": expected["group"],
            "aliases": list(aliases),
            "covered": bool(matched),
            "source": matched.get("source") if matched else "",
            "template_id": matched.get("id") if matched else None,
            "outline_count": len(matched.get("outline") or []) if matched else 0,
            "quality_points_count": len(matched.get("quality_points") or []) if matched else 0,
            "required_methods": bool(expected.get("required_methods")),
        }
        coverage_items.append(item)
        if not matched:
            missing.append(item)

    method_groups = [
        {
            "keywords": list(keywords),
            "methods": list(methods),
            "method_count": len(methods),
        }
        for keywords, methods in METHOD_LIBRARY
    ]
    method_count = len(set(COMMON_METHODS).union(*(set(methods) for _, methods in METHOD_LIBRARY)))
    construction_template = next((item for item in coverage_items if item["name"] == "施工工艺及主要施工方法"), {})
    recommendations: list[str] = []
    if missing:
        recommendations.append("优先补齐缺失章节模板，避免目录规划回退到通用模板。")
    if not construction_template.get("covered"):
        recommendations.append("施工工艺模板缺失，应补充主要施工方法、关键工序、质量验收和成品保护提纲。")
    else:
        recommendations.append(f"施工工艺模板已覆盖，并已接入 {len(method_groups)} 类工程工艺库、{method_count} 条工艺要点。")
    custom_count = sum(1 for item in templates if item.get("source") == "custom")
    default_count = sum(1 for item in templates if item.get("source") == "default")
    summary = {
        "standard_total": len(STANDARD_TEMPLATE_CATALOG),
        "covered_total": sum(1 for item in coverage_items if item["covered"]),
        "missing_total": len(missing),
        "default_templates": default_count,
        "custom_templates": custom_count,
        "method_groups": len(method_groups),
        "method_items": method_count,
        "construction_method_template_covered": bool(construction_template.get("covered")),
    }
    return {
        "summary": summary,
        "items": coverage_items,
        "missing": missing,
        "construction_methods": {
            "common": list(COMMON_METHODS),
            "groups": method_groups,
        },
        "recommendations": recommendations,
    }


def get_custom_template(template_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM custom_section_templates WHERE id = ?", (template_id,)).fetchone())
    if not row:
        raise ValueError(f"Template not found: {template_id}")
    if own_conn:
        conn.close()
    return {
        "id": row["id"],
        "source": "custom",
        "enabled": row.get("enabled"),
        "name": row.get("name") or "",
        "keywords": _list_from_json(row.get("keywords_json")),
        "intent": row.get("intent") or "",
        "outline": _list_from_json(row.get("outline_json")),
        "quality_points": _list_from_json(row.get("quality_points_json")),
        "industry": row.get("industry") or "",
        "project_type": row.get("project_type") or "",
        "method_key": row.get("method_key") or "",
        "version": row.get("version") or "1.0",
        "review_status": row.get("review_status") or "approved",
        "generation_rules": _json_object(row.get("generation_rules_json")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def save_section_template(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("模板名称不能为空。")
    keywords = _list_from_payload(data.get("keywords")) or [name]
    outline = _list_from_payload(data.get("outline"))
    quality_points = _list_from_payload(data.get("quality_points"))
    intent = str(data.get("intent") or "").strip()
    industry = str(data.get("industry") or "").strip()
    project_type = str(data.get("project_type") or "").strip()
    method_key = str(data.get("method_key") or "").strip()
    version = str(data.get("version") or "1.0").strip()
    review_status = str(data.get("review_status") or "approved").strip()
    generation_rules = _json_object(data.get("generation_rules"))
    with conn:
        current = row_to_dict(conn.execute("SELECT id FROM custom_section_templates WHERE name = ?", (name,)).fetchone())
        if current:
            template_id = int(current["id"])
            conn.execute(
                """
                UPDATE custom_section_templates
                SET keywords_json = ?, intent = ?, outline_json = ?,
                    quality_points_json = ?, industry = ?, project_type = ?, method_key = ?,
                    version = ?, review_status = ?, generation_rules_json = ?,
                    enabled = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    json.dumps(keywords, ensure_ascii=False),
                    intent,
                    json.dumps(outline, ensure_ascii=False),
                    json.dumps(quality_points, ensure_ascii=False),
                    industry,
                    project_type,
                    method_key,
                    version,
                    review_status,
                    json.dumps(generation_rules, ensure_ascii=False),
                    template_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO custom_section_templates (
                    name, keywords_json, intent, outline_json, quality_points_json,
                    industry, project_type, method_key, version, review_status,
                    generation_rules_json, enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    name,
                    json.dumps(keywords, ensure_ascii=False),
                    intent,
                    json.dumps(outline, ensure_ascii=False),
                    json.dumps(quality_points, ensure_ascii=False),
                    industry,
                    project_type,
                    method_key,
                    version,
                    review_status,
                    json.dumps(generation_rules, ensure_ascii=False),
                ),
            )
            template_id = int(cur.lastrowid)
    result = get_custom_template(template_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def update_section_template(template_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    current = get_custom_template(template_id, conn=conn)
    merged = {**current, **data}
    return save_section_template(merged, conn=conn)


def delete_section_template(template_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        cur = conn.execute("DELETE FROM custom_section_templates WHERE id = ?", (template_id,))
    if own_conn:
        conn.close()
    return {"id": template_id, "deleted": cur.rowcount > 0}
