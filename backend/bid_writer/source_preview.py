from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .case_assets import get_case_asset
from .db import connect, row_to_dict, rows_to_dicts
from .settings import KB_ROOT, PROJECT_ROOT
from .text_utils import summarize


MAX_CONTEXT_CHARS = 12000
MAX_MARKDOWN_CHARS = 16000


def _resolve_markdown_path(value: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    candidates = [path] if path.is_absolute() else []
    if not path.is_absolute():
        if path.parts and path.parts[0] == KB_ROOT.name:
            candidates.append(PROJECT_ROOT / path)
        candidates.append(KB_ROOT / path)
        candidates.append(PROJECT_ROOT / path)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _read_text(path: Path, limit: int = MAX_MARKDOWN_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = path.read_text(errors="replace")
    return text[:limit]


def _heading_excerpt(text: str, heading: str) -> str:
    heading = str(heading or "").strip()
    if not heading:
        return text[:MAX_MARKDOWN_CHARS]
    index = text.find(heading)
    if index < 0:
        return text[:MAX_MARKDOWN_CHARS]
    start = max(0, index - 1000)
    end = min(len(text), index + MAX_MARKDOWN_CHARS)
    return text[start:end].strip()


def _case_asset_from_source(conn: sqlite3.Connection, source_path: str) -> dict[str, Any] | None:
    match = re.match(r"^案例资产/([^/]+)/(.+)$", str(source_path or ""))
    if not match:
        return None
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM case_assets
            WHERE project_name = ? AND section_title = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (match.group(1), match.group(2)),
        ).fetchone()
    )


def _kb_chunk_by_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any] | None:
    chunk_id = payload.get("chunk_id") or payload.get("id")
    if chunk_id not in ("", None):
        row = row_to_dict(conn.execute("SELECT * FROM chunks WHERE id = ?", (int(chunk_id),)).fetchone())
        if row:
            return row
    source_path = str(payload.get("source_path") or "").strip()
    heading = str(payload.get("heading_text") or "").strip()
    markdown_path = str(payload.get("markdown_path") or "").strip()
    clauses = []
    params: list[Any] = []
    if source_path:
        clauses.append("source_path = ?")
        params.append(source_path)
    if heading:
        clauses.append("COALESCE(heading_text, '') = ?")
        params.append(heading)
    if markdown_path:
        clauses.append("COALESCE(markdown_path, '') = ?")
        params.append(markdown_path)
    if not clauses:
        return None
    return row_to_dict(
        conn.execute(
            f"""
            SELECT *
            FROM chunks
            WHERE {' AND '.join(clauses)}
            ORDER BY chunk_index
            LIMIT 1
            """,
            params,
        ).fetchone()
    )


def _section_context(conn: sqlite3.Connection, chunk: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    section_id = chunk.get("section_id")
    if section_id not in ("", None):
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT id, chunk_index, content
                FROM chunks
                WHERE section_id = ?
                ORDER BY chunk_index
                LIMIT 20
                """,
                (section_id,),
            ).fetchall()
        )
    else:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT id, chunk_index, content
                FROM chunks
                WHERE source_path = ? AND COALESCE(heading_text, '') = COALESCE(?, '')
                ORDER BY chunk_index
                LIMIT 20
                """,
                (chunk.get("source_path") or "", chunk.get("heading_text") or ""),
            ).fetchall()
        )
    context_lines: list[str] = []
    for row in rows:
        part = str(row.get("content") or "").strip()
        if part:
            context_lines.append(part)
        if sum(len(line) for line in context_lines) >= MAX_CONTEXT_CHARS:
            break
    return "\n\n".join(context_lines)[:MAX_CONTEXT_CHARS], rows


def _document_meta(conn: sqlite3.Connection, document_id: Any) -> dict[str, Any]:
    if document_id in ("", None):
        return {}
    return row_to_dict(conn.execute("SELECT * FROM documents WHERE id = ?", (int(document_id),)).fetchone()) or {}


