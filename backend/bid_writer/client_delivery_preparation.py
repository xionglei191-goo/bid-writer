from __future__ import annotations

import sqlite3
from typing import Any

from .client_delivery_confirmation import build_client_delivery_confirmation
from .client_package_validation import validate_latest_client_package
from .db import connect, row_to_dict
from .exporter import export_client_package
from .production_pipeline import run_production_pipeline
from .task_status import sync_production_status


def _step(key: str, title: str, status: str, detail: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "payload": payload or {},
    }


def prepare_client_delivery(
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

    pipeline_options = {
        "force_parse": bool(opts.get("force_parse")),
        "rebuild_plan": bool(opts.get("rebuild_plan")),
        "regenerate": bool(opts.get("regenerate")),
        "export_package": bool(opts.get("export_internal_package", True)),
    }
    pipeline = run_production_pipeline(tender_id, pipeline_options, conn=conn)
    steps = [
        _step(
            "production_pipeline",
            "生产技术标草稿",
            "complete",
            f"已完成 {len(pipeline.get('steps') or [])} 个生产步骤，当前状态：{(pipeline.get('status') or {}).get('current_status') or '已完成'}。",
            {"steps": pipeline.get("steps") or []},
        )
    ]
    if pipeline.get("package"):
        steps.append(_step("internal_package", "内部归档包", "complete", f"已导出：{pipeline['package'].get('path')}", pipeline["package"]))
    else:
        steps.append(_step("internal_package", "内部归档包", "skipped", "本次未导出内部归档包。"))

    client_package = export_client_package(tender_id, conn=conn)
    steps.append(_step("client_package", "导出客户发货包", "complete", f"已导出：{client_package.get('path')}", client_package))

    validation = validate_latest_client_package(tender_id, conn=conn)
    validation_summary = validation.get("summary") or {}
    validation_ready = str(validation_summary.get("readiness") or "") == "ready"
    steps.append(
        _step(
            "client_package_validation",
            "客户包安全核验",
            "complete" if validation_ready else "warning",
            (
                f"状态 {validation_summary.get('readiness') or 'unknown'}，"
                f"缺失 {validation_summary.get('missing_files', 0)}，"
                f"内部文件 {validation_summary.get('forbidden_files', 0)}，"
                f"内容风险 {validation_summary.get('content_findings', 0)}。"
            ),
            validation,
        )
    )

    confirmation = build_client_delivery_confirmation(
        tender_id,
        {"extra_note": str(opts.get("extra_note") or "").strip()},
        conn=conn,
    )
    confirmation_summary = confirmation.get("summary") or {}
    can_send = bool(confirmation_summary.get("can_send"))
    steps.append(
        _step(
            "client_delivery_confirmation",
            "生成客户发货确认",
            "complete" if can_send else "warning",
            f"发货状态：{confirmation_summary.get('send_label') or '待确认'}。",
            confirmation,
        )
    )

    status = sync_production_status(tender_id, conn=conn)
    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "tender_id": tender_id,
        "summary": {
            "ready_to_send": can_send,
            "client_package_ready": bool(confirmation_summary.get("client_package_ready")),
            "send_status": confirmation_summary.get("send_status"),
            "send_label": confirmation_summary.get("send_label"),
            "blockers_count": len(confirmation.get("blockers") or []),
            "warnings_count": len(confirmation.get("warnings") or []),
            "internal_package_path": (pipeline.get("package") or {}).get("path") or "",
            "client_package_path": client_package.get("path") or "",
            "customer_message": confirmation.get("customer_message") or "",
        },
        "steps": steps,
        "pipeline": pipeline,
        "client_package": client_package,
        "client_package_validation": validation,
        "client_delivery_confirmation": confirmation,
        "status": status,
    }
    if own_conn:
        conn.close()
    return result
