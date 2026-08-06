from __future__ import annotations
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .settings import DOCUMENT_TEMPLATE_DIR


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _template_row(row: dict[str, Any]) -> dict[str, Any]:
    row["style_map"] = _json_object(row.get("style_map_json"))
    row["cover_fields"] = _json_object(row.get("cover_fields_json"))
    row["is_default"] = bool(row.get("is_default"))
    return row


def ensure_default_document_template(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM document_templates WHERE is_default = 1 ORDER BY id LIMIT 1").fetchone())
    if not row:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO document_templates (name, version, status, is_default, style_map_json, cover_fields_json)
                VALUES ('系统默认技术标模板', '1.0', 'active', 1, '{}', '{}')
                """
            )
        row = row_to_dict(conn.execute("SELECT * FROM document_templates WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    result = _template_row(row)
    if own_conn:
        conn.close()
    return result


def list_document_templates(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    ensure_default_document_template(conn=conn)
    rows = [_template_row(row) for row in rows_to_dicts(conn.execute("SELECT * FROM document_templates ORDER BY is_default DESC, name").fetchall())]
    if own_conn:
        conn.close()
    return rows


def get_document_template(template_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM document_templates WHERE id = ?", (template_id,)).fetchone())
    if not row:
        raise ValueError(f"Document template not found: {template_id}")
    result = _template_row(row)
    if own_conn:
        conn.close()
    return result


def save_document_template(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("模板名称不能为空。")
    source = str(data.get("source_docx_path") or "").strip()
    saved_path = ""
    if source:
        source_path = Path(source).resolve()
        if not source_path.exists() or source_path.suffix.lower() != ".docx":
            raise ValueError("企业模板必须是存在的 DOCX 文件。")
        target = DOCUMENT_TEMPLATE_DIR / f"{name}_{str(data.get('version') or '1.0').replace('/', '_')}.docx"
        if source_path != target.resolve():
            shutil.copy2(source_path, target)
        saved_path = str(target)
    is_default = 1 if data.get("is_default") else 0
    with conn:
        if is_default:
            conn.execute("UPDATE document_templates SET is_default = 0")
        current = row_to_dict(conn.execute("SELECT id FROM document_templates WHERE name = ?", (name,)).fetchone())
        values = (
            saved_path,
            json.dumps(_json_object(data.get("style_map")), ensure_ascii=False),
            json.dumps(_json_object(data.get("cover_fields")), ensure_ascii=False),
            str(data.get("version") or "1.0"),
            str(data.get("status") or "active"),
            is_default,
        )
        if current:
            template_id = int(current["id"])
            conn.execute(
                """
                UPDATE document_templates
                SET source_docx_path = CASE WHEN ? = '' THEN source_docx_path ELSE ? END,
                    style_map_json = ?, cover_fields_json = ?, version = ?, status = ?,
                    is_default = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (saved_path, *values, template_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO document_templates (
                    name, source_docx_path, style_map_json, cover_fields_json,
                    version, status, is_default
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, *values),
            )
            template_id = int(cur.lastrowid)
    result = get_document_template(template_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def update_document_template(template_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    current = get_document_template(template_id, conn=conn)
    merged = {**current, **data, "name": data.get("name") or current["name"]}
    return save_document_template(merged, conn=conn)


def delete_document_template(template_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = get_document_template(template_id, conn=conn)
    if current.get("is_default"):
        raise ValueError("系统默认模板不能删除。")
    with conn:
        conn.execute("UPDATE document_settings SET template_id = NULL WHERE template_id = ?", (template_id,))
        cur = conn.execute("DELETE FROM document_templates WHERE id = ?", (template_id,))
    if own_conn:
        conn.close()
    return {"id": template_id, "deleted": cur.rowcount > 0}


def template_for_tender(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(
        conn.execute(
            """
            SELECT dt.*
            FROM document_settings ds
            JOIN document_templates dt ON dt.id = ds.template_id
            WHERE ds.tender_id = ? AND dt.status = 'active'
            """,
            (tender_id,),
        ).fetchone()
    )
    result = _template_row(row) if row else ensure_default_document_template(conn=conn)
    if own_conn:
        conn.close()
    return result
