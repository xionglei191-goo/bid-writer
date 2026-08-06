from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect, row_to_dict


ENTERPRISE_PROFILE_FIELDS = (
    "profile_name",
    "bidder_name",
    "legal_representative",
    "contact",
    "qualification_summary",
    "capability_summary",
    "quality_system",
    "safety_system",
    "key_personnel",
    "equipment_resources",
    "similar_projects",
    "service_commitment",
    "notes",
    "is_default",
)

TEXT_FIELDS = tuple(field for field in ENTERPRISE_PROFILE_FIELDS if field != "is_default")


def _truthy(value: Any) -> int:
    return 1 if value in {True, 1, "1", "true", "True", "yes", "是", "默认"} else 0


def _default_profile() -> dict[str, Any]:
    return {
        "profile_name": "默认投标单位",
        "bidder_name": "",
        "legal_representative": "",
        "contact": "",
        "qualification_summary": "",
        "capability_summary": "",
        "quality_system": "",
        "safety_system": "",
        "key_personnel": "",
        "equipment_resources": "",
        "similar_projects": "",
        "service_commitment": "",
        "notes": "",
        "is_default": 1,
    }


def ensure_enterprise_profile(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM enterprise_profiles
            ORDER BY is_default DESC, id
            LIMIT 1
            """
        ).fetchone()
    )
    if row:
        row["is_default"] = bool(row.get("is_default"))
        if own_conn:
            conn.close()
        return row

    profile = _default_profile()
    columns = ", ".join(ENTERPRISE_PROFILE_FIELDS)
    placeholders = ", ".join("?" for _ in ENTERPRISE_PROFILE_FIELDS)
    values = [profile[field] for field in ENTERPRISE_PROFILE_FIELDS]
    with conn:
        cur = conn.execute(f"INSERT INTO enterprise_profiles ({columns}) VALUES ({placeholders})", values)
    row = row_to_dict(conn.execute("SELECT * FROM enterprise_profiles WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    row["is_default"] = bool(row.get("is_default"))
    if own_conn:
        conn.close()
    return row


def get_enterprise_profile(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    return ensure_enterprise_profile(conn=conn)


def update_enterprise_profile(
    data: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    profile = ensure_enterprise_profile(conn=conn)
    cleaned: dict[str, Any] = {}
    for field in ENTERPRISE_PROFILE_FIELDS:
        if field not in data:
            continue
        if field == "is_default":
            cleaned[field] = _truthy(data.get(field))
        else:
            cleaned[field] = str(data.get(field) or "").strip()
    if cleaned:
        if cleaned.get("is_default"):
            with conn:
                conn.execute("UPDATE enterprise_profiles SET is_default = 0 WHERE id <> ?", (profile["id"],))
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE enterprise_profiles
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*cleaned.values(), profile["id"]),
            )
    row = row_to_dict(conn.execute("SELECT * FROM enterprise_profiles WHERE id = ?", (profile["id"],)).fetchone()) or {}
    row["is_default"] = bool(row.get("is_default"))
    if own_conn:
        conn.close()
    return row


def enterprise_summary(profile: dict[str, Any]) -> str:
    labels = {
        "profile_name": "资料名称",
        "bidder_name": "投标单位",
        "legal_representative": "法定代表人",
        "contact": "联系方式",
        "qualification_summary": "资质能力",
        "capability_summary": "综合履约能力",
        "quality_system": "质量管理体系",
        "safety_system": "安全文明体系",
        "key_personnel": "拟投入人员",
        "equipment_resources": "机械设备与资源",
        "similar_projects": "类似业绩",
        "service_commitment": "服务承诺",
        "notes": "备注",
    }
    lines: list[str] = []
    for field in TEXT_FIELDS:
        value = str(profile.get(field) or "").strip()
        if value:
            lines.append(f"- {labels[field]}：{value}")
    return "\n".join(lines)


def render_enterprise_profile_markdown(conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    profile = get_enterprise_profile(conn=conn)
    lines = ["# 投标单位资料", ""]
    summary = enterprise_summary(profile)
    if summary:
        lines.append(summary)
    else:
        lines.append("> 暂未维护投标单位资料。正式投标前请补齐投标单位、资质能力、人员设备和类似业绩。")
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
