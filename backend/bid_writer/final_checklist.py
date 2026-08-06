from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .case_assets import list_case_assets
from .coverage_report import build_coverage_report
from .db import connect, row_to_dict, rows_to_dicts
from .delivery_records import list_delivery_records
from .delivery_review import build_delivery_review
from .quality_gate import build_quality_gate


DEFAULT_FINAL_CHECKS: tuple[dict[str, Any], ...] = (
    {
        "check_key": "source_verified",
        "title": "招标文件版本确认",
        "category": "资料",
        "required": 1,
    },
    {
        "check_key": "requirements_reviewed",
        "title": "响应矩阵已人工校正",
        "category": "响应",
        "required": 1,
    },
    {
        "check_key": "profile_reviewed",
        "title": "项目资料已核对",
        "category": "资料",
        "required": 1,
    },
    {
        "check_key": "section_drafts_reviewed",
        "title": "章节草稿完整性确认",
        "category": "成稿",
        "required": 1,
    },
    {
        "check_key": "citations_reviewed",
        "title": "来源引用可追溯",
        "category": "成稿",
        "required": 1,
    },
    {
        "check_key": "quality_gate_reviewed",
        "title": "质量门禁问题已处理",
        "category": "审查",
        "required": 1,
    },
    {
        "check_key": "format_reviewed",
        "title": "目录页码格式已人工终审",
        "category": "格式",
        "required": 1,
    },
    {
        "check_key": "package_exported",
        "title": "交付包已导出归档",
        "category": "交付",
        "required": 1,
    },
    {
        "check_key": "delivery_message_ready",
        "title": "客户发货说明已确认",
        "category": "交付",
        "required": 1,
    },
    {
        "check_key": "case_assets_archived",
        "title": "优质成稿已沉淀为案例资产",
        "category": "复盘",
        "required": 0,
    },
)


MANUAL_OK = {"已确认", "不适用"}


