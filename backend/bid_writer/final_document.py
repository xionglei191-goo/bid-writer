from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .coverage_report import build_coverage_report
from .db import connect, row_to_dict, rows_to_dicts
from .delivery_review import build_delivery_review
from .final_checklist import build_final_checklist
from .quality_gate import build_quality_gate


FINAL_DOCUMENT_FIELDS = {"status", "approved_by", "notes", "checklist_json"}


def _content_with_heading(content: str, section_title: str) -> str:
    lines = content.strip().splitlines()
    if not lines:
        return f"# {section_title}\n\n> 本章尚未生成。"
    if lines[0].startswith("# "):
        lines[0] = f"# {section_title}"
        return "\n".join(lines).strip()
    return f"# {section_title}\n\n{content.strip()}"


def _ordered_draft_entries(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    planned_rows = rows_to_dicts(
        conn.execute(
            """
            SELECT
                sp.id AS plan_id,
                sp.order_no,
                sp.section_title AS plan_section_title,
                sp.status AS plan_status,
                sp.draft_id AS plan_draft_id,
                d.id AS draft_id,
                d.section_title AS draft_section_title,
                d.content,
                d.citations_json
            FROM section_plans sp
            LEFT JOIN drafts d ON d.id = sp.draft_id
            WHERE sp.tender_id = ?
            ORDER BY sp.order_no, sp.id
            """,
            (tender_id,),
        ).fetchall()
    )
    if not planned_rows:
        drafts = rows_to_dicts(conn.execute("SELECT * FROM drafts WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
        return [
            {
                "section_title": draft["section_title"],
                "content": draft["content"],
                "citations": json.loads(draft.get("citations_json") or "[]"),
                "draft_id": draft["id"],
                "missing": False,
            }
            for draft in drafts
        ]

    entries: list[dict[str, Any]] = []
    used_draft_ids: set[int] = set()
    for row in planned_rows:
        draft_id = row.get("draft_id")
        if draft_id:
            used_draft_ids.add(int(draft_id))
            entries.append(
                {
                    "section_title": row["plan_section_title"] or row["draft_section_title"],
                    "content": row.get("content") or "",
                    "citations": json.loads(row.get("citations_json") or "[]"),
                    "draft_id": int(draft_id),
                    "plan_id": row["plan_id"],
                    "order_no": row["order_no"],
                    "missing": False,
                }
            )
        else:
            entries.append(
                {
                    "section_title": row["plan_section_title"],
                    "content": "",
                    "citations": [],
                    "draft_id": None,
                    "plan_id": row["plan_id"],
                    "order_no": row["order_no"],
                    "missing": True,
                }
            )

    if used_draft_ids:
        placeholders = ",".join("?" for _ in used_draft_ids)
        orphan_rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT *
                FROM drafts
                WHERE tender_id = ? AND id NOT IN ({placeholders})
                ORDER BY id
                """,
                [tender_id, *sorted(used_draft_ids)],
            ).fetchall()
        )
    else:
        orphan_rows = rows_to_dicts(conn.execute("SELECT * FROM drafts WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    for draft in orphan_rows:
        entries.append(
            {
                "section_title": draft["section_title"],
                "content": draft["content"],
                "citations": json.loads(draft.get("citations_json") or "[]"),
                "draft_id": draft["id"],
                "missing": False,
                "orphan": True,
            }
        )
    return entries


def compose_final_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    entries = _ordered_draft_entries(conn, tender_id)
    lines = [f"# {tender['name']}", "", "## 技术标章节"]
    for entry in entries:
        lines.append("")
        if entry.get("missing"):
            lines.append(f"# {entry['section_title']}")
            lines.append("")
            lines.append("> 本章尚未生成。请在目录规划中生成本章后再导出正式稿。")
            continue
        content = str(entry.get("content") or "").strip()
        lines.append(_content_with_heading(content, str(entry["section_title"])))
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"


def _ensure_record(tender_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    row = row_to_dict(conn.execute("SELECT * FROM final_documents WHERE tender_id = ?", (tender_id,)).fetchone())
    if row:
        return row
    with conn:
        cur = conn.execute("INSERT INTO final_documents (tender_id) VALUES (?)", (tender_id,))
    return row_to_dict(conn.execute("SELECT * FROM final_documents WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    try:
        checklist = json.loads(record.get("checklist_json") or "[]")
    except json.JSONDecodeError:
        checklist = []
    record["checklist"] = checklist if isinstance(checklist, list) else []
    return record


def _section_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, 1):
        content = str(entry.get("content") or "")
        rows.append(
            {
                "order_no": entry.get("order_no") or index,
                "section_title": entry.get("section_title") or "",
                "draft_id": entry.get("draft_id"),
                "status": "missing" if entry.get("missing") else "generated",
                "char_count": len(content),
                "citations": len(entry.get("citations") or []),
                "preview": content.strip().replace("\n", " ")[:160],
                "orphan": bool(entry.get("orphan")),
            }
        )
    return rows


def _warnings(
    sections: list[dict[str, Any]],
    coverage: dict[str, Any],
    quality_gate: dict[str, Any],
    final_checklist: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    missing_sections = [item for item in sections if item["status"] == "missing"]
    if missing_sections:
        warnings.append({"level": "blocker", "title": "存在未生成章节", "detail": f"{len(missing_sections)} 个目录章节尚未生成。"})
    high_missing = int((coverage.get("summary") or {}).get("high_priority_missing") or 0)
    if high_missing:
        warnings.append({"level": "blocker", "title": "高优先级条款未覆盖", "detail": f"{high_missing} 条高优先级要求尚未形成草稿响应。"})
    quality_score = int((quality_gate.get("summary") or {}).get("score") or 0)
    if quality_score and quality_score < 70:
        warnings.append({"level": "warning", "title": "质量门禁分偏低", "detail": f"当前质量分为 {quality_score}，建议修订后再定稿。"})
    required_open = int((final_checklist.get("summary") or {}).get("required_open") or 0)
    if required_open:
        warnings.append({"level": "warning", "title": "最终核对未完成", "detail": f"{required_open} 个必核项尚未人工确认。"})
    uncited = [item for item in sections if item["status"] == "generated" and item["citations"] == 0]
    if uncited:
        warnings.append({"level": "warning", "title": "部分章节缺少来源", "detail": f"{len(uncited)} 个章节没有引用来源，请人工确认。"})
    return warnings


def build_final_document(
    tender_id: int,
    *,
    include_content: bool = True,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    entries = _ordered_draft_entries(conn, tender_id)
    sections = _section_rows(entries)
    content = compose_final_markdown(tender_id, conn=conn)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    coverage = build_coverage_report(tender_id, conn=conn)
    quality_gate = build_quality_gate(tender_id, conn=conn)
    final_checklist = build_final_checklist(tender_id, conn=conn)
    warnings = _warnings(sections, coverage, quality_gate, final_checklist)
    record = _normalize_record(_ensure_record(tender_id, conn))
    can_approve = not any(item["level"] == "blocker" for item in warnings)
    if record.get("snapshot_hash") and record.get("snapshot_hash") != digest and record.get("status") == "approved":
        warnings.insert(0, {"level": "warning", "title": "成稿已变化", "detail": "当前草稿内容与上次确认时不一致，请重新确认。"})
        can_approve = False
    summary = {
        "total_sections": len(sections),
        "generated_sections": sum(1 for item in sections if item["status"] == "generated"),
        "missing_sections": sum(1 for item in sections if item["status"] == "missing"),
        "char_count": len(content),
        "hash": digest,
        "warnings": len(warnings),
        "blockers": sum(1 for item in warnings if item["level"] == "blocker"),
        "approval_status": record.get("status") or "draft",
        "can_approve": can_approve,
    }
    report = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry"), "region": tender.get("region")},
        "summary": summary,
        "approval": record,
        "sections": sections,
        "warnings": warnings,
        "markdown": render_final_document_markdown_from_parts(tender, summary, record, sections, warnings),
    }
    if include_content:
        report["content"] = content
    if own_conn:
        conn.close()
    return report


def update_final_document(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    _ensure_record(tender_id, conn)
    content = compose_final_markdown(tender_id, conn=conn)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    payload = {key: value for key, value in data.items() if key in FINAL_DOCUMENT_FIELDS}
    if "checklist_json" in payload and not isinstance(payload["checklist_json"], str):
        payload["checklist_json"] = json.dumps(payload["checklist_json"], ensure_ascii=False)
    assignments = []
    values: list[Any] = []
    for key, value in payload.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    assignments.extend(["snapshot_hash = ?", "snapshot_char_count = ?", "updated_at = CURRENT_TIMESTAMP"])
    values.extend([digest, len(content)])
    if payload.get("status") == "approved":
        assignments.append("approved_at = COALESCE(approved_at, CURRENT_TIMESTAMP)")
    with conn:
        conn.execute(
            f"UPDATE final_documents SET {', '.join(assignments)} WHERE tender_id = ?",
            [*values, tender_id],
        )
    report = build_final_document(tender_id, include_content=True, conn=conn)
    if own_conn:
        conn.close()
    return report


def render_final_document_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    report = build_final_document(tender_id, include_content=False, conn=conn)
    return str(report["markdown"])


def render_final_document_markdown_from_parts(
    tender: dict[str, Any],
    summary: dict[str, Any],
    approval: dict[str, Any],
    sections: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> str:
    lines = [
        "# 成稿确认报告",
        "",
        f"- 项目名称：{tender.get('name') or ''}",
        f"- 章节进度：{summary['generated_sections']}/{summary['total_sections']}",
        f"- 全稿字数：{summary['char_count']}",
        f"- 确认状态：{summary['approval_status']}",
        f"- 确认人：{approval.get('approved_by') or '未填写'}",
        f"- 确认时间：{approval.get('approved_at') or '未确认'}",
        f"- 内容指纹：{summary['hash']}",
        "",
        "## 风险提示",
    ]
    if warnings:
        for item in warnings:
            lines.append(f"- [{item['level']}] {item['title']}：{item['detail']}")
    else:
        lines.append("- 暂无阻断项，仍需人工核对项目参数、招标专用条款和格式要求。")
    lines.extend(["", "## 章节清单"])
    for item in sections:
        status = "未生成" if item["status"] == "missing" else "已生成"
        lines.append(
            f"- {item['order_no']}. {item['section_title']}：{status}，{item['char_count']} 字，引用 {item['citations']} 处"
        )
    if approval.get("notes"):
        lines.extend(["", "## 定稿备注", str(approval["notes"])])
    return "\n".join(lines).strip() + "\n"
