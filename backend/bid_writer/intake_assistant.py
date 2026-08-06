from __future__ import annotations

import re
import sqlite3
from math import ceil
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .pricing import COMPLEX_WORDS, LIGHT_WORDS, RUSH_WORDS, calculate_price_quote_from_context
from .production_tasks import get_production_task, update_production_task
from .project_profiles import get_project_profile
from .tenders import create_tender, get_tender, parse_tender


def _text_blob(*items: Any) -> str:
    return "\n".join(str(item or "") for item in items if item not in (None, ""))


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    normalized = text.lower().replace(" ", "")
    return any(word.lower().replace(" ", "") in normalized for word in words)


def _extract_deadline(text: str) -> str:
    patterns = (
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?\s*\d{0,2}:?\d{0,2})",
        r"(\d{1,2}月\d{1,2}[日号]?\s*\d{0,2}:?\d{0,2})",
        r"(今晚|今天|明天|后天|本周[内前]?|周[一二三四五六日天])",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_budget(text: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(元|块|k|K|千|万)", text)
    if not match:
        return ""
    amount, unit = match.groups()
    return f"{amount}{unit}"


def _project_name_from_message(message: str, fallback: str = "") -> str:
    patterns = (
        r"(?:项目名称|工程名称|招标项目名称)[:：\s]+(.{4,80})",
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{4,60}(?:项目|工程|技术标|施工组织设计))",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1).strip(" ，,。；;：:")
    return fallback or "客户接单草稿"


def _round_price(value: int) -> int:
    return int(ceil(value / 50) * 50)


def _project_type(profile: dict[str, Any], tender: dict[str, Any], customer_message: str) -> str:
    blob = _text_blob(
        profile.get("project_type"),
        profile.get("industry"),
        tender.get("industry"),
        tender.get("name"),
        customer_message,
        tender.get("raw_text"),
    )
    mapping = (
        ("医院", "医院"),
        ("医疗", "医院"),
        ("学校", "学校"),
        ("教学", "学校"),
        ("厂房", "厂房"),
        ("洁净", "厂房"),
        ("市政", "市政"),
        ("道路", "市政"),
        ("桥梁", "市政"),
        ("水利", "水利"),
        ("泵站", "水利"),
        ("改造", "改造"),
        ("装修", "装饰装修"),
    )
    for keyword, label in mapping:
        if keyword in blob:
            return label
    return str(profile.get("project_type") or tender.get("industry") or "通用工程")


def _requirements(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    return rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())


def _plan_count(conn: sqlite3.Connection, tender_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM section_plans WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _draft_count(conn: sqlite3.Connection, tender_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM drafts WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _material_gap_count(materials: list[dict[str, str]]) -> int:
    return sum(1 for item in materials if item["status"] not in {"已具备", "已识别", "已登记"})


def _missing_materials(
    tender: dict[str, Any],
    task: dict[str, Any],
    profile: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[dict[str, str]]:
    raw_text_length = len(str(tender.get("raw_text") or "").strip())
    materials = [
        {
            "name": "完整招标文件",
            "status": "已具备" if tender.get("file_path") or raw_text_length >= 800 else "待补充",
            "reason": "用于解析评分办法、目录要求和技术条款。",
        },
        {
            "name": "评分办法与技术评审标准",
            "status": "已识别" if any(item.get("kind") == "评分点" for item in requirements) else "待确认",
            "reason": "决定章节优先级和响应深度。",
        },
        {
            "name": "项目基础资料",
            "status": "已登记"
            if profile.get("project_type") and (profile.get("building_area") or profile.get("contract_scope"))
            else "待补充",
            "reason": "包括工程类型、建设规模、承包范围、结构形式和特殊要求。",
        },
        {
            "name": "工期、质量、安全目标",
            "status": "已登记" if task.get("deadline") and profile.get("quality_target") and profile.get("safety_target") else "待补充",
            "reason": "技术标进度、质量、安全章节需要准确响应。",
        },
        {
            "name": "企业模板或历史偏好",
            "status": "待确认",
            "reason": "用于统一封面、页眉页脚、字体、目录和常用承诺口径。",
        },
        {
            "name": "图纸、清单或现场条件",
            "status": "待确认",
            "reason": "用于工程重难点、施工部署、总平面和主要工艺深化。",
        },
    ]
    return materials


def _estimate(
    tender: dict[str, Any],
    profile: dict[str, Any],
    requirements: list[dict[str, Any]],
    plan_count: int,
    customer_message: str,
    materials: list[dict[str, str]],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    return calculate_price_quote_from_context(
        tender,
        profile,
        requirements,
        plan_count,
        customer_message,
        material_gap_count=_material_gap_count(materials),
        conn=conn,
    )


def _acceptance(
    estimate: dict[str, Any],
    missing_materials: list[dict[str, str]],
    task: dict[str, Any],
    customer_message: str,
) -> dict[str, Any]:
    pending_materials = [item["name"] for item in missing_materials if item["status"] != "已具备" and item["status"] != "已识别" and item["status"] != "已登记"]
    rush = _contains_any(customer_message, RUSH_WORDS)
    if estimate["requirement_count"] == 0 and "完整招标文件" in pending_materials:
        decision = "暂缓接单"
        reason = "尚未拿到完整招标文件，无法判断技术标范围和废标风险。"
    elif rush and len(pending_materials) >= 3:
        decision = "谨慎承接"
        reason = "客户要求较急，但关键资料仍不完整，需先确认资料和交付边界。"
    elif len(pending_materials) >= 4:
        decision = "谨慎承接"
        reason = "资料缺口较多，报价和工期需要留出复核余量。"
    else:
        decision = "可承接"
        reason = "已有基础招标信息，可进入资料确认、报价和生产排期。"
    if not task.get("deadline") and not _extract_deadline(customer_message):
        reason += " 交付期限仍需客户确认。"
    return {
        "decision": decision,
        "reason": reason,
        "pending_materials": pending_materials,
        "rush": rush,
    }


def _risks(
    acceptance: dict[str, Any],
    estimate: dict[str, Any],
    customer_message: str,
) -> list[dict[str, str]]:
    risks = [
        {
            "level": "high" if acceptance["decision"] == "暂缓接单" else "medium",
            "title": "资料完整性",
            "detail": "未拿到完整招标文件、评分办法或项目资料时，不建议承诺最终定稿质量。",
        },
        {
            "level": "medium",
            "title": "人工复核",
            "detail": "技术标初稿必须人工检查项目名称、工期目标、质量安全承诺和引用来源。",
        },
        {
            "level": "medium",
            "title": "平台合规",
            "detail": "系统只生成回复和交付材料，接单、付款、发货仍需人工确认并遵守平台规则。",
        },
    ]
    if acceptance.get("rush"):
        risks.insert(
            1,
            {
                "level": "high",
                "title": "加急交付",
                "detail": f"预计工作量 {estimate['workload']}，加急单需先确认资料齐全和返工次数。",
            },
        )
    if "中标" in customer_message or "保证" in customer_message:
        risks.append(
            {
                "level": "high",
                "title": "承诺边界",
                "detail": "不要承诺中标结果，只承诺按招标文件完成技术标编制和修改配合。",
            }
        )
    return risks


def _reply_message(
    tender: dict[str, Any],
    task: dict[str, Any],
    profile: dict[str, Any],
    estimate: dict[str, Any],
    acceptance: dict[str, Any],
    materials: list[dict[str, str]],
) -> str:
    customer = str(task.get("customer_name") or "您好")
    project_name = str(profile.get("project_name") or tender.get("name") or "本项目")
    pending = [item["name"] for item in materials if item["status"] in {"待补充", "待确认"}]
    pending_text = "、".join(pending[:5]) if pending else "目前资料基本够用"
    return "\n".join(
        [
            f"{customer}，已收到 {project_name} 的技术标编制需求。",
            f"初步判断：{acceptance['decision']}。{acceptance['reason']}",
            f"建议报价区间：{estimate['suggested_price']}，预计工作量：{estimate['workload']}，建议交付周期：{estimate['turnaround']}。",
            f"接单前还需要确认：{pending_text}。",
            "交付内容建议为：技术标 Word 初稿、Markdown 备份、响应覆盖检查、交付审查报告和 ZIP 归档包。",
            "我这边可以先按招标文件做目录和章节初稿，最终提交前会保留人工复核环节；不承诺中标结果，可配合合理修改。",
        ]
    )


def build_intake_assistant(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    payload = data or {}
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    requirements = _requirements(conn, tender_id)
    plan_count = _plan_count(conn, tender_id)
    draft_count = _draft_count(conn, tender_id)
    customer_message = str(payload.get("customer_message") or task.get("delivery_notes") or tender.get("raw_text") or "")
    deadline = str(payload.get("deadline") or task.get("deadline") or _extract_deadline(customer_message))
    budget_expectation = str(payload.get("budget_expectation") or task.get("budget") or _extract_budget(customer_message))
    source_platform = str(payload.get("source_platform") or task.get("source_platform") or "闲鱼")
    deliverable_format = str(payload.get("deliverable_format") or task.get("deliverable_format") or "DOCX + ZIP 交付包")
    project_type = _project_type(profile, tender, customer_message)
    materials = _missing_materials(tender, task | {"deadline": deadline}, profile, requirements)
    estimate = _estimate(tender, profile, requirements, plan_count, customer_message, materials, conn)
    acceptance = _acceptance(estimate, materials, task | {"deadline": deadline}, customer_message)
    risks = _risks(acceptance, estimate, customer_message)
    reply = _reply_message(tender, task, profile, estimate, acceptance, materials)
    suggested_notes = "\n".join(
        [
            f"接单评估：{acceptance['decision']}。{acceptance['reason']}",
            f"报价建议：{estimate['suggested_price']}；预计工作量：{estimate['workload']}；交付周期：{estimate['turnaround']}。",
            f"待确认资料：{'、'.join(acceptance['pending_materials']) or '无明显缺口'}。",
        ]
    )
    result = {
        "tender_id": tender_id,
        "project": {
            "name": profile.get("project_name") or tender.get("name") or "",
            "type": project_type,
            "industry": profile.get("industry") or tender.get("industry") or "",
            "region": profile.get("region") or tender.get("region") or "",
        },
        "input": {
            "customer_message": customer_message,
            "source_platform": source_platform,
            "deadline": deadline,
            "budget_expectation": budget_expectation,
            "deliverable_format": deliverable_format,
        },
        "estimate": estimate | {"draft_count": draft_count},
        "acceptance": acceptance,
        "materials": materials,
        "risks": risks,
        "reply_message": reply,
        "internal_note": suggested_notes,
        "suggested_task": {
            "source_platform": source_platform,
            "deadline": deadline,
            "budget": budget_expectation or estimate["suggested_price"],
            "deliverable_format": deliverable_format,
            "delivery_status": "待接单确认" if acceptance["decision"] != "暂缓接单" else "待补资料",
            "delivery_notes": suggested_notes,
        },
    }
    if own_conn:
        conn.close()
    return result


def render_intake_markdown(report: dict[str, Any]) -> str:
    estimate = report.get("estimate", {})
    acceptance = report.get("acceptance", {})
    project = report.get("project", {})
    lines = [
        "# 接单评估",
        "",
        f"- 项目名称：{project.get('name') or ''}",
        f"- 项目类型：{project.get('type') or ''}",
        f"- 接单判断：{acceptance.get('decision') or ''}",
        f"- 判断原因：{acceptance.get('reason') or ''}",
        f"- 建议报价：{estimate.get('suggested_price') or ''}",
        f"- 预计工作量：{estimate.get('workload') or ''}",
        f"- 建议交付周期：{estimate.get('turnaround') or ''}",
        "",
        "## 资料清单",
    ]
    for item in report.get("materials", []):
        lines.append(f"- {item.get('name')}：{item.get('status')}。{item.get('reason')}")
    lines.extend(["", "## 风险提示"])
    for item in report.get("risks", []):
        lines.append(f"- {item.get('level')} / {item.get('title')}：{item.get('detail')}")
    lines.extend(["", "## 客户回复", "", report.get("reply_message") or "", "", "## 内部备注", "", report.get("internal_note") or ""])
    return "\n".join(lines).strip() + "\n"


def create_intake_tender(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    message = str(data.get("customer_message") or "").strip()
    if not message:
        raise ValueError("Customer message is required")
    project_name = str(data.get("project_name") or "").strip() or _project_name_from_message(message)
    industry = str(data.get("industry") or "")
    region = str(data.get("region") or "")
    tender = create_tender(project_name, text=message, industry=industry, region=region, conn=conn)
    tender_id = int(tender["id"])
    initial_task = {
        "customer_name": str(data.get("customer_name") or "").strip(),
        "source_platform": str(data.get("source_platform") or "闲鱼").strip(),
        "contact": str(data.get("contact") or "").strip(),
        "deadline": str(data.get("deadline") or _extract_deadline(message)).strip(),
        "budget": str(data.get("budget_expectation") or _extract_budget(message)).strip(),
        "deliverable_format": str(data.get("deliverable_format") or "DOCX + ZIP 交付包").strip(),
        "delivery_status": "待接单确认",
        "delivery_notes": message,
        "internal_owner": str(data.get("internal_owner") or "").strip(),
    }
    task = update_production_task(tender_id, initial_task, conn=conn)
    parsed = parse_tender(tender_id, conn=conn)
    report = build_intake_assistant(tender_id, data, conn=conn)
    conn.execute(
        """
        INSERT INTO customer_communications (
            tender_id, stage, direction, channel, customer_message, system_reply, status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tender_id,
            "询盘",
            "outgoing",
            initial_task["source_platform"],
            message,
            report.get("reply_message") or "",
            "待发送",
            "订单草稿创建时自动保存的首条询盘记录。",
        ),
    )
    suggested_task = dict(report.get("suggested_task") or {})
    suggested_task.update(
        {
            "customer_name": initial_task["customer_name"],
            "source_platform": initial_task["source_platform"],
            "contact": initial_task["contact"],
            "deadline": initial_task["deadline"] or suggested_task.get("deadline", ""),
            "budget": initial_task["budget"] or suggested_task.get("budget", ""),
            "deliverable_format": initial_task["deliverable_format"],
            "delivery_notes": report.get("internal_note") or message,
            "internal_owner": initial_task["internal_owner"],
        }
    )
    task = update_production_task(tender_id, suggested_task, conn=conn)
    result = {
        "tender": get_tender(tender_id, conn=conn),
        "task": task,
        "parsed": parsed,
        "intake": report,
    }
    if own_conn:
        conn.close()
    return result
