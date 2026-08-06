from __future__ import annotations

import sqlite3
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect, row_to_dict
from .feedback import feedback_summary
from .materials import material_summary
from .production_tasks import TASK_FIELD_LABELS, get_production_task, missing_task_fields
from .project_profiles import get_project_profile
from .workflow_confirmations import list_workflow_confirmations


PROFILE_REQUIRED_FIELDS = (
    "project_name",
    "project_type",
    "structure_type",
    "building_area",
    "duration_days",
    "quality_target",
    "safety_target",
)


def _count(conn: sqlite3.Connection, table: str, tender_id: int) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _step(key: str, title: str, status: str, detail: str, action: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "action": action,
    }


def build_workflow_status(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    profile = get_project_profile(tender_id, conn=conn)
    task = get_production_task(tender_id, conn=conn)
    materials = material_summary(tender_id, conn=conn)
    missing_task = missing_task_fields(task)
    missing_task_labels = [TASK_FIELD_LABELS.get(field, field) for field in missing_task]
    missing_profile_fields = [field for field in PROFILE_REQUIRED_FIELDS if profile.get(field) in ("", None)]
    requirement_count = _count(conn, "requirements", tender_id)
    plan_count = _count(conn, "section_plans", tender_id)
    draft_count = _count(conn, "drafts", tender_id)
    delivery_count = _count(conn, "delivery_records", tender_id)
    delivered_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM delivery_records WHERE tender_id = ? AND status IN (?, ?)",
            (tender_id, "已交付", "已结案"),
        ).fetchone()[0]
    )
    closed_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM closure_records WHERE tender_id = ? AND status = ?",
            (tender_id, "客户已确认"),
        ).fetchone()[0]
    )
    retrospective = row_to_dict(
        conn.execute(
            "SELECT * FROM project_retrospectives WHERE tender_id = ?",
            (tender_id,),
        ).fetchone()
    )
    latest_delivery = row_to_dict(
        conn.execute(
            """
            SELECT id, status, exported_at, delivered_at, package_path
            FROM delivery_records
            WHERE tender_id = ?
            ORDER BY exported_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    )
    latest_closure = row_to_dict(
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
    )
    feedback = feedback_summary(tender_id, conn=conn)
    generated_plan_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM section_plans WHERE tender_id = ? AND draft_id IS NOT NULL",
            (tender_id,),
        ).fetchone()[0]
    )
    missing_plan_count = max(0, plan_count - generated_plan_count)
    coverage = build_coverage_report(tender_id, conn=conn) if requirement_count or plan_count or draft_count else None
    coverage_summary = coverage.get("summary", {}) if coverage else {}

    steps: list[dict[str, Any]] = []
    task_status = "complete" if not missing_task else ("current" if task.get("customer_name") or task.get("deadline") else "pending")
    steps.append(
        _step(
            "task",
            "登记生产任务",
            task_status,
            "客户、期限和交付格式已登记" if not missing_task else f"缺少 {len(missing_task)} 项：{', '.join(missing_task_labels)}",
            "补充客户名称、交付期限和交付格式" if missing_task else "",
        )
    )
    material_status = (
        "complete"
        if materials["required"] and not materials["pending_required"]
        else ("current" if materials["total"] else "pending")
    )
    steps.append(
        _step(
            "materials",
            "收集客户资料",
            material_status,
            f"必要资料 {materials['required_completed']}/{materials['required']}，待补 {materials['pending_required']} 项",
            "补齐完整招标文件、评分办法、项目基础资料和工期质量安全目标" if materials["pending_required"] else "",
        )
    )
    profile_status = "complete" if not missing_profile_fields else ("current" if profile.get("project_name") else "pending")
    steps.append(
        _step(
            "profile",
            "补齐项目资料",
            profile_status,
            "已填写关键资料" if not missing_profile_fields else f"缺少 {len(missing_profile_fields)} 项关键资料",
            "补充结构、规模、工期、质量安全目标" if missing_profile_fields else "",
        )
    )
    steps.append(
        _step(
            "parse",
            "解析招标要求",
            "complete" if requirement_count else "current",
            f"已解析 {requirement_count} 条要求" if requirement_count else "尚未形成响应矩阵",
            "创建或上传招标文件并解析" if not requirement_count else "",
        )
    )
    steps.append(
        _step(
            "plan",
            "生成技术标目录",
            "complete" if plan_count else ("current" if requirement_count else "pending"),
            f"已规划 {plan_count} 个章节" if plan_count else "尚未生成目录规划",
            "根据招标要求生成目录规划" if requirement_count and not plan_count else "",
        )
    )
    draft_status = "complete" if plan_count and missing_plan_count == 0 else ("current" if plan_count else "pending")
    steps.append(
        _step(
            "drafts",
            "生成章节草稿",
            draft_status,
            f"已生成 {generated_plan_count}/{plan_count} 个规划章节，草稿 {draft_count} 篇" if plan_count else "等待目录规划",
            "批量生成全部章节" if plan_count and missing_plan_count else "",
        )
    )
    review_findings = int(coverage_summary.get("review_findings") or 0)
    high_missing = int(coverage_summary.get("high_priority_missing") or 0)
    review_status = "complete" if plan_count and not missing_plan_count and not high_missing and not review_findings else ("current" if draft_count else "pending")
    steps.append(
        _step(
            "review",
            "覆盖审查",
            review_status,
            f"高优先级缺口 {high_missing}，审查问题 {review_findings}" if draft_count else "等待草稿生成",
            "执行响应覆盖检查并处理问题" if draft_count and review_status != "complete" else "",
        )
    )
    export_ready = plan_count > 0 and missing_plan_count == 0 and high_missing == 0
    steps.append(
        _step(
            "export",
            "导出 Word 标书",
            "complete" if export_ready else "pending",
            "已具备导出初稿条件" if export_ready else "需先完成目录章节和高优先级条款响应",
            "导出 DOCX 后人工复核格式" if export_ready else "",
        )
    )
    delivery_status = "complete" if delivered_count else ("current" if delivery_count or export_ready else "pending")
    if latest_delivery and latest_delivery.get("status") == "已结案":
        delivery_detail = f"已结案归档，交付记录 {delivery_count} 条"
        delivery_action = ""
    elif delivered_count:
        delivery_detail = f"已交付 {delivered_count} 次，交付记录 {delivery_count} 条"
        delivery_action = "发送结案确认话术并记录客户确认"
    elif latest_delivery:
        delivery_detail = f"最新交付包状态：{latest_delivery.get('status') or '已导出'}"
        delivery_action = "确认客户接收后标记为已交付"
    elif export_ready:
        delivery_detail = "尚未导出交付包"
        delivery_action = "导出 ZIP 交付包并形成交付记录"
    else:
        delivery_detail = "等待交付包导出条件"
        delivery_action = ""
    steps.append(
        _step(
            "delivery",
            "交付归档",
            delivery_status,
            delivery_detail,
            delivery_action,
        )
    )
    feedback_status = "complete" if delivery_count and not feedback["open"] else ("current" if feedback["open"] else "pending")
    steps.append(
        _step(
            "feedback",
            "客户反馈返工",
            feedback_status,
            f"反馈 {feedback['total']} 条，未处理 {feedback['open']} 条"
            if feedback["total"]
            else "暂无客户反馈或返工记录",
            "处理客户反馈并标记为已解决" if feedback["open"] else "",
        )
    )
    closure_status = (
        "complete"
        if closed_count and not feedback["open"]
        else ("current" if delivered_count and not feedback["open"] else "pending")
    )
    if closed_count and not feedback["open"]:
        closure_detail = f"已记录 {closed_count} 条客户结案确认"
        closure_action = ""
    elif delivered_count and not feedback["open"]:
        closure_detail = "已交付且无未处理反馈，可发起结案确认"
        closure_action = "生成结案话术，收到客户确认后记录结案"
    elif feedback["open"]:
        closure_detail = f"仍有 {feedback['open']} 条反馈未处理，暂不结案"
        closure_action = "先完成返工处理"
    else:
        closure_detail = "等待交付完成"
        closure_action = ""
    steps.append(
        _step(
            "closure",
            "客户验收结案",
            closure_status,
            closure_detail,
            closure_action,
        )
    )
    retro_status_value = str((retrospective or {}).get("status") or "待复盘")
    retrospective_status = "complete" if retro_status_value == "已复盘" else ("current" if closed_count and not feedback["open"] else "pending")
    if retro_status_value == "已复盘":
        retrospective_detail = f"复盘完成，风险：{(retrospective or {}).get('risk_level') or '未评估'}，复用评分：{(retrospective or {}).get('reusable_score') or '未评估'}"
        retrospective_action = ""
    elif closed_count and not feedback["open"]:
        retrospective_detail = "已结案，等待补充成交、耗时、返工和经验标签"
        retrospective_action = "填写项目复盘台账，沉淀报价和模板经验"
    else:
        retrospective_detail = "等待客户结案后复盘"
        retrospective_action = ""
    steps.append(
        _step(
            "retrospective",
            "项目复盘沉淀",
            retrospective_status,
            retrospective_detail,
            retrospective_action,
        )
    )

    next_step = next((step for step in steps if step["status"] in {"current", "pending"}), steps[-1])
    result = {
        "tender_id": tender_id,
        "tender_name": tender["name"],
        "summary": {
            "profile_missing": missing_profile_fields,
            "task_missing": missing_task,
            "materials": materials,
            "requirements": requirement_count,
            "plans": plan_count,
            "generated_plans": generated_plan_count,
            "missing_plans": missing_plan_count,
            "drafts": draft_count,
            "draft_coverage_rate": coverage_summary.get("draft_coverage_rate", 0),
            "export_ready": export_ready,
            "delivery_records": delivery_count,
            "delivered_records": delivered_count,
            "latest_delivery": latest_delivery or {},
            "closure_records": closed_count,
            "latest_closure": latest_closure or {},
            "retrospective": retrospective or {},
            "feedback": feedback,
        },
        "steps": steps,
        "next_step": next_step,
        "confirmations": list_workflow_confirmations(tender_id, conn=conn)["items"],
    }
    if own_conn:
        conn.close()
    return result
