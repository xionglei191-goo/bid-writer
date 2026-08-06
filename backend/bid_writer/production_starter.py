from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .command_center import build_command_center
from .db import connect, row_to_dict
from .intake_assistant import build_intake_assistant
from .materials import DONE_STATUSES, list_material_items, material_summary
from .order_confirmation import build_order_confirmation
from .payments import payment_summary
from .pricing import build_price_quote
from .production_readiness import build_production_readiness
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


def _card(key: str, label: str, value: Any, detail: str, status: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "detail": detail,
        "status": status,
    }


def _check(
    key: str,
    title: str,
    status: str,
    detail: str,
    action: str,
    action_code: str = "scroll",
    target: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "action": action,
        "action_code": action_code,
        "target": target,
    }


def _is_done(status: str) -> bool:
    return str(status or "") in DONE_STATUSES


def _platform_label(platform: str) -> str:
    text = str(platform or "").strip()
    if not text:
        return "未登记渠道"
    if any(word in text for word in ("闲鱼", "咸鱼", "Xianyu")):
        return "闲鱼"
    if any(word in text for word in ("微信", "企微", "企业微信")):
        return "微信"
    return text


def _channel_policy(platform: str) -> dict[str, Any]:
    label = _platform_label(platform)
    is_marketplace = label in {"闲鱼"} or any(word in label for word in ("平台", "淘宝", "拼多多"))
    return {
        "platform": label,
        "mode": "人工确认后半自动交付" if is_marketplace else "人工确认后交付",
        "automation_boundary": "只生成可复制话术、资料清单和交付说明；不自动登录平台、不自动收款、不自动点击发货。",
        "manual_confirm": [
            "确认客户已接受订单范围、费用、交付期限和修改轮次。",
            "确认收款状态或定金安排后再发送正式交付包。",
            "确认交付文件无旧项目名、缺章、来源缺失和明显空泛内容。",
            "在平台或聊天工具中由人工复制发送，不让系统代替账号操作。",
        ],
        "copy_assets": [
            "接单回复",
            "订单确认话术",
            "资料催补清单",
            "交付说明",
            "结案确认话术",
        ],
        "do_not_automate": [
            "绕过平台规则自动接单、自动催付或自动发货。",
            "批量私信、刷单、虚假承诺中标结果或承诺平台外交易。",
            "未人工复核交付包就向客户发送最终稿。",
        ],
    }


def _decision(
    intake: dict[str, Any],
    readiness: dict[str, Any],
    task: dict[str, Any],
    material_stats: dict[str, Any],
) -> dict[str, str]:
    acceptance = intake.get("acceptance") or {}
    readiness_summary = readiness.get("summary") or {}
    acceptance_decision = str(acceptance.get("decision") or "")
    readiness_key = str(readiness_summary.get("readiness") or "")

    if acceptance_decision == "暂缓接单":
        return {
            "decision": "先补资料再接单",
            "state": "blocked",
            "next_action": acceptance.get("reason") or "补齐招标文件和关键资料后重新评估。",
        }
    if not task.get("customer_name") or not task.get("deadline"):
        return {
            "decision": "可评估，待确认订单信息",
            "state": "needs_work",
            "next_action": "补齐客户名称、来源渠道、交付期限和交付格式，再生成订单确认单。",
        }
    if int(material_stats.get("pending_required") or 0):
        return {
            "decision": "可接单，需催补资料",
            "state": "needs_work",
            "next_action": "先把必要资料缺口发给客户确认，生产内容按已具备资料出初稿。",
        }
    if readiness_key in {"ready_to_produce", "ready_for_final_review", "ready_to_deliver"}:
        return {
            "decision": "可进入生产",
            "state": "ready",
            "next_action": str(readiness_summary.get("workflow_next_step") or "按目录生成章节并进入人工复核。"),
        }
    if readiness_key == "blocked":
        return {
            "decision": "已接单但暂缓生产",
            "state": "blocked",
            "next_action": (readiness.get("next_actions") or ["先处理可交付性评估中的阻断项。"])[0],
        }
    return {
        "decision": "可继续推进",
        "state": "needs_work",
        "next_action": (readiness.get("next_actions") or ["按指挥台下一步推进。"])[0],
    }


