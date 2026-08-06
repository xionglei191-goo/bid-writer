from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import connect, row_to_dict


PROFILE_FIELDS = (
    "project_name",
    "industry",
    "region",
    "project_type",
    "structure_type",
    "building_area",
    "floor_info",
    "duration_days",
    "planned_start",
    "planned_finish",
    "quality_target",
    "safety_target",
    "green_target",
    "contract_scope",
    "site_conditions",
    "key_constraints",
    "special_requirements",
)


def _project_name_from_tender(tender: dict[str, Any]) -> str:
    try:
        parsed = json.loads(tender.get("parsed_json") or "{}")
        name = parsed.get("overview", {}).get("project_name")
        if name:
            return str(name)
    except json.JSONDecodeError:
        pass
    return str(tender.get("name") or "")


def _parsed_overview(tender: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(tender.get("parsed_json") or "{}")
    except json.JSONDecodeError:
        return {}
    overview = parsed.get("overview") if isinstance(parsed, dict) else {}
    return overview if isinstance(overview, dict) else {}


def _default_profile(tender: dict[str, Any]) -> dict[str, Any]:
    industry = str(tender.get("industry") or "")
    overview = _parsed_overview(tender)
    return {
        "project_name": _project_name_from_tender(tender),
        "industry": industry or str(overview.get("project_type") or ""),
        "region": str(tender.get("region") or ""),
        "project_type": str(overview.get("project_type") or industry),
        "structure_type": str(overview.get("structure_type") or ""),
        "building_area": str(overview.get("building_area") or ""),
        "floor_info": str(overview.get("floor_info") or ""),
        "duration_days": overview.get("duration_days") or None,
        "planned_start": "",
        "planned_finish": "",
        "quality_target": str(overview.get("quality_target") or ""),
        "safety_target": str(overview.get("safety_target") or ""),
        "green_target": str(overview.get("green_target") or ""),
        "contract_scope": str(overview.get("contract_scope") or ""),
        "site_conditions": str(overview.get("site_conditions") or ""),
        "key_constraints": str(overview.get("key_constraints") or ""),
        "special_requirements": str(overview.get("special_requirements") or ""),
    }


def ensure_project_profile(
    tender_id: int,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM project_profiles WHERE tender_id = ?", (tender_id,)).fetchone())
    if row:
        if own_conn:
            conn.close()
        return row

    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = _default_profile(tender)
    columns = ", ".join(["tender_id", *PROFILE_FIELDS])
    placeholders = ", ".join("?" for _ in ["tender_id", *PROFILE_FIELDS])
    values = [tender_id, *[profile[field] for field in PROFILE_FIELDS]]
    with conn:
        cur = conn.execute(
            f"INSERT INTO project_profiles ({columns}) VALUES ({placeholders})",
            values,
        )
    row = row_to_dict(conn.execute("SELECT * FROM project_profiles WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def get_project_profile(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    return ensure_project_profile(tender_id, conn=conn)


def sync_profile_from_tender(
    tender_id: int,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = ensure_project_profile(tender_id, conn=conn)
    defaults = _default_profile(tender)
    updates: dict[str, Any] = {}
    for field in PROFILE_FIELDS:
        current = profile.get(field)
        default = defaults.get(field)
        current_blank = current in ("", None)
        if field == "project_name" and default and (current_blank or str(current) == str(tender.get("name") or "")):
            updates[field] = default
        elif current_blank and default not in ("", None):
            updates[field] = defaults[field]
    if updates:
        profile = update_project_profile(tender_id, updates, conn=conn)
    if own_conn:
        conn.close()
    return profile


def update_project_profile(
    tender_id: int,
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    ensure_project_profile(tender_id, conn=conn)
    cleaned: dict[str, Any] = {}
    for field in PROFILE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "duration_days":
            if value in ("", None):
                cleaned[field] = None
            else:
                cleaned[field] = int(value)
        else:
            cleaned[field] = str(value or "").strip()
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        values = [*cleaned.values(), tender_id]
        with conn:
            conn.execute(
                f"""
                UPDATE project_profiles
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE tender_id = ?
                """,
                values,
            )
    profile = row_to_dict(conn.execute("SELECT * FROM project_profiles WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return profile


def profile_summary(profile: dict[str, Any]) -> str:
    labels = {
        "project_name": "项目名称",
        "industry": "行业类型",
        "region": "建设地区",
        "project_type": "项目类型",
        "structure_type": "结构形式",
        "building_area": "建设规模",
        "floor_info": "层数信息",
        "duration_days": "工期天数",
        "planned_start": "计划开工",
        "planned_finish": "计划竣工",
        "quality_target": "质量目标",
        "safety_target": "安全目标",
        "green_target": "绿色施工目标",
        "contract_scope": "承包范围",
        "site_conditions": "现场条件",
        "key_constraints": "关键约束",
        "special_requirements": "特殊要求",
    }
    lines = []
    for field in PROFILE_FIELDS:
        value = profile.get(field)
        if value not in ("", None):
            lines.append(f"- {labels[field]}：{value}")
    return "\n".join(lines)
