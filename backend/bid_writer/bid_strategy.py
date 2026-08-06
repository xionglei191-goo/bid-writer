from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .materials import material_summary
from .project_profiles import get_project_profile, profile_summary
from .section_templates import template_for
from .text_utils import keywords


BASE_STRATEGY_SECTIONS = (
    "工程概况",
    "施工总体部署",
    "施工工艺及主要施工方法",
    "工程重点难点分析及对策",
    "施工进度计划及保证措施",
    "质量保证措施",
    "安全文明施工及环境保护",
    "施工总平面布置",
    "总承包管理与协调",
)

STRATEGY_FIELDS = (
    "positioning",
    "win_themes",
    "key_constraints",
    "risk_controls",
    "response_priorities",
    "writing_tone",
    "section_focus_json",
    "reference_keywords",
    "forbidden_terms",
    "status",
    "notes",
)


def _split_lines(text: str) -> list[str]:
    return [line.strip(" -\t") for line in str(text or "").splitlines() if line.strip(" -\t")]


def _join_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item).strip()


def _requirements(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM requirements
            WHERE tender_id = ?
            ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, id
            """,
            (tender_id,),
        ).fetchall()
    )


def _project_label(tender: dict[str, Any], profile: dict[str, Any]) -> str:
    return str(profile.get("project_name") or tender.get("name") or "本项目")


def _detect_themes(tender: dict[str, Any], profile: dict[str, Any], requirements: list[dict[str, Any]]) -> list[str]:
    blob = "\n".join(
        [
            str(tender.get("name") or ""),
            str(tender.get("industry") or ""),
            profile_summary(profile),
            "\n".join(str(item.get("content") or "") for item in requirements[:60]),
        ]
    )
    themes = ["以招标评分点为主线，突出技术响应完整性、措施可执行性和来源可追溯性"]
    mapping = (
        ("医院", "突出医疗专项机电、洁污分流、净化区域、运营安全和交叉施工控制"),
        ("学校", "突出校园安全、教学运营影响控制、绿色文明施工和工期节点保障"),
        ("厂房", "突出设备基础、洁净/生产工艺条件、机电安装协同和投产节点保障"),
        ("市政", "突出交通组织、管线迁改、周边协调、导改安全和分阶段开放"),
        ("水利", "突出防汛度汛、围堰导流、水工结构质量和生态环保控制"),
        ("BIM", "突出 BIM 深化、碰撞检查、进度质量安全协同和成果交付"),
        ("装配", "突出构件深化、运输堆放、吊装精度、连接质量和成品保护"),
        ("改造", "突出既有结构保护、运营不停用、拆改安全和界面协调"),
    )
    for keyword, theme in mapping:
        if keyword in blob and theme not in themes:
            themes.append(theme)
    quality = str(profile.get("quality_target") or "")
    safety = str(profile.get("safety_target") or "")
    if quality:
        themes.append(f"围绕质量目标“{quality}”设置样板引路、过程实测实量和验收闭环")
    if safety:
        themes.append(f"围绕安全目标“{safety}”设置风险分级管控、专项方案和应急响应")
    return themes[:8]


def _constraints(profile: dict[str, Any], materials: dict[str, Any], requirements: list[dict[str, Any]]) -> list[str]:
    items = []
    for field, label in (
        ("duration_days", "工期天数"),
        ("site_conditions", "现场条件"),
        ("key_constraints", "关键约束"),
        ("special_requirements", "特殊要求"),
        ("contract_scope", "承包范围"),
    ):
        value = profile.get(field)
        if value not in ("", None):
            items.append(f"{label}：{value}")
    risk_requirements = [str(item.get("content") or "") for item in requirements if item.get("kind") == "risk" or item.get("priority") == "high"]
    for item in risk_requirements[:6]:
        items.append(f"高优先级/风险条款：{item}")
    if materials.get("pending_required"):
        names = "、".join(str(item.get("name") or "") for item in materials.get("pending_required_items", [])[:6])
        items.append(f"资料缺口：{names}")
    return items[:12]


def _risk_controls(materials: dict[str, Any], requirements: list[dict[str, Any]]) -> list[str]:
    controls = [
        "所有章节避免承诺中标结果，仅承诺按招标文件完成技术标编制、复核和修改配合",
        "历史素材必须项目化改写，删除旧项目名称、旧地点、旧日期和不适用技术参数",
        "每章保留引用来源，交付前执行项目名、质量目标、工期目标和安全目标复核",
    ]
    if materials.get("pending_required"):
        controls.append("资料未补齐章节只作为初稿，正式交付前需根据最终招标文件重新校核")
    for item in requirements:
        content = str(item.get("content") or "")
        if item.get("kind") == "risk" and content:
            controls.append(f"废标/否决风险响应：{content}")
    return controls[:10]


def _section_focus(conn: sqlite3.Connection, tender_id: int, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM section_plans
            WHERE tender_id = ?
            ORDER BY order_no, id
            """,
            (tender_id,),
        ).fetchall()
    )
    for plan in plans:
        try:
            plan["requirement_ids"] = json.loads(plan.get("requirement_ids_json") or "[]")
        except json.JSONDecodeError:
            plan["requirement_ids"] = []
    if not plans:
        plans = [
            {
                "order_no": index,
                "section_title": title,
                "requirement_ids": [],
                "template_name": template_for(title).name,
            }
            for index, title in enumerate(BASE_STRATEGY_SECTIONS, 1)
        ]
    req_by_id = {int(item["id"]): item for item in requirements if item.get("id")}
    focus_items: list[dict[str, Any]] = []
    for plan in plans:
        section_title = str(plan.get("section_title") or "")
        template = template_for(str(plan.get("template_name") or section_title))
        linked = [req_by_id.get(int(item)) for item in plan.get("requirement_ids", []) if req_by_id.get(int(item))]
        high_count = sum(1 for item in linked if item and item.get("priority") == "high")
        focus = template.intent
        if linked:
            focus += f"；重点响应 {len(linked)} 条招标要求"
        if high_count:
            focus += f"，其中高优先级 {high_count} 条"
        focus_items.append(
            {
                "order_no": int(plan.get("order_no") or len(focus_items) + 1),
                "section_title": section_title,
                "focus": focus,
                "linked_requirements": len(linked),
                "high_priority": high_count,
            }
        )
    return focus_items[:24]


