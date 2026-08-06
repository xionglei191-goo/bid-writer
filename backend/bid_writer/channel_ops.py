from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .closure_confirmation import build_closure_confirmation
from .communications import list_communications
from .db import connect, row_to_dict
from .delivery_assistant import build_delivery_assistant
from .order_wizard import build_order_wizard
from .production_starter import build_production_starter
from .production_tasks import get_production_task


def _status(done: bool, available: bool = True) -> str:
    if done:
        return "complete"
    return "pending" if available else "blocked"


def _platform_label(task: dict[str, Any], starter: dict[str, Any]) -> str:
    policy = starter.get("channel_policy") or {}
    platform = str(policy.get("platform") or task.get("source_platform") or "").strip()
    return platform or "闲鱼"


def _listing_title(tender: dict[str, Any], task: dict[str, Any]) -> str:
    industry = str(tender.get("industry") or "").strip()
    base = f"{industry}技术标" if industry else "工程技术标"
    return f"{base}/施工组织设计初稿编制｜响应矩阵+章节草稿+交付包"


def _listing_description(tender: dict[str, Any], task: dict[str, Any]) -> str:
    industry = str(tender.get("industry") or "房建、市政、学校、医院、厂房等工程").strip()
    deliverable = str(task.get("deliverable_format") or "Word 初稿 + ZIP 归档包").strip()
    return "\n".join(
        [
            "可协助整理技术标/施工组织设计初稿，适合已有招标文件、评分办法或技术要求的项目。",
            f"适用方向：{industry}。",
            f"交付内容：{deliverable}，通常包含目录规划、章节初稿、响应要点、资料清单和基础审查。",
            "下单前请先发送招标文件、评分办法、项目概况、工期质量安全目标、投标单位资料和格式要求，我会先判断能否承接并确认费用、周期和修改范围。",
            "说明：不承诺中标结果，不代替最终投标审核、报价、盖章和平台外违规交易；正式递交前请人工复核专用条款、签章、页码目录和企业资质。",
        ]
    )


