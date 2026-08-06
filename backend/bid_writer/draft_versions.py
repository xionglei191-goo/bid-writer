from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .chapter_contracts import structured_generation_result, validate_chapter_contract
from .requirement_responses import rebuild_requirement_responses


def _next_version_no(conn: sqlite3.Connection, draft_id: int) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version_no), 0) + 1 FROM draft_versions WHERE draft_id = ?", (draft_id,)).fetchone()
    return int(row[0])


def record_draft_version(
    draft_id: int,
    content: str,
    origin: str = "saved",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    draft = row_to_dict(conn.execute("SELECT id, tender_id FROM drafts WHERE id = ?", (draft_id,)).fetchone())
    if not draft:
        raise ValueError(f"Draft not found: {draft_id}")
    with conn:
        cur = conn.execute(
            """
            INSERT INTO draft_versions (draft_id, tender_id, version_no, content, origin)
            VALUES (?, ?, ?, ?, ?)
            """,
            (draft_id, int(draft["tender_id"]), _next_version_no(conn, draft_id), content, origin),
        )
    version = row_to_dict(conn.execute("SELECT * FROM draft_versions WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return version


def list_draft_versions(
    draft_id: int,
    include_content: bool = False,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    fields = "*" if include_content else "id, draft_id, tender_id, version_no, origin, created_at, LENGTH(content) AS char_count"
    rows = rows_to_dicts(
        conn.execute(
            f"""
            SELECT {fields}
            FROM draft_versions
            WHERE draft_id = ?
            ORDER BY version_no DESC
            """,
            (draft_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def restore_draft_version(
    draft_id: int,
    version_id: int,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    version = row_to_dict(
        conn.execute(
            "SELECT * FROM draft_versions WHERE id = ? AND draft_id = ?",
            (version_id, draft_id),
        ).fetchone()
    )
    if not version:
        raise ValueError(f"Draft version not found: {version_id}")
    with conn:
        conn.execute(
            "UPDATE drafts SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (version["content"], draft_id),
        )
    record_draft_version(draft_id, str(version["content"]), origin=f"restored from v{version['version_no']}", conn=conn)
    draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()) or {}
    draft["citations"] = json.loads(draft.get("citations_json") or "[]")
    draft["requirements"] = json.loads(draft.get("requirements_json") or "[]")
    review_data = json.loads(draft.get("review_json") or "[]")
    if isinstance(review_data, dict):
        contract = review_data.get("chapter_contract") or {}
        review_data["findings"] = []
        review_data["contract_validation"] = validate_chapter_contract(str(draft.get("content") or ""), contract)
        review_data["structured_result"] = structured_generation_result(str(draft.get("content") or ""), contract)
        with conn:
            conn.execute("UPDATE drafts SET review_json = ? WHERE id = ?", (json.dumps(review_data, ensure_ascii=False), draft_id))
        draft["review"] = []
        draft["chapter_contract"] = contract
        draft["contract_validation"] = review_data["contract_validation"]
        draft["structured_result"] = review_data["structured_result"]
    else:
        draft["review"] = review_data
        draft["chapter_contract"] = {}
        draft["contract_validation"] = {}
        draft["structured_result"] = {}
    rebuild_requirement_responses(int(draft["tender_id"]), conn=conn)
    if own_conn:
        conn.close()
    return draft
