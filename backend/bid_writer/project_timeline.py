from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts


KIND_LABELS = {
    "tender": "项目",
    "document": "文档",
    "communication": "沟通",
    "quote": "报价",
    "payment": "收款",
    "requirements": "响应矩阵",
    "materials": "资料",
    "profile": "项目资料",
    "task": "生产任务",
    "strategy": "投标策略",
    "plan": "目录",
    "draft": "章节",
    "polish": "校正",
    "final_check": "核对",
    "final_document": "成稿",
    "delivery": "交付",
    "feedback": "反馈",
    "closure": "结案",
    "retrospective": "复盘",
    "case_asset": "案例资产",
}


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _event(
    kind: str,
    title: str,
    detail: str,
    occurred_at: Any,
    *,
    ref_table: str = "",
    ref_id: Any = None,
    status: str = "",
    amount: Any = None,
    section_title: str = "",
    source: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "title": title,
        "detail": detail,
        "occurred_at": str(occurred_at or ""),
        "ref_table": ref_table,
        "ref_id": ref_id,
        "status": str(status or ""),
        "amount": amount,
        "section_title": str(section_title or ""),
        "source": str(source or ""),
    }


def _row_count(conn: sqlite3.Connection, table: str, tender_id: int) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _latest_updated(conn: sqlite3.Connection, table: str, tender_id: int) -> str:
    row = conn.execute(
        f"""
        SELECT MAX(COALESCE(updated_at, created_at)) AS latest_at
        FROM {table}
        WHERE tender_id = ?
        """,
        (tender_id,),
    ).fetchone()
    return str(row["latest_at"] or "") if row else ""


