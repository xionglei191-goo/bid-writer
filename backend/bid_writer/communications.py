from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .closure_confirmation import build_closure_confirmation
from .db import connect, row_to_dict, rows_to_dicts
from .delivery_assistant import build_delivery_assistant
from .feedback import feedback_summary
from .intake_assistant import build_intake_assistant
from .materials import material_summary
from .order_confirmation import build_order_confirmation
from .pricing import build_price_quote
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


COMMUNICATION_FIELDS = (
    "stage",
    "direction",
    "channel",
    "customer_message",
    "system_reply",
    "status",
    "notes",
)

STAGE_LABELS = {
    "inquiry": "询盘",
    "quote": "报价",
    "materials": "资料催补",
    "confirmation": "订单确认",
    "delivery": "交付",
    "aftersales": "售后反馈",
    "closure": "结案确认",
}


def _stage_label(stage: str) -> str:
    text = (stage or "").strip()
    return STAGE_LABELS.get(text, text or "询盘")


def _pending_materials(tender_id: int, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return material_summary(tender_id, conn=conn).get("pending_required_items", [])


def _join_items(items: list[str], fallback: str) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "、".join(cleaned) if cleaned else fallback


def _project_name(tender: dict[str, Any], profile: dict[str, Any]) -> str:
    return str(profile.get("project_name") or tender.get("name") or "本项目")


def _build_material_reply(tender_id: int, conn: sqlite3.Connection) -> str:
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()) or {}
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    pending = _pending_materials(tender_id, conn)
    pending_names = [str(item.get("name") or "") for item in pending]
    customer = task.get("customer_name") or "您好"
    project = _project_name(tender, profile)
    if pending_names:
        pending_text = _join_items(pending_names, "完整招标文件、评分办法、项目基础资料")
        return "\n".join(
            [
                f"{customer}，{project} 这边我可以继续往下做。",
                f"为了避免后面返工，麻烦先补充或确认：{pending_text}。",
                "资料齐后我会按最终招标文件重新核对目录、评分点和废标风险，再进入正式编制。",
                "如果暂时没有完整资料，也可以先做目录和章节框架，但正式初稿质量需要以补齐资料为前提。",
            ]
        )
    return "\n".join(
        [
            f"{customer}，{project} 当前关键资料基本够用。",
            "我会继续按招标要求推进章节编制，正式交付前还会再做项目名、工期、质量安全目标和引用来源复核。",
        ]
    )


def _build_aftersales_reply(tender_id: int, customer_message: str, conn: sqlite3.Connection) -> str:
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()) or {}
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    feedback = feedback_summary(tender_id, conn=conn)
    customer = task.get("customer_name") or "您好"
    project = _project_name(tender, profile)
    lines = [
        f"{customer}，收到 {project} 的修改反馈。",
        "我会先核对这次反馈是否属于原招标范围内的合理修改，再按章节逐项处理。",
    ]
    if customer_message.strip():
        lines.append("你刚才提到的内容我会作为本轮修改依据保留。")
    if feedback.get("open"):
        lines.append(f"系统里当前还有 {feedback['open']} 条未处理反馈，我会和本次意见一起归并处理，避免重复返工。")
    lines.append("修改完成后会重新检查项目名称、条款响应和交付文件清单，再发你确认。")
    return "\n".join(lines)


def _build_default_reply(tender_id: int, data: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    stage = str(data.get("stage") or "inquiry")
    customer_message = str(data.get("customer_message") or "")
    channel = str(data.get("channel") or "")
    stage_label = _stage_label(stage)
    common_payload = {
        "customer_message": customer_message,
        "source_platform": channel,
    }

    if stage in {"inquiry", "询盘", "接单"}:
        report = build_intake_assistant(tender_id, common_payload, conn=conn)
        return {
            "stage": stage_label,
            "reply": report.get("reply_message") or "",
            "source": "接单评估",
            "summary": {
                "decision": (report.get("acceptance") or {}).get("decision"),
                "suggested_price": (report.get("estimate") or {}).get("suggested_price"),
            },
        }

    if stage in {"quote", "报价"}:
        report = build_price_quote(tender_id, common_payload, conn=conn)
        return {
            "stage": stage_label,
            "reply": report.get("customer_message") or "",
            "source": "报价测算",
            "summary": {
                "suggested_price": report.get("suggested_price"),
                "workload": report.get("workload"),
                "turnaround": report.get("turnaround"),
            },
        }

    if stage in {"materials", "资料催补", "补资料"}:
        reply = _build_material_reply(tender_id, conn)
        return {
            "stage": stage_label,
            "reply": reply,
            "source": "资料清单",
            "summary": {"pending_required": len(_pending_materials(tender_id, conn))},
        }

    if stage in {"confirmation", "订单确认", "确认"}:
        report = build_order_confirmation(tender_id, conn=conn)
        return {
            "stage": stage_label,
            "reply": report.get("customer_message") or "",
            "source": "订单确认单",
            "summary": report.get("commercial") or {},
        }

    if stage in {"delivery", "交付", "发货"}:
        report = build_delivery_assistant(tender_id, conn=conn)
        return {
            "stage": stage_label,
            "reply": report.get("customer_message") or "",
            "source": "交付说明",
            "summary": report.get("summary") or {},
        }

    if stage in {"aftersales", "售后反馈", "返工"}:
        reply = _build_aftersales_reply(tender_id, customer_message, conn)
        return {
            "stage": stage_label,
            "reply": reply,
            "source": "反馈处理",
            "summary": feedback_summary(tender_id, conn=conn),
        }

    if stage in {"closure", "结案确认", "结案"}:
        report = build_closure_confirmation(tender_id, conn=conn)
        return {
            "stage": stage_label,
            "reply": report.get("customer_message") or "",
            "source": "结案确认单",
            "summary": report.get("summary") or {},
        }

    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()) or {}
    project = _project_name(tender, profile)
    customer = task.get("customer_name") or "您好"
    return {
        "stage": stage_label,
        "reply": f"{customer}，收到 {project} 的需求。我先核对资料和招标要求，确认后再给你明确的交付范围、时间和费用。",
        "source": "通用回复",
        "summary": {},
    }


