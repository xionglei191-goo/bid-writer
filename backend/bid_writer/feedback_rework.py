from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .draft_versions import record_draft_version
from .feedback import list_feedback_items, update_feedback_item
from .planner import generate_from_plan
from .production_tasks import get_production_task


SECTION_HINTS = (
    ("施工工艺及主要施工方法", ("工艺", "施工方法", "测量", "主体", "机电", "装饰", "防水", "土方", "专项")),
    ("施工总体部署", ("部署", "组织", "资源", "流水", "总体")),
    ("工程重点难点分析及对策", ("重难点", "重点", "难点", "风险", "对策")),
    ("质量保证措施", ("质量", "验收", "样板", "检测")),
    ("安全文明施工及环境保护", ("安全", "文明", "环保", "绿色", "扬尘", "应急")),
    ("施工进度计划及保证措施", ("进度", "工期", "节点", "计划")),
    ("施工总平面布置", ("平面", "临设", "临水", "临电", "场地")),
    ("BIM及智慧建造应用", ("BIM", "智慧", "信息化", "模型")),
    ("总承包管理与协调", ("总承包", "协调", "分包", "界面")),
    ("工程概况", ("概况", "规模", "范围", "现场条件")),
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _load_sections(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    planned = rows_to_dicts(
        conn.execute(
            """
            SELECT
                sp.id AS plan_id,
                sp.order_no,
                sp.section_title,
                sp.draft_id,
                d.status AS draft_status,
                LENGTH(d.content) AS draft_chars
            FROM section_plans sp
            LEFT JOIN drafts d ON d.id = sp.draft_id
            WHERE sp.tender_id = ?
            ORDER BY sp.order_no, sp.id
            """,
            (tender_id,),
        ).fetchall()
    )
    if planned:
        return planned
    return rows_to_dicts(
        conn.execute(
            """
            SELECT
                NULL AS plan_id,
                NULL AS order_no,
                section_title,
                id AS draft_id,
                status AS draft_status,
                LENGTH(content) AS draft_chars
            FROM drafts
            WHERE tender_id = ?
            ORDER BY id
            """,
            (tender_id,),
        ).fetchall()
    )


def _score_section(feedback: dict[str, Any], section: dict[str, Any]) -> int:
    related = _clean(feedback.get("related_section"))
    text = f"{related}\n{_clean(feedback.get('feedback_text'))}\n{_clean(feedback.get('action_plan'))}"
    title = _clean(section.get("section_title"))
    score = 0
    if related and (related in title or title in related):
        score += 10
    if title and title in text:
        score += 8
    for canonical, terms in SECTION_HINTS:
        if canonical == title:
            score += sum(2 for term in terms if term and term in text)
    for token in ("质量", "安全", "工期", "进度", "机电", "施工", "资料", "格式", "目录"):
        if token in title and token in text:
            score += 1
    return score


def _target_sections(feedback: dict[str, Any], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [(section, _score_section(feedback, section)) for section in sections]
    matches = [section for section, score in sorted(scored, key=lambda item: item[1], reverse=True) if score > 0]
    if not matches and sections:
        matches = [sections[0]]
    return [
        {
            "plan_id": item.get("plan_id"),
            "order_no": item.get("order_no"),
            "section_title": item.get("section_title") or "待确认章节",
            "draft_id": item.get("draft_id"),
            "draft_status": item.get("draft_status") or "未生成",
            "draft_chars": item.get("draft_chars") or 0,
        }
        for item in matches[:3]
    ]


def _action_plan(feedback: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    text = _clean(feedback.get("feedback_text"))
    section_text = "、".join(item["section_title"] for item in targets) if targets else "相关章节"
    return (
        f"围绕“{text}”处理 {section_text}：补充客户要求内容，复核招标条款响应、项目名称、工期质量安全目标、"
        "引用来源和格式层级；处理完成后重新导出客户发货包并发起客户确认。"
    )


def _feedback_marker(feedback_id: int) -> str:
    return f"<!-- feedback-rework:{feedback_id} -->"


def _supplement_text(item: dict[str, Any], section_title: str) -> str:
    feedback_text = _clean(item.get("feedback_text"))
    action_plan = _clean(item.get("action_plan")) or _clean(item.get("suggested_action_plan"))
    return "\n".join(
        [
            _feedback_marker(int(item["id"])),
            f"## 客户反馈响应补充（反馈 #{item['id']}）",
            "",
            f"针对客户反馈“{feedback_text}”，本章“{section_title}”补充如下响应内容：",
            "",
            f"- 按反馈要求补充和复核：{action_plan or feedback_text}",
            "- 复核本章与招标文件、项目名称、工期、质量目标、安全目标和专项要求的一致性。",
            "- 处理完成后需人工通读本章，确认表述准确、格式统一、无历史项目残留，再重新导出客户发货包。",
        ]
    )


def _ensure_draft_for_target(
    target: dict[str, Any],
    generate_missing_drafts: bool,
    conn: sqlite3.Connection,
) -> tuple[dict[str, Any] | None, bool]:
    draft_id = target.get("draft_id")
    if draft_id:
        draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (int(draft_id),)).fetchone())
        return draft, False
    plan_id = target.get("plan_id")
    if generate_missing_drafts and plan_id:
        generated = generate_from_plan(int(plan_id), conn=conn)
        draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (int(generated["id"]),)).fetchone())
        return draft, True
    return None, False