def _reference_keywords(tender: dict[str, Any], profile: dict[str, Any], requirements: list[dict[str, Any]]) -> list[str]:
    raw = [
        str(tender.get("industry") or ""),
        str(profile.get("project_type") or ""),
        str(profile.get("structure_type") or ""),
        str(profile.get("special_requirements") or ""),
    ]
    for item in requirements[:30]:
        raw.extend(keywords(str(item.get("content") or ""))[:4])
    seen: set[str] = set()
    result = []
    for item in raw:
        for part in str(item or "").replace("/", " ").replace("、", " ").split():
            part = part.strip()
            if len(part) >= 2 and part not in seen:
                seen.add(part)
                result.append(part)
    return result[:40]


def generate_bid_strategy(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    requirements = _requirements(conn, tender_id)
    materials = material_summary(tender_id, conn=conn)
    project_name = _project_label(tender, profile)
    high_requirements = [str(item.get("content") or "") for item in requirements if item.get("priority") == "high"]
    themes = _detect_themes(tender, profile, requirements)
    constraints = _constraints(profile, materials, requirements)
    controls = _risk_controls(materials, requirements)
    priorities = high_requirements[:8] or [str(item.get("content") or "") for item in requirements[:8]]
    section_focus = _section_focus(conn, tender_id, requirements)
    reference_keywords = _reference_keywords(tender, profile, requirements)
    strategy = {
        "positioning": f"{project_name} 的技术标应以“精准响应招标要求、突出项目化实施措施、保留来源可追溯”为总体编制定位。",
        "win_themes": _join_lines(themes),
        "key_constraints": _join_lines(constraints or ["工期、质量、安全、资料完整性和格式要求需在交付前逐项复核"]),
        "risk_controls": _join_lines(controls),
        "response_priorities": _join_lines(priorities or ["优先响应评分点、废标风险、目录要求和技术专项要求"]),
        "writing_tone": "正式、稳健、项目化；多写可执行动作、责任主体、检查频次和闭环措施，少用空泛承诺。",
        "section_focus_json": json.dumps(section_focus, ensure_ascii=False),
        "reference_keywords": " / ".join(reference_keywords),
        "forbidden_terms": _join_lines(["确保中标", "保证中标", "必中", "包中", "旧项目名称", "旧地点日期", "不适用技术参数"]),
        "status": "generated",
        "notes": "系统根据当前招标要求、项目资料、目录规划和资料清单自动生成，可人工编辑。",
    }
    row = row_to_dict(conn.execute("SELECT id FROM bid_strategies WHERE tender_id = ?", (tender_id,)).fetchone())
    with conn:
        if row:
            assignments = ", ".join(f"{field} = ?" for field in STRATEGY_FIELDS)
            conn.execute(
                f"""
                UPDATE bid_strategies
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE tender_id = ?
                """,
                (*[strategy[field] for field in STRATEGY_FIELDS], tender_id),
            )
        else:
            columns = ", ".join(["tender_id", *STRATEGY_FIELDS])
            placeholders = ", ".join("?" for _ in ["tender_id", *STRATEGY_FIELDS])
            conn.execute(
                f"INSERT INTO bid_strategies ({columns}) VALUES ({placeholders})",
                (tender_id, *[strategy[field] for field in STRATEGY_FIELDS]),
            )
    result = get_bid_strategy(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def get_bid_strategy(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM bid_strategies WHERE tender_id = ?", (tender_id,)).fetchone())
    if not row:
        row = generate_bid_strategy(tender_id, conn=conn)
    else:
        try:
            row["section_focus"] = json.loads(row.get("section_focus_json") or "[]")
        except json.JSONDecodeError:
            row["section_focus"] = []
        row["win_theme_items"] = _split_lines(str(row.get("win_themes") or ""))
        row["constraint_items"] = _split_lines(str(row.get("key_constraints") or ""))
        row["risk_control_items"] = _split_lines(str(row.get("risk_controls") or ""))
        row["priority_items"] = _split_lines(str(row.get("response_priorities") or ""))
        row["forbidden_items"] = _split_lines(str(row.get("forbidden_terms") or ""))
    row["markdown"] = render_bid_strategy_markdown_from_row(row)
    if own_conn:
        conn.close()
    return row


def update_bid_strategy(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    get_bid_strategy(tender_id, conn=conn)
    cleaned: dict[str, Any] = {}
    for field in STRATEGY_FIELDS:
        if field not in data:
            continue
        if field == "section_focus_json" and not isinstance(data.get(field), str):
            cleaned[field] = json.dumps(data.get(field) or [], ensure_ascii=False)
        else:
            cleaned[field] = str(data.get(field) or "").strip()
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE bid_strategies
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE tender_id = ?
                """,
                (*cleaned.values(), tender_id),
            )
    result = get_bid_strategy(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def strategy_context_text(strategy: dict[str, Any]) -> str:
    if not strategy:
        return ""
    lines = [
        f"总体定位：{strategy.get('positioning') or ''}",
        "核心卖点：",
        str(strategy.get("win_themes") or ""),
        "关键约束：",
        str(strategy.get("key_constraints") or ""),
        "风险控制：",
        str(strategy.get("risk_controls") or ""),
        "响应优先级：",
        str(strategy.get("response_priorities") or ""),
        f"写作口径：{strategy.get('writing_tone') or ''}",
    ]
    section_focus = strategy.get("section_focus") or []
    if section_focus:
        lines.append("章节重点：")
        for item in section_focus[:12]:
            lines.append(f"- {item.get('section_title')}: {item.get('focus')}")
    return "\n".join(line for line in lines if str(line).strip()).strip()


def section_strategy_focus(strategy: dict[str, Any], section_title: str) -> str:
    title = str(section_title or "")
    for item in strategy.get("section_focus") or []:
        if item.get("section_title") == title:
            return str(item.get("focus") or "")
    return ""


def render_bid_strategy_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    strategy = get_bid_strategy(tender_id, conn=conn)
    markdown = render_bid_strategy_markdown_from_row(strategy)
    if own_conn:
        conn.close()
    return markdown


def render_bid_strategy_markdown_from_row(strategy: dict[str, Any]) -> str:
    lines = [
        "# 投标响应策略",
        "",
        f"- 状态：{strategy.get('status') or ''}",
        f"- 更新时间：{strategy.get('updated_at') or strategy.get('created_at') or ''}",
        "",
        "## 总体定位",
        "",
        str(strategy.get("positioning") or ""),
        "",
        "## 核心卖点",
        "",
        str(strategy.get("win_themes") or ""),
        "",
        "## 关键约束",
        "",
        str(strategy.get("key_constraints") or ""),
        "",
        "## 风险控制",
        "",
        str(strategy.get("risk_controls") or ""),
        "",
        "## 响应优先级",
        "",
        str(strategy.get("response_priorities") or ""),
        "",
        "## 写作口径",
        "",
        str(strategy.get("writing_tone") or ""),
        "",
        "## 章节重点",
    ]
    for item in strategy.get("section_focus") or []:
        lines.append(f"- {item.get('order_no')}. {item.get('section_title')}：{item.get('focus')}")
    lines.extend(["", "## 检索关键词", "", str(strategy.get("reference_keywords") or "")])
    lines.extend(["", "## 禁用/慎用表述", "", str(strategy.get("forbidden_terms") or "")])
    if strategy.get("notes"):
        lines.extend(["", "## 备注", "", str(strategy.get("notes") or "")])
    return "\n".join(lines).strip() + "\n"
