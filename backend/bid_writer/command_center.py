from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict
from .package_validation import validate_latest_package
from .production_readiness import build_production_readiness
from .project_overview import build_project_overview
from .workflow import build_workflow_status


ACTION_MAP: dict[str, dict[str, str]] = {
    "task": {
        "label": "补齐生产任务",
        "action_code": "scroll",
        "target": "stage-task",
        "variant": "secondary",
    },
    "materials": {
        "label": "补齐资料清单",
        "action_code": "scroll",
        "target": "stage-materials",
        "variant": "secondary",
    },
    "profile": {
        "label": "补齐项目资料",
        "action_code": "scroll",
        "target": "stage-profile",
        "variant": "secondary",
    },
    "parse": {
        "label": "解析招标要求",
        "action_code": "parse_current",
        "target": "stage-source",
        "variant": "primary",
    },
    "plan": {
        "label": "生成目录规划",
        "action_code": "build_plan",
        "target": "stage-plan",
        "variant": "primary",
    },
    "drafts": {
        "label": "批量生成章节",
        "action_code": "generate_all",
        "target": "stage-generate",
        "variant": "primary",
    },
    "review": {
        "label": "执行质量审查",
        "action_code": "quality_gate",
        "target": "stage-workflow",
        "variant": "primary",
    },
    "export": {
        "label": "导出交付包",
        "action_code": "export_package",
        "target": "stage-delivery",
        "variant": "primary",
    },
    "delivery": {
        "label": "生成交付说明",
        "action_code": "delivery_assistant",
        "target": "stage-delivery",
        "variant": "primary",
    },
    "feedback": {
        "label": "处理客户反馈",
        "action_code": "scroll",
        "target": "stage-delivery",
        "variant": "secondary",
    },
    "closure": {
        "label": "生成结案确认",
        "action_code": "closure_confirmation",
        "target": "stage-delivery",
        "variant": "primary",
    },
    "retrospective": {
        "label": "填写项目复盘",
        "action_code": "scroll",
        "target": "stage-retro",
        "variant": "secondary",
    },
}


def _card(key: str, label: str, value: Any, detail: str = "", status: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "detail": detail,
        "status": status,
    }


