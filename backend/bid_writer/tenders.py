from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect, init_db, row_to_dict, rows_to_dicts
from .document_processing import record_document_processing
from .draft_versions import record_draft_version
from .parsing import dumps, extract_file, parse_tender_text
from .planner import list_section_plans
from .production_tasks import ensure_production_task
from .project_profiles import ensure_project_profile, sync_profile_from_tender
from .requirement_responses import classify_requirement, classify_tender_requirements, rebuild_requirement_responses
from .chapter_contracts import structured_generation_result, validate_chapter_contract


def create_tender(
    name: str,
    text: str = "",
    file_path: str = "",
    industry: str = "",
    region: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    init_db(conn)
    processing_info: dict[str, Any] | None = None
    if file_path and not text:
        try:
            processing_info = dict(extract_file(Path(file_path)))
            text = str(processing_info.get("text") or "")
        except Exception as exc:
            record_document_processing(
                {
                    "source_path": file_path,
                    "file_type": Path(file_path).suffix.lower().lstrip("."),
                    "action": "extract_text",
                    "status": "failed",
                    "error_message": str(exc),
                },
                conn=conn,
            )
            if own_conn:
                conn.close()
            raise
    if not name:
        name = Path(file_path).stem if file_path else f"未命名项目-{datetime.now():%Y%m%d%H%M%S}"
    with conn:
        cur = conn.execute(
            """
            INSERT INTO tenders (name, industry, region, file_path, raw_text, parsed_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, industry, region, file_path, text, "{}"),
        )
        tender_id = int(cur.lastrowid)
    if file_path:
        record_document_processing(
            {
                **(processing_info or {}),
                "tender_id": tender_id,
                "source_path": file_path,
                "file_type": Path(file_path).suffix.lower().lstrip("."),
                "status": "success",
                "text_chars": len(text),
            },
            conn=conn,
        )
    ensure_project_profile(tender_id, conn=conn)
    ensure_production_task(tender_id, conn=conn)
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return tender


def parse_tender(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    parsed = parse_tender_text(tender.get("raw_text", ""), fallback_name=tender["name"])
    requirements = parsed["requirements"]
    with conn:
        conn.execute("DELETE FROM requirement_responses WHERE tender_id = ?", (tender_id,))
        conn.execute("DELETE FROM requirements WHERE tender_id = ?", (tender_id,))
        conn.execute("UPDATE tenders SET parsed_json = ? WHERE id = ?", (dumps(parsed), tender_id))
        conn.executemany(
            """
            INSERT INTO requirements (tender_id, kind, content, source_hint, priority, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    tender_id,
                    item["kind"],
                    item["content"],
                    item.get("source_hint", ""),
                    item.get("priority", "normal"),
                    item.get("status", "pending"),
                )
                for item in requirements
            ],
        )
    classification = classify_tender_requirements(tender_id, conn=conn)
    profile = sync_profile_from_tender(tender_id, conn=conn)
    result = {
        "tender": row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()),
        "parsed": parsed,
        "requirements": get_requirements(tender_id, conn=conn),
        "profile": profile,
        "classification": classification,
    }
    if own_conn:
        conn.close()
    return result