def _ensure_items(tender_id: int, conn: sqlite3.Connection) -> None:
    tender = row_to_dict(conn.execute("SELECT id FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    with conn:
        for item in DEFAULT_FINAL_CHECKS:
            conn.execute(
                """
                INSERT OR IGNORE INTO final_check_items (
                    tender_id, check_key, title, category, required, status
                )
                VALUES (?, ?, ?, ?, ?, '待确认')
                """,
                (
                    tender_id,
                    item["check_key"],
                    item["title"],
                    item["category"],
                    int(item["required"]),
                ),
            )


def _auto_map(tender_id: int, conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    coverage = build_coverage_report(tender_id, conn=conn)
    delivery_review = build_delivery_review(tender_id, conn=conn)
    quality_gate = build_quality_gate(tender_id, conn=conn)
    deliveries = list_delivery_records(tender_id, conn=conn)
    case_assets = list_case_assets(tender_id=tender_id, conn=conn)

    coverage_summary = coverage.get("summary", {})
    delivery_summary = delivery_review.get("summary", {})
    quality_summary = quality_gate.get("summary", {})
    total_requirements = int(coverage_summary.get("total_requirements") or 0)
    generated_sections = int(coverage_summary.get("generated_sections") or 0)
    total_sections = int(coverage_summary.get("total_sections") or 0)
    missing_sections = int(coverage_summary.get("missing_sections") or 0)
    high_priority_missing = int(coverage_summary.get("high_priority_missing") or 0)
    citation_missing = int(delivery_summary.get("citation_missing_sections") or 0)
    profile_missing = delivery_summary.get("profile_missing_labels") or []
    task_missing = delivery_summary.get("task_missing_labels") or []
    package_records = len(deliveries)

    return {
        "source_verified": {
            "auto_status": "complete" if not task_missing else "warning",
            "auto_detail": "生产任务关键字段已登记。" if not task_missing else f"生产任务仍缺：{', '.join(task_missing)}。",
        },
        "requirements_reviewed": {
            "auto_status": "complete" if total_requirements else "pending",
            "auto_detail": f"响应矩阵已有 {total_requirements} 条要求。" if total_requirements else "尚未形成响应矩阵。",
        },
        "profile_reviewed": {
            "auto_status": "complete" if not profile_missing else "warning",
            "auto_detail": "项目资料关键字段已补齐。" if not profile_missing else f"项目资料仍缺：{', '.join(profile_missing)}。",
        },
        "section_drafts_reviewed": {
            "auto_status": "complete" if total_sections and not missing_sections else "pending",
            "auto_detail": f"章节生成 {generated_sections}/{total_sections}，未生成 {missing_sections} 章。",
        },
        "citations_reviewed": {
            "auto_status": "complete" if generated_sections and not citation_missing else "warning",
            "auto_detail": "已生成章节均保留来源引用。" if not citation_missing else f"{citation_missing} 个章节缺少来源引用。",
        },
        "quality_gate_reviewed": {
            "auto_status": "complete" if quality_gate.get("status") in {"pass", "needs_review"} and not high_priority_missing else "warning",
            "auto_detail": f"质量分 {quality_gate.get('score', 0)}，修订任务 {quality_summary.get('task_count', 0)}，高优先级缺口 {high_priority_missing}。",
        },
        "format_reviewed": {
            "auto_status": "warning",
            "auto_detail": "格式、页码、签章和最终投标专用条款必须人工确认。",
        },
        "package_exported": {
            "auto_status": "complete" if package_records else "pending",
            "auto_detail": f"已有 {package_records} 条交付包导出记录。" if package_records else "尚未导出 ZIP 交付包。",
        },
        "delivery_message_ready": {
            "auto_status": "complete" if delivery_review.get("summary", {}).get("export_ready") else "warning",
            "auto_detail": delivery_review.get("summary", {}).get("readiness_label") or "等待交付审查。",
        },
        "case_assets_archived": {
            "auto_status": "complete" if case_assets else "warning",
            "auto_detail": f"已沉淀 {len(case_assets)} 条案例资产。" if case_assets else "尚未沉淀案例资产，可在交付后补做。",
        },
    }


def _sync_auto_status(tender_id: int, conn: sqlite3.Connection) -> None:
    auto = _auto_map(tender_id, conn)
    with conn:
        for key, item in auto.items():
            conn.execute(
                """
                UPDATE final_check_items
                SET auto_status = ?, auto_detail = ?, updated_at = CURRENT_TIMESTAMP
                WHERE tender_id = ? AND check_key = ?
                """,
                (item["auto_status"], item["auto_detail"], tender_id, key),
            )


def update_final_check_item(
    item_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = row_to_dict(conn.execute("SELECT * FROM final_check_items WHERE id = ?", (item_id,)).fetchone())
    if not current:
        raise ValueError(f"Final check item not found: {item_id}")
    status = str(data.get("status") or current.get("status") or "待确认").strip() or "待确认"
    owner = str(data.get("owner") if data.get("owner") is not None else current.get("owner") or "").strip()
    notes = str(data.get("notes") if data.get("notes") is not None else current.get("notes") or "").strip()
    with conn:
        conn.execute(
            """
            UPDATE final_check_items
            SET status = ?, owner = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, owner, notes, item_id),
        )
    result = row_to_dict(conn.execute("SELECT * FROM final_check_items WHERE id = ?", (item_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return result


def build_final_checklist(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    _ensure_items(tender_id, conn)
    _sync_auto_status(tender_id, conn)
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM final_check_items
            WHERE tender_id = ?
            ORDER BY required DESC, category, id
            """,
            (tender_id,),
        ).fetchall()
    )
    required_items = [item for item in rows if int(item.get("required") or 0)]
    manual_pending = [item for item in required_items if str(item.get("status") or "") not in MANUAL_OK]
    auto_blockers = [
        item
        for item in required_items
        if item.get("auto_status") in {"pending", "blocked"} and str(item.get("status") or "") != "不适用"
    ]
    auto_warnings = [
        item
        for item in rows
        if item.get("auto_status") == "warning" and str(item.get("status") or "") != "不适用"
    ]
    if auto_blockers:
        readiness = "needs_work"
    elif manual_pending:
        readiness = "needs_confirmation"
    else:
        readiness = "ready"

    summary = {
        "readiness": readiness,
        "readiness_label": {
            "ready": "最终核对已完成",
            "needs_confirmation": "等待人工确认",
            "needs_work": "仍需补齐后核对",
        }.get(readiness, readiness),
        "total": len(rows),
        "required_total": len(required_items),
        "required_confirmed": len(required_items) - len(manual_pending),
        "manual_pending": len(manual_pending),
        "auto_blockers": len(auto_blockers),
        "auto_warnings": len(auto_warnings),
    }
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender_id": tender_id,
        "summary": summary,
        "items": rows,
        "manual_pending_items": manual_pending,
        "auto_blocker_items": auto_blockers,
        "auto_warning_items": auto_warnings,
    }
    report["markdown"] = render_final_checklist_markdown(report)
    if own_conn:
        conn.close()
    return report


def render_final_checklist_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# 最终核对清单",
        "",
        f"- 核对结论：{summary.get('readiness_label')}",
        f"- 必选项确认：{summary.get('required_confirmed')}/{summary.get('required_total')}",
        f"- 自动阻碍：{summary.get('auto_blockers')}",
        f"- 自动提醒：{summary.get('auto_warnings')}",
        "",
        "## 核对项",
    ]
    for item in report.get("items", []):
        required = "必选" if int(item.get("required") or 0) else "建议"
        lines.extend(
            [
                f"### {item.get('title')}",
                "",
                f"- 分类：{item.get('category') or ''}",
                f"- 类型：{required}",
                f"- 人工状态：{item.get('status') or '待确认'}",
                f"- 自动状态：{item.get('auto_status') or ''}",
                f"- 自动说明：{item.get('auto_detail') or ''}",
                f"- 负责人：{item.get('owner') or ''}",
                f"- 备注：{item.get('notes') or ''}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