def _workflow_action(step: dict[str, Any]) -> dict[str, Any] | None:
    key = str(step.get("key") or "")
    action = ACTION_MAP.get(key)
    if not action:
        return None
    return {
        "key": key,
        "label": action["label"],
        "detail": step.get("action") or step.get("detail") or "",
        "action_code": action["action_code"],
        "target": action["target"],
        "variant": action["variant"],
    }


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for action in actions:
        key = (
            str(action.get("action_code") or ""),
            str(action.get("target") or ""),
            str(action.get("label") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped[:8]


def _extra_actions(
    overview: dict[str, Any],
    workflow: dict[str, Any],
    readiness: dict[str, Any],
    package_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    metrics = overview.get("metrics") or {}
    readiness_summary = readiness.get("summary") or {}
    package_summary = package_validation.get("summary") or {}
    workflow_summary = workflow.get("summary") or {}
    actions: list[dict[str, Any]] = []

    if readiness_summary.get("blockers"):
        actions.append(
            {
                "key": "readiness",
                "label": "查看阻碍项",
                "detail": f"当前有 {readiness_summary.get('blockers')} 个阻碍项需要先处理。",
                "action_code": "production_readiness",
                "target": "stage-workflow",
                "variant": "secondary",
            }
        )
    if metrics.get("communications_pending"):
        actions.append(
            {
                "key": "communications",
                "label": "跟进客户沟通",
                "detail": f"仍有 {metrics.get('communications_pending')} 条沟通记录待发送或需跟进。",
                "action_code": "scroll",
                "target": "stage-intake",
                "variant": "secondary",
            }
        )
    if package_summary.get("readiness") == "blocked" and workflow_summary.get("export_ready"):
        actions.append(
            {
                "key": "package",
                "label": "重新导出交付包",
                "detail": "当前具备导出条件，但最新交付包缺失或未通过清单核验。",
                "action_code": "export_package",
                "target": "stage-delivery",
                "variant": "primary",
            }
        )
    if int((overview.get("quality") or {}).get("summary", {}).get("task_count") or 0):
        actions.append(
            {
                "key": "quality",
                "label": "同步修订任务",
                "detail": "将质量门禁发现的问题同步成可跟踪的修订任务。",
                "action_code": "sync_revision_tasks",
                "target": "stage-workflow",
                "variant": "secondary",
            }
        )
    return actions


def build_command_center(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    workflow = build_workflow_status(tender_id, conn=conn)
    overview = build_project_overview(tender_id, conn=conn)
    readiness = build_production_readiness(tender_id, conn=conn)
    package_validation = validate_latest_package(tender_id, conn=conn)

    metrics = overview.get("metrics") or {}
    readiness_summary = readiness.get("summary") or {}
    package_summary = package_validation.get("summary") or {}
    next_step = workflow.get("next_step") or {}
    workflow_action = _workflow_action(next_step)
    actions = [workflow_action] if workflow_action else []
    actions.extend(_extra_actions(overview, workflow, readiness, package_validation))
    actions.append(
        {
            "key": "pipeline",
            "label": "一键生产交付包",
            "detail": "按解析、目录、批量生成、审查、导出和状态同步连续执行。",
            "action_code": "run_pipeline",
            "target": "stage-workflow",
            "variant": "secondary",
        }
    )

    cards = [
        _card(
            "requirements",
            "响应条款",
            metrics.get("requirements", 0),
            "已解析的评分点、技术要求和风险条款。",
            "ready" if metrics.get("requirements") else "needs_work",
        ),
        _card(
            "sections",
            "章节进度",
            f"{metrics.get('generated_plans', 0)}/{metrics.get('plans', 0)}",
            f"草稿 {metrics.get('drafts', 0)} 篇。",
            "ready" if metrics.get("plans") and metrics.get("generated_plans") == metrics.get("plans") else "needs_work",
        ),
        _card(
            "quality",
            "质量分",
            metrics.get("quality_score", 0),
            metrics.get("quality_status", ""),
            "ready" if (overview.get("quality") or {}).get("status") == "pass" else "needs_work",
        ),
        _card(
            "materials",
            "必要资料",
            f"{metrics.get('materials_ready', 0)}/{metrics.get('materials_required', 0)}",
            "客户资料、项目资料和投标单位资料。",
            "ready"
            if metrics.get("materials_required") and metrics.get("materials_ready") == metrics.get("materials_required")
            else "needs_work",
        ),
        _card(
            "payment",
            "收款状态",
            metrics.get("payment_status_label") or "待确认",
            f"已收 {metrics.get('payment_received_amount', 0)} 元，未收 {metrics.get('payment_outstanding_amount', 0)} 元。",
            "ready" if not (overview.get("payment") or {}).get("requires_payment_confirmation") else "needs_work",
        ),
        _card(
            "package",
            "交付包",
            package_summary.get("readiness") or "blocked",
            f"核心缺失 {package_summary.get('core_missing', 0)}，JSON 异常 {package_summary.get('invalid_json', 0)}。",
            "ready" if package_summary.get("readiness") == "ready" else "needs_work",
        ),
    ]

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": {
            "id": tender["id"],
            "name": tender["name"],
            "industry": tender.get("industry") or "",
            "region": tender.get("region") or "",
        },
        "headline": {
            "decision": readiness_summary.get("decision") or overview.get("readiness", {}).get("label") or "",
            "readiness": readiness_summary.get("readiness") or "",
            "next_step_key": next_step.get("key") or "",
            "next_step_title": next_step.get("title") or "",
            "next_step_action": next_step.get("action") or next_step.get("detail") or "",
            "delivery_status": (overview.get("task") or {}).get("delivery_status") or "",
            "package_readiness": package_summary.get("readiness") or "",
            "quality_status": (overview.get("quality") or {}).get("status_label") or "",
        },
        "cards": cards,
        "progress": workflow.get("steps", []),
        "primary_actions": _dedupe_actions(actions),
        "blockers": readiness.get("blockers", [])[:8],
        "warnings": readiness.get("warnings", [])[:8],
        "risks": overview.get("risks", [])[:8],
        "overview": {
            "metrics": metrics,
            "readiness": overview.get("readiness") or {},
            "next_actions": overview.get("next_actions") or [],
        },
        "readiness_report": {
            "summary": readiness_summary,
            "phases": readiness.get("phases", []),
        },
        "package": {
            "summary": package_summary,
            "path": (package_validation.get("package") or {}).get("path") or "",
        },
    }
    if own_conn:
        conn.close()
    return result