def _priority_rank(value: str) -> int:
    return {"high": 0, "normal": 1, "medium": 1, "low": 2}.get(value, 1)


def _customer_message(tender: dict[str, Any], task: dict[str, Any], items: list[dict[str, Any]], extra_note: str = "") -> str:
    customer = task.get("customer_name") or "您好"
    project_name = tender.get("name") or "本项目"
    if not items:
        lines = [
            f"{customer}，您好。",
            f"{project_name} 当前没有未处理修改意见。",
            "如后续需要新增章节、调整格式或补充专项内容，可以继续发我，我会按反馈处理。",
        ]
    else:
        lines = [
            f"{customer}，您好。",
            f"{project_name} 的修改意见已收到，我会按以下范围处理：",
        ]
        for index, item in enumerate(items[:5], 1):
            targets = "、".join(section["section_title"] for section in item.get("target_sections") or []) or "相关章节"
            lines.append(f"{index}. {item.get('feedback_text')}（涉及：{targets}）")
        lines.extend(
            [
                "处理完成后我会重新整理客户版 Word 初稿和 Markdown 备份，并发您确认。",
                "本次调整默认限于原招标文件和本次订单范围内；新增范围或重大改版会先单独确认。",
            ]
        )
    if extra_note:
        lines.append(f"补充说明：{extra_note}")
    return "\n".join(lines)


def render_feedback_rework_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 客户反馈返工处理单",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        "",
        "## 返工概览",
        f"- 反馈总数：{summary.get('total_feedback', 0)}",
        f"- 未处理反馈：{summary.get('open_feedback', 0)}",
        f"- 高优先级：{summary.get('high_priority', 0)}",
        f"- 影响章节：{summary.get('affected_sections', 0)}",
        f"- 当前状态：{summary.get('rework_status') or '待确认'}",
        "",
        "## 处理明细",
    ]
    items = report.get("items") or []
    if not items:
        lines.append("- 暂无未处理反馈。")
    for item in items:
        targets = "、".join(section["section_title"] for section in item.get("target_sections") or []) or "待确认章节"
        lines.append(f"- #{item.get('id')} [{item.get('priority')}] {item.get('feedback_text')}")
        lines.append(f"  - 涉及章节：{targets}")
        lines.append(f"  - 处理计划：{item.get('suggested_action_plan')}")
    lines.extend(["", "## 客户回复话术", "", report.get("customer_message") or ""])
    return "\n".join(lines).strip() + "\n"


def build_feedback_rework(
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
    feedback_items = list_feedback_items(tender_id, conn=conn)
    open_items = [item for item in feedback_items if item.get("status") != "已解决"]
    sections = _load_sections(conn, tender_id)
    items: list[dict[str, Any]] = []
    affected: set[str] = set()
    for item in sorted(open_items, key=lambda row: (_priority_rank(_clean(row.get("priority"))), row.get("id") or 0)):
        targets = _target_sections(item, sections)
        affected.update(section["section_title"] for section in targets)
        action_plan = _action_plan(item, targets)
        items.append(
            {
                **item,
                "target_sections": targets,
                "suggested_action_plan": action_plan,
                "needs_draft_update": bool(targets),
            }
        )
    high_priority = sum(1 for item in open_items if _clean(item.get("priority")) == "high")
    rework_status = "待处理返工" if open_items else "暂无返工"
    report = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "task": task,
        "summary": {
            "total_feedback": len(feedback_items),
            "open_feedback": len(open_items),
            "resolved_feedback": len(feedback_items) - len(open_items),
            "high_priority": high_priority,
            "affected_sections": len(affected),
            "rework_status": rework_status,
            "can_prepare_rework": bool(open_items),
        },
        "items": items,
        "customer_message": _customer_message(tender, task, items, _clean(payload.get("extra_note"))),
    }
    report["markdown"] = render_feedback_rework_markdown(report)
    if own_conn:
        conn.close()
    return report


