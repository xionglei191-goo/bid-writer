from __future__ import annotations

import re
import sqlite3
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect, row_to_dict, rows_to_dicts
from .feedback import feedback_summary
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


RETROSPECTIVE_FIELDS = (
    "status",
    "actual_price",
    "actual_cost",
    "work_hours",
    "revision_count",
    "satisfaction",
    "risk_level",
    "reusable_score",
    "industry_tags",
    "reusable_assets",
    "lessons",
    "next_action",
)


def _number(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _money(value: Any) -> float | None:
    return _number(value)


def _clean_payload(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field in RETROSPECTIVE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "work_hours":
            cleaned[field] = float(value) if value not in ("", None) else None
        elif field in {"revision_count", "reusable_score"}:
            cleaned[field] = int(value) if value not in ("", None) else None
        else:
            cleaned[field] = str(value or "").strip()
    return cleaned


def _latest_closure(conn: sqlite3.Connection, tender_id: int) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM closure_records
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    ) or {}


def _delivery_counts(conn: sqlite3.Connection, tender_id: int) -> dict[str, int]:
    row = row_to_dict(
        conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status IN ('已交付', '已结案') THEN 1 ELSE 0 END) AS delivered,
                SUM(CASE WHEN status = '已结案' THEN 1 ELSE 0 END) AS closed
            FROM delivery_records
            WHERE tender_id = ?
            """,
            (tender_id,),
        ).fetchone()
    ) or {}
    return {key: int(row.get(key) or 0) for key in ("total", "delivered", "closed")}


def _latest_delivery(conn: sqlite3.Connection, tender_id: int) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM delivery_records
            WHERE tender_id = ?
            ORDER BY exported_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    ) or {}


def _default_risk(feedback: dict[str, Any], delivery: dict[str, int], closure: dict[str, Any]) -> str:
    if int(feedback.get("open") or 0):
        return "高"
    if int(feedback.get("total") or 0) >= 3 or delivery.get("total", 0) >= 3:
        return "中"
    if str(closure.get("status") or "") == "客户已确认":
        return "低"
    return "待评估"


def _default_score(feedback: dict[str, Any], coverage: dict[str, Any], closure: dict[str, Any]) -> int:
    summary = coverage.get("summary") or {}
    score = 3
    if str(closure.get("status") or "") == "客户已确认":
        score += 1
    if int(feedback.get("open") or 0):
        score -= 1
    if int(summary.get("generated_sections") or 0) >= 8:
        score += 1
    if int(summary.get("high_priority_missing") or 0):
        score -= 1
    return max(1, min(5, score))


def _recommendation(
    retro: dict[str, Any],
    feedback: dict[str, Any],
    closure: dict[str, Any],
    coverage: dict[str, Any],
) -> str:
    status = str(retro.get("status") or "待复盘")
    if int(feedback.get("open") or 0):
        return "先关闭客户反馈，再做项目复盘。"
    if str(closure.get("status") or "") != "客户已确认":
        return "先完成客户结案确认，再沉淀经验。"
    if status != "已复盘":
        return "补充成交价、耗时、返工次数、经验标签和可复用资产。"
    score = int(retro.get("reusable_score") or 0)
    if score >= 4:
        return "建议沉淀为同类项目模板和报价参考。"
    generated = int((coverage.get("summary") or {}).get("generated_sections") or 0)
    return "建议保留为案例参考。" if generated else "建议补充成稿内容后再作为案例。"


def ensure_project_retrospective(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    row = row_to_dict(conn.execute("SELECT * FROM project_retrospectives WHERE tender_id = ?", (tender_id,)).fetchone())
    if not row:
        task = get_production_task(tender_id, conn=conn)
        feedback = feedback_summary(tender_id, conn=conn)
        coverage = build_coverage_report(tender_id, conn=conn)
        closure = _latest_closure(conn, tender_id)
        delivery = _delivery_counts(conn, tender_id)
        with conn:
            cur = conn.execute(
                """
                INSERT INTO project_retrospectives (
                    tender_id, actual_price, revision_count, risk_level,
                    reusable_score, industry_tags, next_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tender_id,
                    str(task.get("budget") or ""),
                    int(feedback.get("total") or 0),
                    _default_risk(feedback, delivery, closure),
                    _default_score(feedback, coverage, closure),
                    str(tender.get("industry") or ""),
                    "补充成交、成本、耗时和可复用经验。",
                ),
            )
        row = row_to_dict(conn.execute("SELECT * FROM project_retrospectives WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def update_project_retrospective(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = ensure_project_retrospective(tender_id, conn=conn)
    cleaned = _clean_payload(data)
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        values = [*cleaned.values(), current["id"]]
        with conn:
            conn.execute(
                f"""
                UPDATE project_retrospectives
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values,
            )
    result = build_project_retrospective(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def build_project_retrospective(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    retro = ensure_project_retrospective(tender_id, conn=conn)
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    delivery = _delivery_counts(conn, tender_id)
    latest_delivery = _latest_delivery(conn, tender_id)
    closure = _latest_closure(conn, tender_id)
    coverage = build_coverage_report(tender_id, conn=conn)
    price = _money(retro.get("actual_price") or task.get("budget"))
    cost = _money(retro.get("actual_cost"))
    hours = _number(retro.get("work_hours"))
    margin = price - cost if price is not None and cost is not None else None
    hourly = price / hours if price is not None and hours and hours > 0 else None
    recommendation = _recommendation(retro, feedback, closure, coverage)
    summary = {
        "status": retro.get("status") or "待复盘",
        "actual_price_value": price,
        "actual_cost_value": cost,
        "gross_margin_value": margin,
        "hourly_revenue_value": hourly,
        "feedback_total": feedback.get("total", 0),
        "feedback_open": feedback.get("open", 0),
        "delivery_total": delivery["total"],
        "delivered_total": delivery["delivered"],
        "closure_status": closure.get("status") or "未结案",
        "risk_level": retro.get("risk_level") or _default_risk(feedback, delivery, closure),
        "reusable_score": retro.get("reusable_score") or _default_score(feedback, coverage, closure),
        "can_archive_case": str(closure.get("status") or "") == "客户已确认" and int(feedback.get("open") or 0) == 0,
        "recommendation": recommendation,
        "generated_sections": (coverage.get("summary") or {}).get("generated_sections", 0),
        "total_sections": (coverage.get("summary") or {}).get("total_sections", 0),
    }
    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "task": task,
        "profile": profile,
        "retrospective": retro,
        "feedback": feedback,
        "delivery": {"counts": delivery, "latest": latest_delivery},
        "closure": closure,
        "coverage": {"summary": coverage.get("summary") or {}},
        "summary": summary,
    }
    result["markdown"] = render_project_retrospective_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_project_retrospective_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    task = report.get("task") or {}
    retro = report.get("retrospective") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 项目复盘台账",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 行业：{tender.get('industry') or '未登记'}",
        f"- 客户：{task.get('customer_name') or '未登记'}",
        f"- 来源平台：{task.get('source_platform') or '未登记'}",
        f"- 订单号：{task.get('order_no') or '未登记'}",
        "",
        "## 经营数据",
        f"- 复盘状态：{summary.get('status')}",
        f"- 成交价：{retro.get('actual_price') or task.get('budget') or '未登记'}",
        f"- 成本：{retro.get('actual_cost') or '未登记'}",
        f"- 耗时：{retro.get('work_hours') or '未登记'} 小时",
        f"- 毛利：{summary.get('gross_margin_value') if summary.get('gross_margin_value') is not None else '未计算'}",
        f"- 小时收入：{round(float(summary.get('hourly_revenue_value')), 2) if summary.get('hourly_revenue_value') is not None else '未计算'}",
        "",
        "## 生产质量",
        f"- 交付次数：{summary.get('delivery_total', 0)}",
        f"- 返工/反馈：{summary.get('feedback_total', 0)} 条，未处理 {summary.get('feedback_open', 0)} 条",
        f"- 结案状态：{summary.get('closure_status')}",
        f"- 风险等级：{summary.get('risk_level')}",
        f"- 可复用评分：{summary.get('reusable_score')}/5",
        f"- 成稿章节：{summary.get('generated_sections')}/{summary.get('total_sections')}",
        "",
        "## 经验沉淀",
        f"- 行业标签：{retro.get('industry_tags') or '未登记'}",
        f"- 可复用资产：{retro.get('reusable_assets') or '未登记'}",
        f"- 经验教训：{retro.get('lessons') or '未登记'}",
        f"- 下一步：{retro.get('next_action') or summary.get('recommendation') or '未登记'}",
    ]
    return "\n".join(lines).strip() + "\n"


def build_retrospective_dashboard(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT
                t.id,
                t.name,
                t.industry,
                COALESCE(pt.customer_name, '') AS customer_name,
                COALESCE(pt.source_platform, '') AS source_platform,
                COALESCE(pt.budget, '') AS budget,
                COALESCE(pr.status, '待复盘') AS retrospective_status,
                COALESCE(pr.actual_price, '') AS actual_price,
                COALESCE(pr.actual_cost, '') AS actual_cost,
                pr.work_hours,
                COALESCE(pr.risk_level, '') AS risk_level,
                pr.reusable_score,
                COALESCE(pr.industry_tags, '') AS industry_tags,
                (SELECT COUNT(*) FROM feedback_items fi WHERE fi.tender_id = t.id) AS feedback_total,
                (SELECT COUNT(*) FROM feedback_items fi WHERE fi.tender_id = t.id AND fi.status <> '已解决') AS feedback_open,
                (SELECT COUNT(*) FROM delivery_records dr WHERE dr.tender_id = t.id) AS delivery_total,
                (SELECT COUNT(*) FROM closure_records cr WHERE cr.tender_id = t.id AND cr.status = '客户已确认') AS closure_total
            FROM tenders t
            LEFT JOIN production_tasks pt ON pt.tender_id = t.id
            LEFT JOIN project_retrospectives pr ON pr.tender_id = t.id
            ORDER BY t.id DESC
            """
        ).fetchall()
    )
    total_revenue = 0.0
    total_margin = 0.0
    margin_count = 0
    reviewed = 0
    pending_review = 0
    high_risk = 0
    reusable = 0
    items: list[dict[str, Any]] = []
    for row in rows:
        price = _money(row.get("actual_price") or row.get("budget")) or 0.0
        cost = _money(row.get("actual_cost"))
        total_revenue += price
        margin = None
        if cost is not None:
            margin = price - cost
            total_margin += margin
            margin_count += 1
        status = str(row.get("retrospective_status") or "待复盘")
        closure_total = int(row.get("closure_total") or 0)
        if status == "已复盘":
            reviewed += 1
        elif closure_total:
            pending_review += 1
        if str(row.get("risk_level") or "") == "高":
            high_risk += 1
        if int(row.get("reusable_score") or 0) >= 4:
            reusable += 1
        items.append(
            {
                **row,
                "actual_price_value": price,
                "gross_margin_value": margin,
                "needs_review": bool(closure_total and status != "已复盘"),
            }
        )
    result = {
        "summary": {
            "total": len(items),
            "reviewed": reviewed,
            "pending_review": pending_review,
            "high_risk": high_risk,
            "reusable_cases": reusable,
            "total_revenue": round(total_revenue, 2),
            "total_margin": round(total_margin, 2) if margin_count else None,
        },
        "items": items,
    }
    if own_conn:
        conn.close()
    return result