def _checklist(
    intake: dict[str, Any],
    quote: dict[str, Any],
    order_confirmation: dict[str, Any],
    task: dict[str, Any],
    materials: list[dict[str, Any]],
    readiness: dict[str, Any],
    command: dict[str, Any],
) -> list[dict[str, Any]]:
    acceptance = intake.get("acceptance") or {}
    readiness_summary = readiness.get("summary") or {}
    pending_required = [item for item in materials if item.get("required") and not _is_done(str(item.get("status") or ""))]
    requirement_count = int(readiness_summary.get("requirements") or 0)
    section_count = int(readiness_summary.get("total_sections") or 0)
    generated_sections = int(readiness_summary.get("generated_sections") or 0)
    quote_ready = bool(quote.get("suggested_price"))
    confirmation_ready = bool((order_confirmation.get("customer_message") or "").strip())
    command_next = command.get("headline") or {}
    plan_action_code = "scroll"
    if not section_count:
        plan_action_code = "build_plan"
    elif generated_sections < section_count:
        plan_action_code = "generate_all"

    return [
        _check(
            "intake",
            "接单判断",
            "blocked" if acceptance.get("decision") == "暂缓接单" else "complete",
            f"{acceptance.get('decision') or '待判断'}：{acceptance.get('reason') or ''}",
            "补充客户原始消息或完整招标文件后重新评估。",
            "scroll",
            "stage-intake",
        ),
        _check(
            "task",
            "订单基础信息",
            "complete" if task.get("customer_name") and task.get("deadline") and task.get("deliverable_format") else "pending",
            f"客户：{task.get('customer_name') or '未登记'}；期限：{task.get('deadline') or '未登记'}；格式：{task.get('deliverable_format') or '未登记'}。",
            "补齐生产任务信息，作为生产排期和交付边界。",
            "scroll",
            "stage-task",
        ),
        _check(
            "quote",
            "报价与范围",
            "complete" if quote_ready and confirmation_ready else "pending",
            f"报价：{quote.get('suggested_price') or '待测算'}；订单确认单：{'已生成' if confirmation_ready else '待生成'}。",
            "生成报价测算和订单确认单，发给客户确认后再正式开工。",
            "scroll",
            "stage-payments",
        ),
        _check(
            "materials",
            "必要资料",
            "complete" if not pending_required else "pending",
            f"必要资料待补 {len(pending_required)} 项。",
            "将资料缺口复制给客户，补齐完整招标文件、评分办法、项目资料和目标要求。",
            "scroll",
            "stage-materials",
        ),
        _check(
            "requirements",
            "招标解析",
            "complete" if requirement_count else "pending",
            f"已形成 {requirement_count} 条响应要求。",
            "解析招标文件，形成响应矩阵后再规划目录。",
            "parse_current",
            "stage-source",
        ),
        _check(
            "plan",
            "目录与章节",
            "complete" if section_count and generated_sections == section_count else "pending",
            f"章节生成 {generated_sections}/{section_count}。",
            str(command_next.get("next_step_action") or "生成目录规划并批量生成章节。"),
            plan_action_code,
            "stage-plan",
        ),
    ]


def _customer_material_text(materials: list[dict[str, Any]]) -> str:
    pending = [item for item in materials if item.get("required") and not _is_done(str(item.get("status") or ""))]
    if not pending:
        return "目前必要资料已基本具备，后续如有格式模板、图纸或特殊要求可继续补充。"
    lines = ["为保证技术标初稿准确，请优先补充以下资料："]
    for index, item in enumerate(pending[:8], 1):
        lines.append(f"{index}. {item.get('name') or ''}：{item.get('notes') or item.get('source') or '用于响应招标要求和项目化编制。'}")
    return "\n".join(lines)