def suggest_communication_reply(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    payload = data or {}
    suggestion = _build_default_reply(tender_id, payload, conn)
    result = {
        "tender_id": tender_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stage": suggestion["stage"],
        "channel": str(payload.get("channel") or payload.get("source_platform") or ""),
        "customer_message": str(payload.get("customer_message") or ""),
        "reply": suggestion["reply"],
        "source": suggestion["source"],
        "summary": suggestion["summary"],
        "safety_note": "仅生成可复制话术，接单、收款和发送仍需人工确认并遵守平台规则。",
    }
    if own_conn:
        conn.close()
    return result


def list_communications(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM customer_communications
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def create_communication(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    if not row_to_dict(conn.execute("SELECT id FROM tenders WHERE id = ?", (tender_id,)).fetchone()):
        raise ValueError(f"Tender not found: {tender_id}")
    stage = _stage_label(str(data.get("stage") or "inquiry"))
    reply = str(data.get("system_reply") or data.get("reply") or "").strip()
    if not reply:
        reply = suggest_communication_reply(tender_id, data, conn=conn)["reply"]
    cleaned = {
        "stage": stage,
        "direction": str(data.get("direction") or "outgoing").strip(),
        "channel": str(data.get("channel") or data.get("source_platform") or "").strip(),
        "customer_message": str(data.get("customer_message") or "").strip(),
        "system_reply": reply,
        "status": str(data.get("status") or "待发送").strip(),
        "notes": str(data.get("notes") or "").strip(),
    }
    with conn:
        cur = conn.execute(
            """
            INSERT INTO customer_communications (
                tender_id, stage, direction, channel, customer_message, system_reply, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tender_id, *[cleaned[field] for field in COMMUNICATION_FIELDS]),
        )
    record = row_to_dict(conn.execute("SELECT * FROM customer_communications WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return record


def update_communication(
    communication_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = row_to_dict(conn.execute("SELECT * FROM customer_communications WHERE id = ?", (communication_id,)).fetchone())
    if not current:
        raise ValueError(f"Communication not found: {communication_id}")
    cleaned: dict[str, Any] = {}
    for field in COMMUNICATION_FIELDS:
        if field not in data:
            continue
        value = str(data.get(field) or "").strip()
        cleaned[field] = _stage_label(value) if field == "stage" else value
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE customer_communications
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*cleaned.values(), communication_id),
            )
    record = row_to_dict(conn.execute("SELECT * FROM customer_communications WHERE id = ?", (communication_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return record


def delete_communication(communication_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        cur = conn.execute("DELETE FROM customer_communications WHERE id = ?", (communication_id,))
    if own_conn:
        conn.close()
    return {"communication_id": communication_id, "deleted": cur.rowcount > 0}


def render_communications_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    records = list_communications(tender_id, conn=conn)
    lines = ["# 客户沟通记录", ""]
    if not records:
        lines.append("> 暂无沟通记录。")
    for index, item in enumerate(records, 1):
        lines.extend(
            [
                f"## {index}. {item.get('stage') or '沟通记录'}",
                "",
                f"- 渠道：{item.get('channel') or '未登记'}",
                f"- 方向：{item.get('direction') or 'outgoing'}",
                f"- 状态：{item.get('status') or '待发送'}",
                f"- 时间：{item.get('created_at') or ''}",
                "",
                "### 客户原文",
                "",
                item.get("customer_message") or "未记录客户原文。",
                "",
                "### 系统建议回复",
                "",
                item.get("system_reply") or "未生成回复。",
            ]
        )
        if item.get("notes"):
            lines.extend(["", "### 备注", "", str(item.get("notes") or "")])
        lines.append("")
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