def update_tender_source(
    tender_id: int,
    text: str = "",
    file_path: str = "",
    name: str = "",
    industry: str | None = None,
    region: str | None = None,
    mode: str = "replace",
    reset_plan: bool = True,
    parse: bool = True,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    next_text = text
    processing_info: dict[str, Any] | None = None
    if file_path and not next_text:
        try:
            processing_info = dict(extract_file(Path(file_path)))
            next_text = str(processing_info.get("text") or "")
        except Exception as exc:
            record_document_processing(
                {
                    "tender_id": tender_id,
                    "source_path": file_path,
                    "file_type": Path(file_path).suffix.lower().lstrip("."),
                    "action": "extract_text",
                    "status": "failed",
                    "error_message": str(exc),
                },
                conn=conn,
            )
            if own_conn:
                conn.close()
            raise
    if mode == "append":
        next_text = "\n\n".join(part for part in (str(tender.get("raw_text") or "").strip(), next_text.strip()) if part)
    if not next_text.strip() and not file_path:
        raise ValueError("Tender source text or file is required")
    next_name = name.strip() or str(tender.get("name") or "")
    if not next_name and file_path:
        next_name = Path(file_path).stem
    assignments = {
        "name": next_name,
        "raw_text": next_text,
        "file_path": file_path or str(tender.get("file_path") or ""),
    }
    if industry is not None:
        assignments["industry"] = industry
    if region is not None:
        assignments["region"] = region
    with conn:
        conn.execute(
            """
            UPDATE tenders
            SET name = ?, raw_text = ?, file_path = ?, industry = ?, region = ?
            WHERE id = ?
            """,
            (
                assignments["name"],
                assignments["raw_text"],
                assignments["file_path"],
                assignments.get("industry", tender.get("industry") or ""),
                assignments.get("region", tender.get("region") or ""),
                tender_id,
            ),
        )
        if reset_plan:
            conn.execute("DELETE FROM section_plans WHERE tender_id = ?", (tender_id,))
    processing_record = None
    if file_path:
        processing_record = record_document_processing(
            {
                **(processing_info or {}),
                "tender_id": tender_id,
                "source_path": file_path,
                "file_type": Path(file_path).suffix.lower().lstrip("."),
                "status": "success",
                "text_chars": len(next_text),
            },
            conn=conn,
        )
    if parse:
        result = parse_tender(tender_id, conn=conn)
    else:
        result = {
            "tender": row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()),
            "requirements": get_requirements(tender_id, conn=conn),
            "profile": sync_profile_from_tender(tender_id, conn=conn),
        }
    result["source_update"] = {
        "mode": mode,
        "reset_plan": reset_plan,
        "parsed": parse,
        "char_count": len(next_text),
        "processing_record": processing_record,
    }
    result["tender"] = get_tender(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def list_tenders(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT
                t.*,
                COALESCE(pt.customer_name, '') AS customer_name,
                COALESCE(pt.source_platform, '') AS source_platform,
                COALESCE(pt.deadline, '') AS deadline,
                COALESCE(pt.delivery_status, '待生产') AS delivery_status,
                (SELECT COUNT(*) FROM requirements r WHERE r.tender_id = t.id) AS requirement_count,
                (SELECT COUNT(*) FROM drafts d WHERE d.tender_id = t.id) AS draft_count
            FROM tenders t
            LEFT JOIN production_tasks pt ON pt.tender_id = t.id
            ORDER BY t.id DESC
            """
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def delete_tender(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        cur = conn.execute("DELETE FROM tenders WHERE id = ?", (tender_id,))
    if own_conn:
        conn.close()
    return {"tender_id": tender_id, "deleted": cur.rowcount > 0}


def get_tender(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not row:
        raise ValueError(f"Tender not found: {tender_id}")
    row["requirements"] = get_requirements(tender_id, conn=conn)
    row["drafts"] = list_drafts(tender_id, conn=conn)
    row["section_plans"] = list_section_plans(tender_id, conn=conn)
    row["profile"] = ensure_project_profile(tender_id, conn=conn)
    row["task"] = ensure_production_task(tender_id, conn=conn)
    if row.get("parsed_json"):
        row["parsed"] = json.loads(row["parsed_json"])
    if own_conn:
        conn.close()
    return row


def get_requirements(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    for row in rows:
        try:
            row["acceptance_keywords"] = json.loads(row.get("acceptance_keywords_json") or "[]")
        except json.JSONDecodeError:
            row["acceptance_keywords"] = []
    if own_conn:
        conn.close()
    return rows


def get_requirement(requirement_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone())
    if not row:
        raise ValueError(f"Requirement not found: {requirement_id}")
    if own_conn:
        conn.close()
    return row


def _clean_requirement_payload(data: dict[str, Any]) -> dict[str, Any]:
    base = {
        "kind": str(data.get("kind") or "技术要求").strip(),
        "content": str(data.get("content") or "").strip(),
        "source_hint": str(data.get("source_hint") or "").strip(),
        "priority": str(data.get("priority") or "normal").strip() or "normal",
        "status": str(data.get("status") or "pending").strip() or "pending",
    }
    classified = classify_requirement({**data, **base})
    for field in (
        "response_scope", "score_weight", "source_page", "section_path", "applicable",
        "classification_source", "review_status", "review_notes",
    ):
        if field in data and data.get(field) is not None:
            classified[field] = data.get(field)
    return {**base, **classified}


def create_requirement(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT id FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    payload = _clean_requirement_payload(data)
    if not payload["content"]:
        raise ValueError("条款内容不能为空。")
    with conn:
        cur = conn.execute(
            """
            INSERT INTO requirements (
                tender_id, kind, content, source_hint, priority, status,
                requirement_key, response_scope, score_weight, source_page, section_path,
                applicable, classification_source, review_status, review_notes, acceptance_keywords_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                payload["kind"],
                payload["content"],
                payload["source_hint"],
                payload["priority"],
                payload["status"],
                payload["requirement_key"],
                payload["response_scope"],
                payload["score_weight"],
                payload["source_page"],
                payload["section_path"],
                payload["applicable"],
                payload["classification_source"],
                payload["review_status"],
                payload["review_notes"],
                json.dumps(payload["acceptance_keywords"], ensure_ascii=False),
            ),
        )
    requirement = get_requirement(int(cur.lastrowid), conn=conn)
    if own_conn:
        conn.close()
    return requirement


def update_requirement(
    requirement_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = get_requirement(requirement_id, conn=conn)
    payload = _clean_requirement_payload({**current, **data})
    if not payload["content"]:
        raise ValueError("条款内容不能为空。")
    with conn:
        conn.execute(
            """
            UPDATE requirements
            SET kind = ?, content = ?, source_hint = ?, priority = ?, status = ?,
                requirement_key = ?, response_scope = ?, score_weight = ?, source_page = ?,
                section_path = ?, applicable = ?, classification_source = ?, review_status = ?,
                review_notes = ?, acceptance_keywords_json = ?
            WHERE id = ?
            """,
            (
                payload["kind"],
                payload["content"],
                payload["source_hint"],
                payload["priority"],
                payload["status"],
                payload["requirement_key"],
                payload["response_scope"],
                payload["score_weight"],
                payload["source_page"],
                payload["section_path"],
                payload["applicable"],
                payload["classification_source"],
                payload["review_status"],
                payload["review_notes"],
                json.dumps(payload["acceptance_keywords"], ensure_ascii=False),
                requirement_id,
            ),
        )
    rebuild_requirement_responses(int(current["tender_id"]), conn=conn)
    requirement = get_requirement(requirement_id, conn=conn)
    if own_conn:
        conn.close()
    return requirement


def _remove_requirement_from_plans(conn: sqlite3.Connection, tender_id: int, requirement_id: int) -> None:
    rows = rows_to_dicts(
        conn.execute(
            "SELECT id, requirement_ids_json FROM section_plans WHERE tender_id = ?",
            (tender_id,),
        ).fetchall()
    )
    for row in rows:
        ids = json.loads(row.get("requirement_ids_json") or "[]")
        next_ids = [item for item in ids if int(item) != requirement_id]
        if next_ids != ids:
            conn.execute(
                "UPDATE section_plans SET requirement_ids_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(next_ids, ensure_ascii=False), row["id"]),
            )


def delete_requirement(requirement_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = get_requirement(requirement_id, conn=conn)
    with conn:
        _remove_requirement_from_plans(conn, int(current["tender_id"]), requirement_id)
        cur = conn.execute("DELETE FROM requirements WHERE id = ?", (requirement_id,))
    if own_conn:
        conn.close()
    return {"id": requirement_id, "tender_id": current["tender_id"], "deleted": cur.rowcount > 0}


def list_drafts(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT id, tender_id, section_title, status, generation_mode, generation_model,
                   generation_error, created_at, updated_at,
                   LENGTH(content) AS char_count
            FROM drafts
            WHERE tender_id = ?
            ORDER BY id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def get_draft(draft_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone())
    if not draft:
        raise ValueError(f"Draft not found: {draft_id}")
    draft["citations"] = json.loads(draft.get("citations_json") or "[]")
    draft["requirements"] = json.loads(draft.get("requirements_json") or "[]")
    review_data = json.loads(draft.get("review_json") or "[]")
    if isinstance(review_data, dict):
        draft["review"] = review_data.get("findings") or []
        draft["chapter_contract"] = review_data.get("chapter_contract") or {}
        draft["contract_validation"] = review_data.get("contract_validation") or {}
        draft["structured_result"] = review_data.get("structured_result") or {}
    else:
        draft["review"] = review_data
        draft["chapter_contract"] = {}
        draft["contract_validation"] = {}
        draft["structured_result"] = {}
    draft["generation"] = {
        "mode": draft.get("generation_mode") or "unknown",
        "model": draft.get("generation_model") or "",
        "error": draft.get("generation_error") or "",
    }
    if own_conn:
        conn.close()
    return draft


def update_draft(draft_id: int, content: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = get_draft(draft_id, conn=conn)
    review_data = {
        "findings": [],
        "chapter_contract": current.get("chapter_contract") or {},
        "contract_validation": validate_chapter_contract(content, current.get("chapter_contract") or {}),
        "structured_result": structured_generation_result(content, current.get("chapter_contract") or {}),
    }
    with conn:
        conn.execute(
            "UPDATE drafts SET content = ?, review_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (content, json.dumps(review_data, ensure_ascii=False), draft_id),
        )
    record_draft_version(draft_id, content, origin="saved", conn=conn)
    draft = get_draft(draft_id, conn=conn)
    rebuild_requirement_responses(int(draft["tender_id"]), conn=conn)
    if own_conn:
        conn.close()
    return draft