def build_production_starter(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    intake = build_intake_assistant(tender_id, conn=conn)
    quote = build_price_quote(tender_id, conn=conn)
    order_confirmation = build_order_confirmation(tender_id, conn=conn)
    materials = list_material_items(tender_id, conn=conn)
    material_stats = material_summary(tender_id, conn=conn)
    payment = payment_summary(tender_id, conn=conn)
    readiness = build_production_readiness(tender_id, conn=conn)
    command = build_command_center(tender_id, conn=conn)
    decision = _decision(intake, readiness, task, material_stats)
    channel = _channel_policy(str(task.get("source_platform") or intake.get("input", {}).get("source_platform") or ""))
    checks = _checklist(intake, quote, order_confirmation, task, materials, readiness, command)
    pending_checks = [item for item in checks if item.get("status") in {"pending", "blocked"}]
    operator_actions = command.get("primary_actions") or []

    cards = [
        _card(
            "decision",
            "启动判断",
            decision["decision"],
            decision["next_action"],
            decision["state"],
        ),
        _card(
            "price",
            "建议报价",
            quote.get("suggested_price") or "待测算",
            f"预计工作量 {quote.get('workload') or '待估算'}，周期 {quote.get('turnaround') or '待确认'}。",
            "ready" if quote.get("suggested_price") else "needs_work",
        ),
        _card(
            "materials",
            "必要资料",
            f"{material_stats.get('required_completed', 0)}/{material_stats.get('required', 0)}",
            f"待补 {material_stats.get('pending_required', 0)} 项。",
            "ready" if not material_stats.get("pending_required") else "needs_work",
        ),
        _card(
            "payment",
            "收款",
            payment.get("status_label") or "待确认",
            f"已收 {payment.get('received_amount', 0)} 元，未收 {payment.get('outstanding_amount', 0)} 元。",
            "ready" if not payment.get("requires_payment_confirmation") else "needs_work",
        ),
        _card(
            "readiness",
            "生产判断",
            (readiness.get("summary") or {}).get("decision") or "待评估",
            f"阻断 {(readiness.get('summary') or {}).get('blockers', 0)} 项，提醒 {(readiness.get('summary') or {}).get('warnings', 0)} 项。",
            "ready" if decision["state"] == "ready" else "needs_work",
        ),
        _card(
            "channel",
            "渠道模式",
            channel["mode"],
            channel["automation_boundary"],
            "ready",
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
        "project": {
            "name": profile.get("project_name") or tender.get("name") or "",
            "type": profile.get("project_type") or intake.get("project", {}).get("type") or "",
            "scope": profile.get("contract_scope") or "",
            "quality_target": profile.get("quality_target") or "",
            "safety_target": profile.get("safety_target") or "",
        },
        "summary": {
            "strategy": "标书生产工具优先",
            "decision": decision["decision"],
            "state": decision["state"],
            "next_action": decision["next_action"],
            "pending_checks": len(pending_checks),
            "channel_mode": channel["mode"],
            "score": (readiness.get("summary") or {}).get("score", 0),
        },
        "cards": cards,
        "start_checklist": checks,
        "operator_actions": operator_actions,
        "customer_reply": intake.get("reply_message") or "",
        "customer_material_request": _customer_material_text(materials),
        "order_confirmation_message": order_confirmation.get("customer_message") or "",
        "channel_policy": channel,
        "snapshots": {
            "task": task,
            "intake": intake,
            "quote": quote,
            "order_confirmation": order_confirmation,
            "materials": material_stats,
            "payment": payment,
            "readiness_summary": readiness.get("summary") or {},
            "command_headline": command.get("headline") or {},
        },
    }
    result["markdown"] = render_production_starter_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_production_starter_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    channel = report.get("channel_policy") or {}
    lines = [
        "# 生产启动包",
        "",
        "## 启动结论",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        f"- 生成时间：{report.get('generated_at') or ''}",
        f"- 产品策略：{summary.get('strategy') or ''}",
        f"- 启动判断：{summary.get('decision') or ''}",
        f"- 下一步：{summary.get('next_action') or ''}",
        f"- 渠道模式：{summary.get('channel_mode') or ''}",
        "",
        "## 指标卡",
    ]
    for card in report.get("cards") or []:
        lines.append(f"- {card.get('label')}：{card.get('value')}。{card.get('detail')}")
    lines.extend(["", "## 开工清单"])
    for item in report.get("start_checklist") or []:
        lines.append(f"- [{item.get('status')}] {item.get('title')}：{item.get('detail')}")
        if item.get("action"):
            lines.append(f"  - 建议：{item.get('action')}")
    lines.extend(["", "## 渠道边界", f"- 平台：{channel.get('platform') or ''}", f"- 模式：{channel.get('mode') or ''}"])
    lines.append(f"- 边界：{channel.get('automation_boundary') or ''}")
    lines.extend(["", "### 必须人工确认"])
    for item in channel.get("manual_confirm") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### 不自动化"])
    for item in channel.get("do_not_automate") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 客户接单回复",
            "",
            report.get("customer_reply") or "",
            "",
            "## 资料催补清单",
            "",
            report.get("customer_material_request") or "",
            "",
            "## 订单确认话术",
            "",
            report.get("order_confirmation_message") or "",
        ]
    )
    return "\n".join(lines).strip() + "\n"
