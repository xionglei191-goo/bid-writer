from __future__ import annotations

import sqlite3
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect, row_to_dict
from .delivery_assistant import build_delivery_assistant
from .delivery_review import build_delivery_review
from .exporter import export_package
from .planner import build_section_plan, generate_all_from_plan, list_section_plans
from .quality_gate import build_quality_gate
from .task_status import sync_production_status
from .tenders import parse_tender


def _count(conn: sqlite3.Connection, table: str, tender_id: int) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _step(key: str, title: str, status: str, detail: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "payload": payload or {},
    }


def run_production_pipeline(
    tender_id: int,
    options: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    opts = options or {}
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    force_parse = bool(opts.get("force_parse"))
    rebuild_plan = bool(opts.get("rebuild_plan"))
    regenerate = bool(opts.get("regenerate"))
    export_enabled = bool(opts.get("export_package", True))
    steps: list[dict[str, Any]] = []

    requirement_count = _count(conn, "requirements", tender_id)
    if force_parse or requirement_count == 0:
        parsed = parse_tender(tender_id, conn=conn)
        requirement_count = len(parsed.get("requirements") or [])
        steps.append(_step("parse", "解析招标文件", "complete", f"已解析 {requirement_count} 条要求。", parsed))
    else:
        steps.append(_step("parse", "解析招标文件", "skipped", f"已有 {requirement_count} 条要求，未重复解析。"))

    plans = list_section_plans(tender_id, conn=conn)
    if rebuild_plan or not plans:
        plans = build_section_plan(tender_id, reset=True, conn=conn)
        steps.append(_step("plan", "生成目录规划", "complete", f"已形成 {len(plans)} 个章节。", {"plans": plans}))
    else:
        steps.append(_step("plan", "生成目录规划", "skipped", f"已有 {len(plans)} 个章节，未重建目录。", {"plans": plans}))

    batch = generate_all_from_plan(tender_id, regenerate=regenerate, conn=conn)
    steps.append(
        _step(
            "generate",
            "批量生成章节",
            "complete",
            f"新增 {batch['generated_count']} 章，跳过 {batch['skipped_count']} 章。",
            batch,
        )
    )

    coverage = build_coverage_report(tender_id, conn=conn)
    delivery_review = build_delivery_review(tender_id, conn=conn)
    quality_gate = build_quality_gate(tender_id, conn=conn)
    steps.append(
        _step(
            "review",
            "覆盖、门禁与交付审查",
            "complete",
            f"条款覆盖 {round(float(coverage['summary'].get('draft_coverage_rate') or 0) * 100)}%，质量门禁：{quality_gate.get('status_label') or ''}，交付结论：{delivery_review['summary'].get('readiness_label') or ''}。",
            {"coverage": coverage, "quality_gate": quality_gate, "delivery_review": delivery_review},
        )
    )

    package: dict[str, Any] | None = None
    if export_enabled:
        package = export_package(tender_id, conn=conn)
        steps.append(_step("export", "导出交付包", "complete", f"已导出 ZIP：{package['path']}", package))
    else:
        steps.append(_step("export", "导出交付包", "skipped", "本次只生成草稿，不导出 ZIP。"))

    status = sync_production_status(tender_id, conn=conn)
    assistant = build_delivery_assistant(tender_id, conn=conn)
    result = {
        "tender_id": tender_id,
        "steps": steps,
        "coverage": coverage,
        "quality_gate": quality_gate,
        "delivery_review": delivery_review,
        "package": package or {},
        "status": status,
        "delivery_assistant": assistant,
    }
    if own_conn:
        conn.close()
    return result