def _section_meta(conn: sqlite3.Connection, section_id: Any) -> dict[str, Any]:
    if section_id in ("", None):
        return {}
    return row_to_dict(conn.execute("SELECT * FROM sections WHERE id = ?", (int(section_id),)).fetchone()) or {}


def preview_source(payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    source_type = str(payload.get("source_type") or "kb_chunk")

    if source_type == "case_asset":
        asset_id = payload.get("chunk_id") or payload.get("id")
        asset = get_case_asset(int(asset_id), conn=conn) if asset_id not in ("", None) else _case_asset_from_source(conn, str(payload.get("source_path") or ""))
        if not asset:
            raise ValueError("案例资产来源未找到。")
        content = str(asset.get("content") or "")
        result = {
            "source_type": "case_asset",
            "id": asset.get("id"),
            "title": asset.get("section_title") or "",
            "source_path": f"案例资产/{asset.get('project_name') or '未命名项目'}/{asset.get('section_title') or ''}",
            "markdown_path": "",
            "top_category": asset.get("industry") or "",
            "top_project": asset.get("project_name") or "",
            "heading_text": asset.get("section_title") or "",
            "content": content[:MAX_CONTEXT_CHARS],
            "summary": asset.get("summary") or summarize(content, 320),
            "metadata": {
                "project_name": asset.get("project_name") or "",
                "industry": asset.get("industry") or "",
                "tags": asset.get("tags") or "",
                "reusable_score": asset.get("reusable_score") or 3,
                "source_status": asset.get("source_status") or "",
                "updated_at": asset.get("updated_at") or "",
            },
            "file_exists": False,
            "markdown_excerpt": "",
        }
        if own_conn:
            conn.close()
        return result

    chunk = _kb_chunk_by_payload(conn, payload)
    if not chunk:
        raise ValueError("知识库来源未找到。")
    document = _document_meta(conn, chunk.get("document_id"))
    section = _section_meta(conn, chunk.get("section_id"))
    context, neighbors = _section_context(conn, chunk)
    markdown_path_value = str(chunk.get("markdown_path") or document.get("markdown_path") or payload.get("markdown_path") or "")
    markdown_path = _resolve_markdown_path(markdown_path_value)
    markdown_excerpt = _heading_excerpt(_read_text(markdown_path), str(chunk.get("heading_text") or "")) if markdown_path else ""
    result = {
        "source_type": "kb_chunk",
        "id": chunk.get("id"),
        "document_id": chunk.get("document_id"),
        "section_id": chunk.get("section_id"),
        "title": chunk.get("heading_text") or section.get("heading_text") or "未命名章节",
        "source_path": chunk.get("source_path") or "",
        "markdown_path": markdown_path_value,
        "resolved_markdown_path": str(markdown_path) if markdown_path else "",
        "top_category": chunk.get("top_category") or document.get("top_category") or "",
        "top_company": chunk.get("top_company") or document.get("top_company") or "",
        "top_project": chunk.get("top_project") or document.get("top_project") or "",
        "heading_text": chunk.get("heading_text") or "",
        "chunk_index": chunk.get("chunk_index"),
        "content": context or str(chunk.get("content") or ""),
        "chunk_content": str(chunk.get("content") or ""),
        "summary": summarize(context or str(chunk.get("content") or ""), 360),
        "file_exists": bool(markdown_path),
        "markdown_excerpt": markdown_excerpt,
        "neighbors": [{"id": item.get("id"), "chunk_index": item.get("chunk_index")} for item in neighbors],
        "metadata": {
            "document_format": document.get("source_format") or "",
            "processing_action": document.get("processing_action") or "",
            "duplicate_policy": document.get("duplicate_policy") or "",
            "page_count": document.get("page_count") or 0,
            "section_count": document.get("section_count") or 0,
            "char_count": document.get("char_count") or 0,
            "page_number": section.get("page_number") or "",
            "heading_level": section.get("heading_level") or "",
        },
    }
    if own_conn:
        conn.close()
    return result
