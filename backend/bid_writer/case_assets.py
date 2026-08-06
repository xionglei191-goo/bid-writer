from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .text_utils import keywords, summarize


CASE_ASSET_FIELDS = (
    "project_name",
    "industry",
    "section_title",
    "tags",
    "content",
    "summary",
    "reusable_score",
    "source_status",
)


def _clean_payload(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field in CASE_ASSET_FIELDS:
        if field not in data:
            continue
        if field == "reusable_score":
            cleaned[field] = int(data[field]) if data[field] not in ("", None) else 3
        else:
            cleaned[field] = str(data[field] or "").strip()
    return cleaned


def _fts_query(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def _sync_fts(conn: sqlite3.Connection, asset: dict[str, Any]) -> None:
    conn.execute("DELETE FROM case_assets_fts WHERE rowid = ?", (asset["id"],))
    conn.execute(
        """
        INSERT INTO case_assets_fts (rowid, content, section_title, project_name, industry, tags)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            asset["id"],
            asset.get("content") or "",
            asset.get("section_title") or "",
            asset.get("project_name") or "",
            asset.get("industry") or "",
            asset.get("tags") or "",
        ),
    )


def get_case_asset(asset_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    asset = row_to_dict(conn.execute("SELECT * FROM case_assets WHERE id = ?", (asset_id,)).fetchone())
    if not asset:
        raise ValueError(f"Case asset not found: {asset_id}")
    if own_conn:
        conn.close()
    return asset


def list_case_assets(
    tender_id: int | None = None,
    limit: int = 100,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    limit = max(1, min(int(limit or 100), 300))
    if tender_id:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM case_assets
                WHERE tender_id = ?
                ORDER BY reusable_score DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (tender_id, limit),
            ).fetchall()
        )
    else:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM case_assets
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
    if own_conn:
        conn.close()
    return rows


def create_case_asset_from_draft(
    draft_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone())
    if not draft:
        raise ValueError(f"Draft not found: {draft_id}")
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (draft["tender_id"],)).fetchone()) or {}
    payload = data or {}
    cleaned = {
        "project_name": tender.get("name") or "",
        "industry": tender.get("industry") or "",
        "section_title": draft.get("section_title") or "",
        "tags": tender.get("industry") or "",
        "content": draft.get("content") or "",
        "summary": summarize(draft.get("content") or "", 260),
        "reusable_score": 3,
        "source_status": "草稿沉淀",
    }
    cleaned.update(_clean_payload(payload))
    if not cleaned["content"]:
        raise ValueError("案例资产内容不能为空。")
    existing = row_to_dict(
        conn.execute(
            "SELECT * FROM case_assets WHERE draft_id = ? ORDER BY id LIMIT 1",
            (draft_id,),
        ).fetchone()
    )
    if existing:
        asset = update_case_asset(int(existing["id"]), cleaned, conn=conn)
        asset["operation"] = "updated"
        if own_conn:
            conn.close()
        return asset
    with conn:
        cur = conn.execute(
            """
            INSERT INTO case_assets (
                tender_id, draft_id, project_name, industry, section_title,
                tags, content, summary, reusable_score, source_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft["tender_id"],
                draft_id,
                cleaned["project_name"],
                cleaned["industry"],
                cleaned["section_title"],
                cleaned["tags"],
                cleaned["content"],
                cleaned["summary"] or summarize(cleaned["content"], 260),
                cleaned["reusable_score"],
                cleaned["source_status"],
            ),
        )
        asset = get_case_asset(int(cur.lastrowid), conn=conn)
        _sync_fts(conn, asset)
    asset["operation"] = "created"
    if own_conn:
        conn.close()
    return asset


def create_case_assets_from_tender(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    drafts = rows_to_dicts(conn.execute("SELECT id FROM drafts WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    items = [create_case_asset_from_draft(int(draft["id"]), data or {}, conn=conn) for draft in drafts]
    result = {
        "tender_id": tender_id,
        "created_count": sum(1 for item in items if item.get("operation") == "created"),
        "updated_count": sum(1 for item in items if item.get("operation") == "updated"),
        "processed_count": len(items),
        "items": items,
    }
    if own_conn:
        conn.close()
    return result


def update_case_asset(
    asset_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = get_case_asset(asset_id, conn=conn)
    cleaned = _clean_payload(data)
    if cleaned:
        if "summary" not in cleaned and "content" in cleaned:
            cleaned["summary"] = summarize(cleaned["content"], 260)
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE case_assets
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [*cleaned.values(), current["id"]],
            )
            asset = get_case_asset(asset_id, conn=conn)
            _sync_fts(conn, asset)
    else:
        asset = current
    if own_conn:
        conn.close()
    return asset


def delete_case_asset(asset_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        conn.execute("DELETE FROM case_assets_fts WHERE rowid = ?", (asset_id,))
        cur = conn.execute("DELETE FROM case_assets WHERE id = ?", (asset_id,))
    if own_conn:
        conn.close()
    return {"deleted": cur.rowcount > 0, "id": asset_id}


def search_case_assets(
    query: str,
    category: str = "",
    heading: str = "",
    limit: int = 10,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    limit = max(1, min(limit, 50))
    clauses = []
    params: list[Any] = []
    if category:
        clauses.append("COALESCE(a.industry, '') LIKE ?")
        params.append(f"%{category}%")
    if heading:
        clauses.append("COALESCE(a.section_title, '') LIKE ?")
        params.append(f"%{heading}%")
    where = " AND ".join(clauses)
    if where:
        where = " AND " + where

    results: list[dict[str, Any]] = []
    cleaned_query = query.strip()
    if cleaned_query:
        for term in keywords(cleaned_query)[:6] or [cleaned_query]:
            try:
                rows = rows_to_dicts(
                    conn.execute(
                        f"""
                        SELECT a.*, bm25(case_assets_fts) AS rank
                        FROM case_assets_fts
                        JOIN case_assets a ON a.id = case_assets_fts.rowid
                        WHERE case_assets_fts MATCH ? {where}
                        ORDER BY rank
                        LIMIT ?
                        """,
                        [_fts_query(term), *params, limit],
                    ).fetchall()
                )
            except sqlite3.OperationalError:
                rows = []
            results.extend(rows)
            if len(results) >= limit:
                break
    if len(results) < limit:
        terms = keywords(" ".join([query, heading, category]))[:8]
        like_clauses = []
        like_params: list[Any] = []
        for term in terms:
            pattern = f"%{term}%"
            like_clauses.append("(content LIKE ? OR section_title LIKE ? OR project_name LIKE ? OR tags LIKE ?)")
            like_params.extend([pattern, pattern, pattern, pattern])
        if not like_clauses:
            like_clauses.append("1=1")
        rows = rows_to_dicts(
            conn.execute(
                f"""
                SELECT a.*
                FROM case_assets a
                WHERE ({' OR '.join(like_clauses)}) {where}
                ORDER BY reusable_score DESC, id DESC
                LIMIT ?
                """,
                [*like_params, *params, limit],
            ).fetchall()
        )
        results.extend(rows)
    seen: set[int] = set()
    mapped: list[dict[str, Any]] = []
    for item in results:
        item_id = int(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        mapped.append(
            {
                "id": item_id,
                "source_type": "case_asset",
                "document_id": None,
                "section_id": None,
                "source_path": f"案例资产/{item.get('project_name') or '未命名项目'}/{item.get('section_title') or ''}",
                "markdown_path": "",
                "top_category": item.get("industry") or "",
                "top_company": "",
                "top_project": item.get("project_name") or "",
                "heading_text": item.get("section_title") or "",
                "chunk_index": 0,
                "content": item.get("content") or "",
                "summary": item.get("summary") or summarize(item.get("content") or "", 260),
                "reusable_score": item.get("reusable_score") or 3,
                "tags": item.get("tags") or "",
            }
        )
    if own_conn:
        conn.close()
    return mapped[:limit]


def render_case_assets_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    assets = list_case_assets(tender_id=tender_id, limit=300, conn=conn)
    lines = ["# 案例资产", ""]
    if not assets:
        lines.append("暂无沉淀案例资产。")
    for item in assets:
        lines.extend(
            [
                f"## {item.get('section_title') or '未命名章节'}",
                "",
                f"- 项目：{item.get('project_name') or ''}",
                f"- 行业：{item.get('industry') or ''}",
                f"- 标签：{item.get('tags') or ''}",
                f"- 复用评分：{item.get('reusable_score') or 3}/5",
                "",
                item.get("summary") or summarize(item.get("content") or "", 300),
                "",
            ]
        )
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
