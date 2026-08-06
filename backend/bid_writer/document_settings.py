from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from .db import connect, row_to_dict
from .enterprise_profiles import get_enterprise_profile
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


DOCUMENT_SETTING_FIELDS = (
    "template_id",
    "document_title",
    "document_subtitle",
    "document_type",
    "bidder_name",
    "version_label",
    "prepared_by",
    "reviewed_by",
    "document_date",
    "confidentiality",
    "header_text",
    "footer_text",
    "body_font",
    "body_font_size",
    "heading_font",
    "include_cover",
    "include_toc",
    "include_response_matrix",
    "include_delivery_review",
    "section_page_break",
    "notes",
)

BOOLEAN_FIELDS = {
    "include_cover",
    "include_toc",
    "include_response_matrix",
    "include_delivery_review",
    "section_page_break",
}


def _truthy(value: Any) -> int:
    return 1 if value in {True, 1, "1", "true", "True", "yes", "是", "启用", "包含"} else 0


def _default_settings(tender_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    task = get_production_task(tender_id, conn=conn)
    enterprise = get_enterprise_profile(conn=conn)
    project_name = str(profile.get("project_name") or tender.get("name") or "").strip().rstrip("，,；;：:。.!！?？")
    bidder = str(enterprise.get("bidder_name") or task.get("customer_name") or "").strip()
    document_type = "技术标"
    return {
        "template_id": None,
        "document_title": project_name,
        "document_subtitle": "投标文件技术部分",
        "document_type": document_type,
        "bidder_name": bidder,
        "version_label": "初稿",
        "prepared_by": str(task.get("internal_owner") or "").strip(),
        "reviewed_by": "",
        "document_date": date.today().isoformat(),
        "confidentiality": "内部编制稿，正式递交前须人工复核。",
        "header_text": f"{project_name} / {document_type}".strip(" /"),
        "footer_text": "技术标智能编制系统生成，正式投标前请人工复核。",
        "body_font": "Microsoft YaHei",
        "body_font_size": 10.5,
        "heading_font": "Microsoft YaHei",
        "include_cover": 1,
        "include_toc": 1,
        "include_response_matrix": 0,
        "include_delivery_review": 0,
        "section_page_break": 1,
        "notes": "",
    }


def ensure_document_settings(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM document_settings WHERE tender_id = ?", (tender_id,)).fetchone())
    if row:
        for field in BOOLEAN_FIELDS:
            row[field] = bool(row.get(field))
        if own_conn:
            conn.close()
        return row
    defaults = _default_settings(tender_id, conn)
    columns = ", ".join(["tender_id", *DOCUMENT_SETTING_FIELDS])
    placeholders = ", ".join("?" for _ in ["tender_id", *DOCUMENT_SETTING_FIELDS])
    values = [tender_id]
    for field in DOCUMENT_SETTING_FIELDS:
        values.append(defaults[field])
    with conn:
        cur = conn.execute(f"INSERT INTO document_settings ({columns}) VALUES ({placeholders})", values)
    row = row_to_dict(conn.execute("SELECT * FROM document_settings WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    for field in BOOLEAN_FIELDS:
        row[field] = bool(row.get(field))
    if own_conn:
        conn.close()
    return row


def get_document_settings(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    return ensure_document_settings(tender_id, conn=conn)


def update_document_settings(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    ensure_document_settings(tender_id, conn=conn)
    cleaned: dict[str, Any] = {}
    for field in DOCUMENT_SETTING_FIELDS:
        if field not in data:
            continue
        if field == "template_id":
            cleaned[field] = int(data.get(field)) if data.get(field) not in {None, ""} else None
        elif field in BOOLEAN_FIELDS:
            cleaned[field] = _truthy(data.get(field))
        elif field == "body_font_size":
            try:
                cleaned[field] = float(data.get(field) or 10.5)
            except (TypeError, ValueError):
                cleaned[field] = 10.5
        else:
            cleaned[field] = str(data.get(field) or "").strip()
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE document_settings
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE tender_id = ?
                """,
                (*cleaned.values(), tender_id),
            )
    row = ensure_document_settings(tender_id, conn=conn)
    if own_conn:
        conn.close()
    return row


def render_document_settings_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    settings = get_document_settings(tender_id, conn=conn)
    lines = [
        "# 成稿格式设置",
        "",
        f"- 文件标题：{settings.get('document_title') or ''}",
        f"- 副标题：{settings.get('document_subtitle') or ''}",
        f"- 文件类型：{settings.get('document_type') or ''}",
        f"- 投标单位/客户：{settings.get('bidder_name') or ''}",
        f"- 版本：{settings.get('version_label') or ''}",
        f"- 编制人：{settings.get('prepared_by') or ''}",
        f"- 复核人：{settings.get('reviewed_by') or ''}",
        f"- 文件日期：{settings.get('document_date') or ''}",
        f"- 保密/提示：{settings.get('confidentiality') or ''}",
        f"- 页眉：{settings.get('header_text') or ''}",
        f"- 页脚：{settings.get('footer_text') or ''}",
        f"- 正文字体：{settings.get('body_font') or ''} / {settings.get('body_font_size') or ''}",
        f"- 标题字体：{settings.get('heading_font') or ''}",
        "",
        "## 导出选项",
        "",
        f"- 包含封面：{'是' if settings.get('include_cover') else '否'}",
        f"- 包含目录页：{'是' if settings.get('include_toc') else '否'}",
        f"- 包含响应矩阵：{'是' if settings.get('include_response_matrix') else '否'}",
        f"- 包含交付审查附录：{'是' if settings.get('include_delivery_review') else '否'}",
        f"- 章节分页：{'是' if settings.get('section_page_break') else '否'}",
    ]
    if settings.get("notes"):
        lines.extend(["", "## 备注", "", str(settings.get("notes") or "")])
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