def _script(key: str, label: str, stage: str, text: str, usage: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    return {
        "key": key,
        "label": label,
        "stage": stage,
        "usage": usage,
        "text": clean,
        "status": "ready" if clean else "pending",
        "length": len(clean),
    }


def _progress_text(tender: dict[str, Any], wizard: dict[str, Any]) -> str:
    summary = wizard.get("summary") or {}
    project = tender.get("name") or "当前项目"
    step = summary.get("current_step") or "继续生产"
    action = summary.get("current_action") or "按计划推进"
    return "\n".join(
        [
            "您好，项目正在按确认范围推进中。",
            f"{project} 当前进度：{summary.get('completed_steps', 0)}/{summary.get('total_steps', 0)}，当前环节是“{step}”。",
            f"下一步我会先处理：{action}。",
            "如您补充了评分办法、图纸、企业资料或格式模板，我会同步纳入初稿调整。",
        ]
    )


def _after_sales_text(task: dict[str, Any]) -> str:
    customer = task.get("customer_name") or "您好"
    return "\n".join(
        [
            f"{customer}，收到后您可以先重点核对项目名称、工期、质量安全目标、目录层级、评分点响应和格式要求。",
            "如需修改，请把要调整的位置、招标条款或截图一起发我，我会按已确认的修改轮次处理。",
            "涉及新增大范围章节、重新更换招标文件、商务报价、资质证照、签章装订或承诺中标结果的内容，需要另行确认范围。",
        ]
    )


def _checklist(
    starter: dict[str, Any],
    wizard: dict[str, Any],
    delivery: dict[str, Any],
    closure: dict[str, Any],
    communications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    starter_summary = starter.get("summary") or {}
    delivery_summary = delivery.get("summary") or {}
    closure_summary = closure.get("summary") or {}
    pending_communications = [
        item for item in communications if item.get("status") in {"待发送", "需跟进"}
    ]
    wizard_summary = wizard.get("summary") or {}
    return [
        {
            "key": "listing",
            "title": "商品说明只做可复制文案",
            "status": "complete",
            "detail": "系统生成标题和说明，是否发布、如何发布由人工在平台确认。",
        },
        {
            "key": "intake",
            "title": "接单判断",
            "status": "complete" if starter_summary.get("decision") else "pending",
            "detail": starter_summary.get("decision") or "待生成接单判断。",
        },
        {
            "key": "copy",
            "title": "客户话术",
            "status": "pending" if pending_communications else "complete",
            "detail": f"待发送或需跟进沟通 {len(pending_communications)} 条。",
        },
        {
            "key": "production",
            "title": "生产推进",
            "status": "complete" if wizard_summary.get("state") == "ready" else "pending",
            "detail": f"当前步骤：{wizard_summary.get('current_step') or '待开始'}。",
        },
        {
            "key": "delivery",
            "title": "人工交付",
            "status": _status(bool(delivery_summary.get("has_package")), available=True),
            "detail": f"交付状态：{delivery_summary.get('delivery_status') or '待生产'}。",
        },
        {
            "key": "closure",
            "title": "验收结案",
            "status": "complete" if closure_summary.get("closure_status") == "已结案" else "pending",
            "detail": f"结案状态：{closure_summary.get('closure_status') or '待客户确认'}。",
        },
    ]


def build_channel_ops(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    task = get_production_task(tender_id, conn=conn)
    starter = build_production_starter(tender_id, conn=conn)
    wizard = build_order_wizard(tender_id, conn=conn)
    delivery = build_delivery_assistant(tender_id, conn=conn)
    closure = build_closure_confirmation(tender_id, conn=conn)
    communications = list_communications(tender_id, conn=conn)
    policy = starter.get("channel_policy") or {}
    platform = _platform_label(task, starter)
    scripts = [
        _script("listing_title", "商品标题", "发布前", _listing_title(tender, task), "复制到平台商品标题或服务标题。"),
        _script("listing_description", "商品说明", "发布前", _listing_description(tender, task), "复制到平台商品详情，人工确认后发布。"),
        _script("first_reply", "接单回复", "询盘", starter.get("customer_reply") or "", "客户首次咨询时复制发送。"),
        _script("material_request", "资料催补", "资料", starter.get("customer_material_request") or "", "客户资料不完整时复制发送。"),
        _script("order_confirmation", "订单确认", "确认", starter.get("order_confirmation_message") or "", "报价、范围和修改轮次确认时复制发送。"),
        _script("progress_update", "进度说明", "生产", _progress_text(tender, wizard), "客户询问进度时复制发送。"),
        _script("delivery_message", "发货说明", "交付", delivery.get("customer_message") or "", "人工上传交付包后复制发送。"),
        _script("closure_message", "验收结案", "结案", closure.get("customer_message") or "", "客户收货后确认结案时复制发送。"),
        _script("after_sales_boundary", "售后边界", "售后", _after_sales_text(task), "客户提出修改或新增范围时复制发送。"),
        _script("automation_boundary", "自动化边界", "风控", policy.get("automation_boundary") or "", "内部确认渠道合规边界。"),
    ]
    ready_scripts = [item for item in scripts if item["status"] == "ready"]
    checklist = _checklist(starter, wizard, delivery, closure, communications)
    pending_actions = [item for item in checklist if item["status"] != "complete"]
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": {
            "id": tender["id"],
            "name": tender["name"],
            "industry": tender.get("industry") or "",
            "region": tender.get("region") or "",
        },
        "summary": {
            "title": "渠道运营助手",
            "platform": platform,
            "mode": policy.get("mode") or "人工确认后交付",
            "state": "ready" if not pending_actions else "needs_work",
            "copy_assets": len(ready_scripts),
            "pending_actions": len(pending_actions),
            "current_step": (wizard.get("summary") or {}).get("current_step") or "",
            "recommended_script_key": next((item["key"] for item in scripts if item["status"] == "ready"), ""),
            "automation_boundary": policy.get("automation_boundary") or "",
        },
        "policy": {
            "platform": platform,
            "mode": policy.get("mode") or "",
            "automation_boundary": policy.get("automation_boundary") or "",
            "manual_confirm": policy.get("manual_confirm") or [],
            "do_not_automate": policy.get("do_not_automate") or [],
        },
        "checklist": checklist,
        "scripts": scripts,
        "snapshots": {
            "starter_summary": starter.get("summary") or {},
            "wizard_summary": wizard.get("summary") or {},
            "delivery_summary": delivery.get("summary") or {},
            "closure_summary": closure.get("summary") or {},
            "communications_total": len(communications),
        },
    }
    result["markdown"] = render_channel_ops_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_channel_ops_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    policy = report.get("policy") or {}
    lines = [
        "# 渠道运营助手",
        "",
        "## 概览",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        f"- 生成时间：{report.get('generated_at') or ''}",
        f"- 渠道：{summary.get('platform') or ''}",
        f"- 模式：{summary.get('mode') or ''}",
        f"- 可复制话术：{summary.get('copy_assets', 0)} 条",
        f"- 待处理动作：{summary.get('pending_actions', 0)} 项",
        "",
        "## 合规边界",
        f"- {summary.get('automation_boundary') or ''}",
        "",
        "### 必须人工确认",
    ]
    for item in policy.get("manual_confirm") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### 不自动化"])
    for item in policy.get("do_not_automate") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## 渠道检查清单"])
    for item in report.get("checklist") or []:
        lines.append(f"- [{item.get('status')}] {item.get('title')}：{item.get('detail')}")
    lines.extend(["", "## 可复制话术"])
    for item in report.get("scripts") or []:
        lines.extend(
            [
                "",
                f"### {item.get('label')}",
                f"- 阶段：{item.get('stage')}",
                f"- 用法：{item.get('usage')}",
                "",
                item.get("text") or "待生成",
            ]
        )
    return "\n".join(lines).strip() + "\n"