def apply_feedback_rework_plan(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    payload = data or {}
    owner = _clean(payload.get("owner"))
    overwrite = bool(payload.get("overwrite_action_plan"))
    report = build_feedback_rework(tender_id, payload, conn=conn)
    applied = 0
    for item in report.get("items") or []:
        update: dict[str, Any] = {"status": "处理中"}
        if owner:
            update["owner"] = owner
        if overwrite or not _clean(item.get("action_plan")):
            update["action_plan"] = item.get("suggested_action_plan") or ""
        update_feedback_item(int(item["id"]), update, conn=conn)
        applied += 1
    result = build_feedback_rework(tender_id, payload, conn=conn)
    result["summary"]["applied_updates"] = applied
    result["markdown"] = render_feedback_rework_markdown(result)
    if own_conn:
        conn.close()
    return result


def execute_feedback_rework(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    payload = data or {}
    owner = _clean(payload.get("owner"))
    generate_missing_drafts = bool(payload.get("generate_missing_drafts", True))
    overwrite = bool(payload.get("overwrite_action_plan"))
    report = apply_feedback_rework_plan(
        tender_id,
        {
            "owner": owner,
            "overwrite_action_plan": overwrite,
            "extra_note": payload.get("extra_note"),
        },
        conn=conn,
    )
    updated_drafts = 0
    generated_drafts = 0
    skipped: list[dict[str, Any]] = []
    touched: list[dict[str, Any]] = []

    for item in report.get("items") or []:
        marker = _feedback_marker(int(item["id"]))
        item_updated = False
        for target in item.get("target_sections") or []:
            draft, generated = _ensure_draft_for_target(target, generate_missing_drafts, conn)
            if not draft:
                skipped.append(
                    {
                        "feedback_id": item.get("id"),
                        "section_title": target.get("section_title"),
                        "reason": "未找到草稿，且未启用缺失草稿生成。",
                    }
                )
                continue
            content = str(draft.get("content") or "")
            if marker in content:
                skipped.append(
                    {
                        "feedback_id": item.get("id"),
                        "draft_id": draft.get("id"),
                        "section_title": draft.get("section_title") or target.get("section_title"),
                        "reason": "该反馈已写入本章，跳过重复追加。",
                    }
                )
                continue
            record_draft_version(int(draft["id"]), content, origin=f"feedback_rework_before:{item['id']}", conn=conn)
            supplement = _supplement_text(item, str(draft.get("section_title") or target.get("section_title") or "相关章节"))
            next_content = content.rstrip() + "\n\n" + supplement + "\n"
            with conn:
                conn.execute(
                    "UPDATE drafts SET content = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (next_content, "needs_revision", int(draft["id"])),
                )
            record_draft_version(int(draft["id"]), next_content, origin=f"feedback_rework:{item['id']}", conn=conn)
            updated_drafts += 1
            generated_drafts += 1 if generated else 0
            item_updated = True
            touched.append(
                {
                    "feedback_id": item.get("id"),
                    "draft_id": int(draft["id"]),
                    "section_title": draft.get("section_title") or target.get("section_title"),
                    "generated": generated,
                }
            )
        if item_updated:
            update_feedback_item(
                int(item["id"]),
                {
                    "status": "需复核",
                    "owner": owner or item.get("owner") or "",
                    "action_plan": item.get("suggested_action_plan") or item.get("action_plan") or "",
                },
                conn=conn,
            )

    result = build_feedback_rework(tender_id, payload, conn=conn)
    result["execution"] = {
        "updated_drafts": updated_drafts,
        "generated_drafts": generated_drafts,
        "skipped": skipped,
        "touched": touched,
    }
    result["summary"]["executed_updates"] = updated_drafts
    result["summary"]["generated_drafts"] = generated_drafts
    result["summary"]["skipped_updates"] = len(skipped)
    result["markdown"] = render_feedback_rework_markdown(result)
    if own_conn:
        conn.close()
    return result
