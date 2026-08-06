from __future__ import annotations

import sqlite3
from typing import Any

from .case_assets import search_case_assets
from .db import connect, rows_to_dicts
from .text_utils import keywords, summarize


def _like_query(query: str) -> str:
    return f"%{query.strip()}%"


def _fts_query(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def search_chunks(
    query: str,
    category: str = "",
    project_type: str = "",
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
        clauses.append("COALESCE(c.top_category, '') LIKE ?")
        params.append(_like_query(category))
    if project_type:
        clauses.append("(COALESCE(c.top_project, '') LIKE ? OR COALESCE(c.source_path, '') LIKE ?)")
        params.extend([_like_query(project_type), _like_query(project_type)])
    if heading:
        clauses.append("COALESCE(c.heading_text, '') LIKE ?")
        params.append(_like_query(heading))
    where = " AND ".join(clauses)
    if where:
        where = " AND " + where

    results: list[dict[str, Any]] = []
    cleaned_query = query.strip()
    if cleaned_query:
        terms = keywords(cleaned_query)[:6]
        for term in terms or [cleaned_query]:
            try:
                rows = conn.execute(
                    f"""
                    SELECT c.*, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    WHERE chunks_fts MATCH ? {where}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    [_fts_query(term), *params, limit],
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            results.extend(rows_to_dicts(rows))
            if len(results) >= limit:
                break

    if len(results) < limit:
        like_terms = keywords(" ".join([query, heading, category, project_type]))[:8]
        like_clauses = []
        like_params: list[Any] = []
        for term in like_terms:
            like_clauses.append("(c.content LIKE ? OR c.heading_text LIKE ? OR c.source_path LIKE ?)")
            pattern = _like_query(term)
            like_params.extend([pattern, pattern, pattern])
        if not like_clauses:
            like_clauses.append("1=1")
        rows = conn.execute(
            f"""
            SELECT c.*
            FROM chunks c
            WHERE ({' OR '.join(like_clauses)}) {where}
            ORDER BY c.id DESC
            LIMIT ?
            """,
            [*like_params, *params, limit],
        ).fetchall()
        results.extend(rows_to_dicts(rows))

    asset_results = search_case_assets(
        query=query,
        category=category,
        heading=heading,
        limit=max(3, min(limit, 12)),
        conn=conn,
    )

    query_terms = keywords(" ".join([query, heading, category, project_type]))[:12]
    seen: set[tuple[str, int]] = set()
    deduped: list[dict[str, Any]] = []
    for item in [*asset_results, *results]:
        item_id = int(item["id"])
        source_type = str(item.get("source_type") or "kb_chunk")
        key = (source_type, item_id)
        if key in seen:
            continue
        seen.add(key)
        item["source_type"] = source_type
        item["summary"] = summarize(item.get("content", ""))
        item["score"] = score_chunk(item, query_terms=query_terms, category=category, heading=heading, project_type=project_type)
        deduped.append(item)
    deduped.sort(key=lambda item: item.get("score", 0), reverse=True)
    deduped = deduped[:limit]

    if own_conn:
        conn.close()
    return deduped


def score_chunk(
    item: dict[str, Any],
    query_terms: list[str],
    category: str = "",
    heading: str = "",
    project_type: str = "",
) -> int:
    heading_text = str(item.get("heading_text") or "")
    content = str(item.get("content") or "")
    source = str(item.get("source_path") or "")
    item_category = str(item.get("top_category") or "")
    item_project = str(item.get("top_project") or "")

    score = 0
    if category and category in item_category:
        score += 80
    if item.get("source_type") == "case_asset":
        score += 45 + int(item.get("reusable_score") or 0) * 5
    if project_type and (project_type in item_project or project_type in source):
        score += 50
    if heading and heading in heading_text:
        score += 60
    for term in query_terms:
        if term in heading_text:
            score += 12
        if term in content:
            score += 4
        if term in source:
            score += 2
    if 200 <= len(content) <= 1600:
        score += 8
    if "目录" in heading_text or "封面" in heading_text:
        score -= 20
    return score
