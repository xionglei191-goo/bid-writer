from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .db import connect, row_to_dict


STAGES = ("parse", "outline", "review")


def _normalise(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in row.keys()} for row in rows]


def _stage_payload(conn: sqlite3.Connection, tender_id: int, stage_key: str) -> dict[str, Any]:
    if stage_key == "parse":
        tender = row_to_dict(
            conn.execute(
                "SELECT name, industry, region, raw_text, parsed_json FROM tenders WHERE id = ?",
                (tender_id,),
            ).fetchone()
        )
        profile = row_to_dict(
            conn.execute(
                """
                SELECT project_name, industry, region, project_type, structure_type,
                       building_area, floor_info, duration_days, planned_start,
                       planned_finish, quality_target, safety_target, green_target,
                       contract_scope, site_conditions, key_constraints, special_requirements
                FROM project_profiles WHERE tender_id = ?
                """,
                (tender_id,),
            ).fetchone()
        )
        requirements = _normalise(
            conn.execute(
                "SELECT id, kind, content, source_hint, priority, status FROM requirements WHERE tender_id = ? ORDER BY id",
                (tender_id,),
            ).fetchall()
        )
        return {"tender": tender or {}, "profile": profile or {}, "requirements": requirements}
    if stage_key == "outline":
        strategy = row_to_dict(
            conn.execute(
                """
                SELECT positioning, win_themes, key_constraints, risk_controls,
                       response_priorities, writing_tone, section_focus_json,
                       reference_keywords, forbidden_terms, status, notes
                FROM bid_strategies WHERE tender_id = ?
                """,
                (tender_id,),
            ).fetchone()
        )
        plans = _normalise(
            conn.execute(
                """
                SELECT id, order_no, section_title, template_name, requirement_ids_json,
                       rationale
                FROM section_plans WHERE tender_id = ? ORDER BY order_no, id
                """,
                (tender_id,),
            ).fetchall()
        )
        return {"strategy": strategy or {}, "plans": plans}
    if stage_key == "review":
        drafts = _normalise(
            conn.execute(
                """
                SELECT id, section_title, content, citations_json, review_json, status
                FROM drafts WHERE tender_id = ? ORDER BY id
                """,
                (tender_id,),
            ).fetchall()
        )
        return {"drafts": drafts}
    raise ValueError(f"Unknown workflow confirmation stage: {stage_key}")


def stage_signature(conn: sqlite3.Connection, tender_id: int, stage_key: str) -> str:
    payload = json.dumps(
        _stage_payload(conn, tender_id, stage_key),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def list_workflow_confirmations(
    tender_id: int,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    if not conn.execute("SELECT 1 FROM tenders WHERE id = ?", (tender_id,)).fetchone():
        if own_conn:
            conn.close()
        raise ValueError(f"Tender not found: {tender_id}")
    rows = {
        row["stage_key"]: row_to_dict(row) or {}
        for row in conn.execute(
            "SELECT * FROM workflow_confirmations WHERE tender_id = ?",
            (tender_id,),
        ).fetchall()
    }
    items: dict[str, dict[str, Any]] = {}
    for stage_key in STAGES:
        row = rows.get(stage_key, {})
        current_signature = stage_signature(conn, tender_id, stage_key)
        stored_signature = str(row.get("content_signature") or "")
        confirmed = row.get("status") == "confirmed" and stored_signature == current_signature
        items[stage_key] = {
            "stage_key": stage_key,
            "status": "confirmed" if confirmed else ("stale" if row.get("status") == "confirmed" else "pending"),
            "confirmed": confirmed,
            "confirmed_by": row.get("confirmed_by") or "",
            "notes": row.get("notes") or "",
            "confirmed_at": row.get("confirmed_at") or "",
            "updated_at": row.get("updated_at") or "",
        }
    result = {"tender_id": tender_id, "items": items}
    if own_conn:
        conn.close()
    return result


def set_workflow_confirmation(
    tender_id: int,
    stage_key: str,
    payload: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    if stage_key not in STAGES:
        raise ValueError(f"Unknown workflow confirmation stage: {stage_key}")
    payload = payload or {}
    own_conn = conn is None
    conn = conn or connect()
    if not conn.execute("SELECT 1 FROM tenders WHERE id = ?", (tender_id,)).fetchone():
        if own_conn:
            conn.close()
        raise ValueError(f"Tender not found: {tender_id}")
    status = "confirmed" if payload.get("confirmed", True) else "pending"
    signature = stage_signature(conn, tender_id, stage_key)
    conn.execute(
        """
        INSERT INTO workflow_confirmations (
            tender_id, stage_key, status, confirmed_by, notes, content_signature,
            confirmed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(tender_id, stage_key) DO UPDATE SET
            status = excluded.status,
            confirmed_by = excluded.confirmed_by,
            notes = excluded.notes,
            content_signature = excluded.content_signature,
            confirmed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            tender_id,
            stage_key,
            status,
            str(payload.get("confirmed_by") or "人工复核"),
            str(payload.get("notes") or ""),
            signature,
        ),
    )
    conn.commit()
    result = list_workflow_confirmations(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return result
