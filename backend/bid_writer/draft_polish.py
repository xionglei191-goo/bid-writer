from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .draft_versions import record_draft_version
from .project_profiles import get_project_profile
from .review import review_draft


FORBIDDEN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("确保中标", "确保技术标响应完整、编制质量满足要求"),
    ("保证中标", "保证技术文件质量和响应完整性"),
    ("必中", "提高技术标响应质量"),
    ("包中", "配合完成技术标编制和修改"),
)


def _draft_rows(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT id, tender_id, section_title, content, LENGTH(content) AS char_count
            FROM drafts
            WHERE tender_id = ?
            ORDER BY id
            """,
            (tender_id,),
        ).fetchall()
    )


def _old_project_candidates(conn: sqlite3.Connection, tender_id: int) -> set[str]:
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT citations_json
            FROM drafts
            WHERE tender_id = ?
            """,
            (tender_id,),
        ).fetchall()
    )
    candidates: set[str] = set()
    for row in rows:
        try:
            citations = json.loads(row.get("citations_json") or "[]")
        except json.JSONDecodeError:
            citations = []
        for citation in citations:
            source = str(citation.get("source_path") or "")
            match = re.match(r"^\d{3}、[^：:]+[：:][^-]+-(.+?)(?:技术标|施工组织设计|$)", source)
            if match:
                name = match.group(1).strip()
                if len(name) > 4:
                    candidates.add(name)
    return candidates


def _count_occurrences(content: str, term: str) -> int:
    return content.count(term) if term else 0


def list_replacement_records(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM draft_replacement_records
            WHERE tender_id = ?
            ORDER BY id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def scan_project_polish(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    target_project = profile.get("project_name") or tender.get("name") or "本项目"
    drafts = _draft_rows(conn, tender_id)

    suggestions: list[dict[str, Any]] = []
    for term, replacement in FORBIDDEN_REPLACEMENTS:
        matches = [
            {
                "draft_id": draft["id"],
                "section_title": draft["section_title"],
                "count": _count_occurrences(str(draft.get("content") or ""), term),
            }
            for draft in drafts
        ]
        matches = [item for item in matches if item["count"]]
        if matches:
            suggestions.append(
                {
                    "type": "forbidden_promise",
                    "search_text": term,
                    "replace_text": replacement,
                    "total_count": sum(item["count"] for item in matches),
                    "matches": matches,
                }
            )

    for candidate in sorted(_old_project_candidates(conn, tender_id)):
        matches = [
            {
                "draft_id": draft["id"],
                "section_title": draft["section_title"],
                "count": _count_occurrences(str(draft.get("content") or ""), candidate),
            }
            for draft in drafts
        ]
        matches = [item for item in matches if item["count"]]
        if matches:
            suggestions.append(
                {
                    "type": "old_project_name",
                    "search_text": candidate,
                    "replace_text": target_project or "本项目",
                    "total_count": sum(item["count"] for item in matches),
                    "matches": matches,
                }
            )

    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "target_project": target_project,
        "draft_count": len(drafts),
        "suggestions": suggestions,
        "records": list_replacement_records(tender_id, conn=conn),
    }
    if own_conn:
        conn.close()
    return result


def preview_replacement(
    tender_id: int,
    search_text: str,
    replace_text: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    search_text = str(search_text or "").strip()
    replace_text = str(replace_text or "")
    if not search_text:
        raise ValueError("查找词不能为空。")
    drafts = _draft_rows(conn, tender_id)
    matches = []
    for draft in drafts:
        count = _count_occurrences(str(draft.get("content") or ""), search_text)
        if count:
            matches.append(
                {
                    "draft_id": draft["id"],
                    "section_title": draft["section_title"],
                    "count": count,
                    "char_count": draft.get("char_count") or 0,
                }
            )
    result = {
        "tender_id": tender_id,
        "search_text": search_text,
        "replace_text": replace_text,
        "changed_drafts": len(matches),
        "changed_count": sum(item["count"] for item in matches),
        "matches": matches,
    }
    if own_conn:
        conn.close()
    return result


def apply_replacement(
    tender_id: int,
    search_text: str,
    replace_text: str,
    notes: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    preview = preview_replacement(tender_id, search_text, replace_text, conn=conn)
    if not preview["changed_count"]:
        return {**preview, "record": None}

    search_text = preview["search_text"]
    replace_text = preview["replace_text"]
    changed_draft_ids: list[int] = []
    with conn:
        for draft in _draft_rows(conn, tender_id):
            content = str(draft.get("content") or "")
            if search_text not in content:
                continue
            next_content = content.replace(search_text, replace_text)
            conn.execute(
                "UPDATE drafts SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (next_content, draft["id"]),
            )
            record_draft_version(int(draft["id"]), next_content, origin=f"replacement: {search_text}", conn=conn)
            changed_draft_ids.append(int(draft["id"]))
        cur = conn.execute(
            """
            INSERT INTO draft_replacement_records (
                tender_id, search_text, replace_text, changed_drafts, changed_count, notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                search_text,
                replace_text,
                preview["changed_drafts"],
                preview["changed_count"],
                str(notes or "").strip(),
            ),
        )
    for draft_id in changed_draft_ids:
        review_draft(draft_id, conn=conn)
    record = row_to_dict(conn.execute("SELECT * FROM draft_replacement_records WHERE id = ?", (cur.lastrowid,)).fetchone())
    result = {**preview, "record": record}
    if own_conn:
        conn.close()
    return result


def render_replacement_records_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    records = list_replacement_records(tender_id, conn=conn)
    lines = ["# 项目化校正记录", ""]
    if not records:
        lines.append("暂无全稿替换记录。")
    for item in records:
        lines.extend(
            [
                f"## {item.get('created_at') or ''}",
                "",
                f"- 查找词：{item.get('search_text') or ''}",
                f"- 替换为：{item.get('replace_text') or ''}",
                f"- 影响草稿：{item.get('changed_drafts') or 0}",
                f"- 替换次数：{item.get('changed_count') or 0}",
                f"- 备注：{item.get('notes') or ''}",
                "",
            ]
        )
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
