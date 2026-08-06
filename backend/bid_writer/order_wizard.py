from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .db import connect, row_to_dict
from .production_starter import build_production_starter
from .workflow import build_workflow_status


PHASE_LABELS = {
    "intake": "接单确认",
    "production": "生产编制",
    "delivery": "交付闭环",
}


def _step(
    key: str,
    phase: str,
    title: str,
    status: str,
    detail: str,
    action_label: str,
    action_code: str,
    target: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "title": title,
        "status": status,
        "detail": detail,
        "action": {
            "label": action_label,
            "action_code": action_code,
            "target": target,
            "variant": "primary" if status in {"current", "blocked"} else "secondary",
        },
    }


def _status_from_done(done: bool, available: bool = True) -> str:
    if done:
        return "complete"
    return "current" if available else "pending"


def _first_incomplete(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return next((step for step in steps if step.get("status") in {"current", "blocked", "pending"}), steps[-1])


def _copyables(starter: dict[str, Any]) -> dict[str, str]:
    return {
        "customer_reply": str(starter.get("customer_reply") or ""),
        "material_request": str(starter.get("customer_material_request") or ""),
        "order_confirmation": str(starter.get("order_confirmation_message") or ""),
        "channel_boundary": str((starter.get("channel_policy") or {}).get("automation_boundary") or ""),
    }


def _recommended_copy_key(current_step: dict[str, Any], copyables: dict[str, str]) -> str:
    key = str(current_step.get("key") or "")
    if key in {"materials", "source"} and copyables.get("material_request"):
        return "material_request"
    if key in {"task", "confirm"} and copyables.get("order_confirmation"):
        return "order_confirmation"
    return "customer_reply" if copyables.get("customer_reply") else "channel_boundary"


def _phase_summary(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    for phase_key, phase_label in PHASE_LABELS.items():
        phase_steps = [step for step in steps if step["phase"] == phase_key]
        completed = sum(1 for step in phase_steps if step["status"] == "complete")
        blocked = sum(1 for step in phase_steps if step["status"] == "blocked")
        current = sum(1 for step in phase_steps if step["status"] == "current")
        if blocked:
            status = "blocked"
        elif completed == len(phase_steps):
            status = "complete"
        elif current:
            status = "current"
        else:
            status = "pending"
        phases.append(
            {
                "key": phase_key,
                "label": phase_label,
                "status": status,
                "completed": completed,
                "total": len(phase_steps),
            }
        )
    return phases


def build_order_wizard(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    starter = build_production_starter(tender_id, conn=conn)
    workflow = build_workflow_status(tender_id, conn=conn)
    task = (starter.get("snapshots") or {}).get("task") or {}
    quote = (starter.get("snapshots") or {}).get("quote") or {}
    materials = (starter.get("snapshots") or {}).get("materials") or {}
    payment = (starter.get("snapshots") or {}).get("payment") or {}
    readiness = (starter.get("snapshots") or {}).get("readiness_summary") or {}
    acceptance = ((starter.get("snapshots") or {}).get("intake") or {}).get("acceptance") or {}
    workflow_summary = workflow.get("summary") or {}

    has_customer = bool(task.get("customer_name"))
    has_deadline = bool(task.get("deadline"))
    has_budget = bool(task.get("budget") or quote.get("suggested_price"))
    has_scope = bool(starter.get("order_confirmation_message"))
    pending_materials = int(materials.get("pending_required") or 0)
    requirements = int(readiness.get("requirements") or workflow_summary.get("requirements") or 0)
    sections = int(readiness.get("total_sections") or workflow_summary.get("plans") or 0)
    generated_sections = int(readiness.get("generated_sections") or workflow_summary.get("generated_plans") or 0)
    quality_status = str(readiness.get("quality_status") or "")
    package_readiness = str(readiness.get("package_readiness") or "")
    delivery_records = int(workflow_summary.get("delivery_records") or 0)
    delivered_records = int(workflow_summary.get("delivered_records") or 0)
    closure_records = int(workflow_summary.get("closure_records") or 0)

    intake_blocked = acceptance.get("decision") == "暂缓接单"
    steps = [
        _step(
            "inquiry",
            "intake",
            "粘贴客户消息并创建订单草稿",
            "complete",
            "当前项目已建立，可继续评估接单。" if tender.get("raw_text") or tender.get("file_path") else "尚未录入客户消息或招标资料。",
            "去接单助手",
            "scroll",
            "stage-intake",
        ),
        _step(
            "intake",
            "intake",
            "生成接单判断和报价建议",
            "blocked" if intake_blocked else "complete",
            f"{acceptance.get('decision') or '待判断'}：{acceptance.get('reason') or ''}",
            "生成接单建议",
            "build_intake",
            "stage-intake",
        ),
        _step(
            "task",
            "intake",
            "确认客户、期限、预算和交付格式",
            _status_from_done(has_customer and has_deadline and has_budget and bool(task.get("deliverable_format"))),
            f"客户：{task.get('customer_name') or '未登记'}；期限：{task.get('deadline') or '未登记'}；预算：{task.get('budget') or quote.get('suggested_price') or '待确认'}。",
            "回填生产任务",
            "apply_intake_task",
            "stage-task",
        ),
        _step(
            "confirm",
            "intake",
            "发送订单确认口径",
            _status_from_done(has_scope and has_customer and has_deadline, available=has_scope),
            "已生成可复制订单确认话术。" if has_scope else "等待报价和订单范围确认。",
            "生成确认单",
            "build_order_confirmation",
            "stage-payments",
        ),
        _step(
            "materials",
            "production",
            "补齐必要资料",
            _status_from_done(pending_materials == 0, available=True),
            f"必要资料待补 {pending_materials} 项。",
            "复制资料清单",
            "copy_material_request",
            "stage-materials",
        ),
        _step(
            "source",
            "production",
            "补充招标文件并解析要求",
            _status_from_done(requirements > 0, available=True),
            f"已形成 {requirements} 条响应要求。",
            "解析招标要求",
            "parse_current",
            "stage-source",
        ),
        _step(
            "plan",
            "production",
            "生成技术标目录",
            _status_from_done(sections > 0, available=requirements > 0),
            f"已规划 {sections} 个章节。",
            "生成目录规划",
            "build_plan",
            "stage-plan",
        ),
        _step(
            "drafts",
            "production",
            "批量生成章节初稿",
            _status_from_done(sections > 0 and generated_sections >= sections, available=sections > 0),
            f"章节生成 {generated_sections}/{sections}。",
            "批量生成章节",
            "generate_all",
            "stage-generate",
        ),
        _step(
            "review",
            "delivery",
            "质量门禁和人工终审",
            _status_from_done(quality_status == "pass" and generated_sections >= sections and sections > 0, available=generated_sections > 0),
            f"质量状态：{quality_status or '待检查'}；收款：{payment.get('status_label') or '待确认'}。",
            "执行质量审查",
            "quality_gate",
            "stage-workflow",
        ),
        _step(
            "package",
            "delivery",
            "导出交付包",
            _status_from_done(package_readiness in {"ready", "warning"}, available=sections > 0 and generated_sections >= sections),
            f"交付包状态：{package_readiness or '未导出'}。",
            "导出交付包",
            "export_package",
            "stage-delivery",
        ),
        _step(
            "delivery",
            "delivery",
            "人工发货并记录交付",
            _status_from_done(delivered_records > 0, available=delivery_records > 0),
            f"交付记录 {delivery_records} 条，已交付 {delivered_records} 条。",
            "生成交付说明",
            "delivery_assistant",
            "stage-delivery",
        ),
        _step(
            "closure",
            "delivery",
            "客户确认、结案和复盘",
            _status_from_done(closure_records > 0, available=delivered_records > 0),
            f"客户确认记录 {closure_records} 条。",
            "生成结案确认",
            "closure_confirmation",
            "stage-delivery",
        ),
    ]
    current_step = _first_incomplete(steps)
    completed = sum(1 for step in steps if step["status"] == "complete")
    copyables = _copyables(starter)
    recommended_copy_key = _recommended_copy_key(current_step, copyables)
    action_bar = [
        current_step["action"],
        {"label": "复制推荐话术", "action_code": "copy_recommended", "target": "", "variant": "secondary"},
        {"label": "刷新启动包", "action_code": "refresh_guides", "target": "stage-starter", "variant": "secondary"},
    ]
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": {
            "id": tender["id"],
            "name": tender["name"],
            "industry": tender.get("industry") or "",
            "region": tender.get("region") or "",
        },
        "summary": {
            "title": "新单生产向导",
            "strategy": "先做标书生产工具，再做人工确认后的订单交付助手",
            "current_phase": current_step["phase_label"],
            "current_step": current_step["title"],
            "current_action": current_step["action"]["label"],
            "completed_steps": completed,
            "total_steps": len(steps),
            "progress": round(completed / len(steps), 4) if steps else 0,
            "state": "ready" if completed == len(steps) else ("blocked" if current_step["status"] == "blocked" else "needs_work"),
            "recommended_copy_key": recommended_copy_key,
            "recommended_copy_text": copyables.get(recommended_copy_key, ""),
        },
        "phases": _phase_summary(steps),
        "steps": steps,
        "current_step": current_step,
        "action_bar": action_bar,
        "copyables": copyables,
        "starter_summary": starter.get("summary") or {},
        "channel_policy": starter.get("channel_policy") or {},
    }
    result["markdown"] = render_order_wizard_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_order_wizard_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 新单生产向导",
        "",
        "## 当前状态",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        f"- 生成时间：{report.get('generated_at') or ''}",
        f"- 策略：{summary.get('strategy') or ''}",
        f"- 当前阶段：{summary.get('current_phase') or ''}",
        f"- 当前步骤：{summary.get('current_step') or ''}",
        f"- 当前动作：{summary.get('current_action') or ''}",
        f"- 进度：{summary.get('completed_steps', 0)}/{summary.get('total_steps', 0)}",
        "",
        "## 步骤",
    ]
    for step in report.get("steps") or []:
        lines.append(f"- [{step.get('status')}] {step.get('phase_label')} / {step.get('title')}：{step.get('detail')}")
        action = step.get("action") or {}
        if action.get("label"):
            lines.append(f"  - 动作：{action.get('label')}")
    lines.extend(["", "## 推荐话术", "", summary.get("recommended_copy_text") or ""])
    return "\n".join(lines).strip() + "\n"