def build_project_timeline(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    events: list[dict[str, Any]] = []
    events.append(
        _event(
            "tender",
            "项目创建",
            f"创建项目：{tender.get('name') or '未命名项目'}",
            tender.get("created_at"),
            ref_table="tenders",
            ref_id=tender.get("id"),
            status="已创建",
            source=tender.get("file_path") or "",
        )
    )

    task = row_to_dict(conn.execute("SELECT * FROM production_tasks WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if task:
        detail_parts = [
            f"客户：{task.get('customer_name') or '未登记'}",
            f"来源：{task.get('source_platform') or '未登记'}",
            f"期限：{task.get('deadline') or '未登记'}",
            f"格式：{task.get('deliverable_format') or '未登记'}",
        ]
        events.append(
            _event(
                "task",
                "生产任务登记",
                "；".join(detail_parts),
                task.get("updated_at") or task.get("created_at"),
                ref_table="production_tasks",
                ref_id=task.get("id"),
                status=task.get("delivery_status") or "",
            )
        )

    profile = row_to_dict(conn.execute("SELECT * FROM project_profiles WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if profile:
        detail_parts = [
            f"工程类型：{profile.get('project_type') or '未登记'}",
            f"工期：{profile.get('duration_days') or '未登记'}",
            f"质量目标：{profile.get('quality_target') or '未登记'}",
        ]
        events.append(
            _event(
                "profile",
                "项目资料维护",
                "；".join(detail_parts),
                profile.get("updated_at") or profile.get("created_at"),
                ref_table="project_profiles",
                ref_id=profile.get("id"),
                status="已维护",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM document_processing_records
            WHERE tender_id = ?
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = (
            f"{row.get('original_filename') or row.get('source_path') or '未命名文件'}；"
            f"{row.get('action') or '处理'}；"
            f"{row.get('text_chars') or 0} 字；{row.get('page_count') or 0} 页"
        )
        if row.get("error_message"):
            detail += f"；错误：{row.get('error_message')}"
        events.append(
            _event(
                "document",
                "招标文件处理",
                detail,
                row.get("updated_at") or row.get("created_at"),
                ref_table="document_processing_records",
                ref_id=row.get("id"),
                status=row.get("status") or "",
                source=row.get("markdown_path") or row.get("source_path") or "",
            )
        )

    requirement_count = _row_count(conn, "requirements", tender_id)
    if requirement_count:
        high_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM requirements
                WHERE tender_id = ? AND priority IN ('high', '高', '重要')
                """,
                (tender_id,),
            ).fetchone()[0]
        )
        events.append(
            _event(
                "requirements",
                "响应矩阵形成",
                f"已抽取 {requirement_count} 条要求，其中高优先级 {high_count} 条。",
                tender.get("created_at"),
                ref_table="requirements",
                status="已形成",
            )
        )

    material_count = _row_count(conn, "material_items", tender_id)
    if material_count:
        done_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM material_items
                WHERE tender_id = ? AND status IN ('已提供', '已完成', '齐全')
                """,
                (tender_id,),
            ).fetchone()[0]
        )
        events.append(
            _event(
                "materials",
                "资料清单维护",
                f"资料项 {material_count} 条，已完成 {done_count} 条。",
                _latest_updated(conn, "material_items", tender_id),
                ref_table="material_items",
                status="资料跟进中" if done_count < material_count else "资料已齐",
            )
        )

    strategy = row_to_dict(conn.execute("SELECT * FROM bid_strategies WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if strategy:
        detail = f"定位：{strategy.get('positioning') or '未填写'}；语气：{strategy.get('writing_tone') or '未填写'}"
        events.append(
            _event(
                "strategy",
                "投标策略维护",
                detail,
                strategy.get("updated_at") or strategy.get("created_at"),
                ref_table="bid_strategies",
                ref_id=strategy.get("id"),
                status=strategy.get("status") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM customer_communications
            WHERE tender_id = ?
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        direction = "发出" if str(row.get("direction") or "").lower() != "incoming" else "收到"
        detail = f"{direction} {row.get('stage') or '沟通'}；渠道：{row.get('channel') or '未登记'}"
        if row.get("notes"):
            detail += f"；备注：{row.get('notes')}"
        events.append(
            _event(
                "communication",
                "客户沟通",
                detail,
                row.get("updated_at") or row.get("created_at"),
                ref_table="customer_communications",
                ref_id=row.get("id"),
                status=row.get("status") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM quotation_records
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = f"建议价：{row.get('suggested_price') or '未计算'}；工作量：{row.get('workload') or '未评估'}；周期：{row.get('turnaround') or '未评估'}"
        events.append(
            _event(
                "quote",
                "报价测算",
                detail,
                row.get("created_at"),
                ref_table="quotation_records",
                ref_id=row.get("id"),
                status="已测算",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM payment_records
            WHERE tender_id = ?
            ORDER BY COALESCE(received_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = (
            f"{row.get('payment_stage') or '收款'}：{row.get('amount') or 0} {row.get('currency') or 'CNY'}；"
            f"方式：{row.get('payment_method') or '未登记'}"
        )
        if row.get("notes"):
            detail += f"；备注：{row.get('notes')}"
        events.append(
            _event(
                "payment",
                "收款记录",
                detail,
                row.get("received_at") or row.get("created_at"),
                ref_table="payment_records",
                ref_id=row.get("id"),
                status=row.get("status") or "",
                amount=row.get("amount"),
            )
        )

    plan_row = row_to_dict(
        conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN draft_id IS NOT NULL THEN 1 ELSE 0 END) AS generated,
                MIN(created_at) AS created_at,
                MAX(updated_at) AS updated_at
            FROM section_plans
            WHERE tender_id = ?
            """,
            (tender_id,),
        ).fetchone()
    ) or {}
    if int(plan_row.get("total") or 0):
        events.append(
            _event(
                "plan",
                "目录规划",
                f"规划章节 {plan_row.get('total') or 0} 个，已关联草稿 {plan_row.get('generated') or 0} 个。",
                plan_row.get("updated_at") or plan_row.get("created_at"),
                ref_table="section_plans",
                status="已规划",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT id, section_title, status, generation_mode, generation_model, generation_error,
                   LENGTH(content) AS char_count, created_at, updated_at
            FROM drafts
            WHERE tender_id = ?
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = f"{row.get('section_title') or '未命名章节'}；{row.get('char_count') or 0} 字"
        if row.get("generation_mode"):
            detail += f"；生成方式：{row.get('generation_mode')}"
        if row.get("generation_error"):
            detail += f"；异常：{row.get('generation_error')}"
        events.append(
            _event(
                "draft",
                "章节草稿生成/更新",
                detail,
                row.get("updated_at") or row.get("created_at"),
                ref_table="drafts",
                ref_id=row.get("id"),
                status=row.get("status") or "",
                section_title=row.get("section_title") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM draft_replacement_records
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = f"替换 {row.get('changed_drafts') or 0} 份草稿，命中 {row.get('changed_count') or 0} 处。"
        if row.get("notes"):
            detail += f" 备注：{row.get('notes')}"
        events.append(
            _event(
                "polish",
                "项目化校正",
                detail,
                row.get("created_at"),
                ref_table="draft_replacement_records",
                ref_id=row.get("id"),
                status="已执行",
            )
        )

    final_check_count = _row_count(conn, "final_check_items", tender_id)
    if final_check_count:
        confirmed_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM final_check_items
                WHERE tender_id = ? AND status IN ('已确认', '通过', '不适用')
                """,
                (tender_id,),
            ).fetchone()[0]
        )
        events.append(
            _event(
                "final_check",
                "最终核对清单",
                f"核对项 {final_check_count} 条，已确认 {confirmed_count} 条。",
                _latest_updated(conn, "final_check_items", tender_id),
                ref_table="final_check_items",
                status="核对中" if confirmed_count < final_check_count else "已核对",
            )
        )

    final_doc = row_to_dict(conn.execute("SELECT * FROM final_documents WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if final_doc:
        detail = f"成稿字数：{final_doc.get('snapshot_char_count') or 0}；确认人：{final_doc.get('approved_by') or '未确认'}"
        if final_doc.get("notes"):
            detail += f"；备注：{final_doc.get('notes')}"
        events.append(
            _event(
                "final_document",
                "成稿确认",
                detail,
                final_doc.get("approved_at") or final_doc.get("updated_at") or final_doc.get("created_at"),
                ref_table="final_documents",
                ref_id=final_doc.get("id"),
                status=final_doc.get("status") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM delivery_records
            WHERE tender_id = ?
            ORDER BY COALESCE(delivered_at, exported_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        size_kb = round(float(row.get("package_size") or 0) / 1024, 1)
        detail = f"{row.get('package_format') or '文件包'}；{size_kb} KB；渠道：{row.get('delivery_channel') or '未登记'}"
        if row.get("recipient"):
            detail += f"；接收人：{row.get('recipient')}"
        events.append(
            _event(
                "delivery",
                "交付包导出/发送",
                detail,
                row.get("delivered_at") or row.get("exported_at") or row.get("created_at"),
                ref_table="delivery_records",
                ref_id=row.get("id"),
                status=row.get("status") or "",
                source=row.get("package_path") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM feedback_items
            WHERE tender_id = ?
            ORDER BY COALESCE(resolved_at, updated_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = f"{row.get('related_section') or '未指明章节'}；{row.get('feedback_text') or ''}"
        if row.get("action_plan"):
            detail += f"；处理：{row.get('action_plan')}"
        events.append(
            _event(
                "feedback",
                "客户反馈/返修",
                detail,
                row.get("resolved_at") or row.get("updated_at") or row.get("created_at"),
                ref_table="feedback_items",
                ref_id=row.get("id"),
                status=row.get("status") or "",
                section_title=row.get("related_section") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM closure_records
            WHERE tender_id = ?
            ORDER BY COALESCE(confirmed_at, updated_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = f"确认人：{row.get('confirmed_by') or '未登记'}；期限：{row.get('reply_deadline') or '未登记'}"
        if row.get("confirmation_note"):
            detail += f"；备注：{row.get('confirmation_note')}"
        events.append(
            _event(
                "closure",
                "结案确认",
                detail,
                row.get("confirmed_at") or row.get("updated_at") or row.get("created_at"),
                ref_table="closure_records",
                ref_id=row.get("id"),
                status=row.get("status") or "",
            )
        )

    retro = row_to_dict(conn.execute("SELECT * FROM project_retrospectives WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if retro:
        detail = (
            f"成交价：{retro.get('actual_price') or '未登记'}；耗时：{retro.get('work_hours') or '未登记'}；"
            f"风险：{retro.get('risk_level') or '未评估'}；复用评分：{retro.get('reusable_score') or '未评估'}"
        )
        events.append(
            _event(
                "retrospective",
                "项目复盘",
                detail,
                retro.get("updated_at") or retro.get("created_at"),
                ref_table="project_retrospectives",
                ref_id=retro.get("id"),
                status=retro.get("status") or "",
            )
        )

    for row in rows_to_dicts(
        conn.execute(
            """
            SELECT id, project_name, industry, section_title, tags, reusable_score,
                   source_status, created_at, updated_at
            FROM case_assets
            WHERE tender_id = ?
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    ):
        detail = f"{row.get('section_title') or '未命名章节'}；标签：{row.get('tags') or '未登记'}；评分：{row.get('reusable_score') or '未评估'}"
        events.append(
            _event(
                "case_asset",
                "案例资产沉淀",
                detail,
                row.get("updated_at") or row.get("created_at"),
                ref_table="case_assets",
                ref_id=row.get("id"),
                status=row.get("source_status") or "",
                section_title=row.get("section_title") or "",
            )
        )

    events.sort(key=lambda item: (item.get("occurred_at") or "", int(item.get("ref_id") or 0)), reverse=True)
    counts = Counter(str(item.get("kind") or "") for item in events)
    first_event = min((item.get("occurred_at") or "" for item in events if item.get("occurred_at")), default="")
    latest_event = events[0] if events else {}
    summary = {
        "total_events": len(events),
        "first_event_at": first_event,
        "latest_event_at": latest_event.get("occurred_at") or "",
        "latest_title": latest_event.get("title") or "",
        "latest_status": latest_event.get("status") or "",
        "counts_by_kind": dict(counts),
        "document_events": counts.get("document", 0),
        "communication_events": counts.get("communication", 0),
        "quote_events": counts.get("quote", 0),
        "payment_events": counts.get("payment", 0),
        "draft_events": counts.get("draft", 0),
        "delivery_events": counts.get("delivery", 0),
        "feedback_events": counts.get("feedback", 0),
        "closure_events": counts.get("closure", 0),
    }
    result = {
        "generated_at": _now(),
        "tender": {
            "id": tender["id"],
            "name": tender["name"],
            "industry": tender.get("industry") or "",
            "region": tender.get("region") or "",
        },
        "summary": summary,
        "events": events,
    }
    result["markdown"] = render_project_timeline_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_project_timeline_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    events = report.get("events") or []
    lines = [
        "# 项目生产履历",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 行业：{tender.get('industry') or '未登记'}",
        f"- 地区：{tender.get('region') or '未登记'}",
        f"- 生成时间：{report.get('generated_at') or ''}",
        "",
        "## 履历概览",
        f"- 事件总数：{summary.get('total_events', 0)}",
        f"- 起始时间：{summary.get('first_event_at') or '未记录'}",
        f"- 最近动作：{summary.get('latest_event_at') or '未记录'} / {summary.get('latest_title') or '无'}",
        f"- 文档处理：{summary.get('document_events', 0)} 条",
        f"- 客户沟通：{summary.get('communication_events', 0)} 条",
        f"- 报价记录：{summary.get('quote_events', 0)} 条",
        f"- 收款记录：{summary.get('payment_events', 0)} 条",
        f"- 章节草稿：{summary.get('draft_events', 0)} 条",
        f"- 交付记录：{summary.get('delivery_events', 0)} 条",
        f"- 客户反馈：{summary.get('feedback_events', 0)} 条",
        "",
        "## 事件明细",
    ]
    if not events:
        lines.append("- 暂无履历记录。")
    for item in events:
        occurred_at = item.get("occurred_at") or "未记录时间"
        label = item.get("kind_label") or item.get("kind") or "记录"
        status = f" / {item.get('status')}" if item.get("status") else ""
        lines.append(f"- {occurred_at} [{label}] {item.get('title') or ''}{status}")
        detail = str(item.get("detail") or "").strip()
        if detail:
            lines.append(f"  - 说明：{detail}")
        source = str(item.get("source") or "").strip()
        if source:
            lines.append(f"  - 来源：{source}")
    return "\n".join(lines).strip() + "\n"
