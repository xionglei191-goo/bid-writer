from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


MATERIAL_FIELDS = (
    "category",
    "name",
    "status",
    "required",
    "source",
    "notes",
    "owner",
    "due_at",
)

DONE_STATUSES = {"已具备", "已识别", "已登记", "已确认", "已完成", "不需要"}

DEFAULT_MATERIALS = (
    {
        "category": "招标资料",
        "name": "完整招标文件",
        "status": "待补充",
        "required": 1,
        "notes": "用于解析评分办法、目录要求和技术条款。",
    },
    {
        "category": "招标资料",
        "name": "评分办法与技术评审标准",
        "status": "待确认",
        "required": 1,
        "notes": "决定章节优先级和响应深度。",
    },
    {
        "category": "项目资料",
        "name": "项目基础资料",
        "status": "待补充",
        "required": 1,
        "notes": "包括工程类型、建设规模、承包范围、结构形式和特殊要求。",
    },
    {
        "category": "项目资料",
        "name": "工期、质量、安全目标",
        "status": "待补充",
        "required": 1,
        "notes": "技术标进度、质量、安全章节需要准确响应。",
    },
    {
        "category": "深化资料",
        "name": "图纸、清单或现场条件",
        "status": "待确认",
        "required": 0,
        "notes": "用于工程重难点、施工部署、总平面和主要工艺深化。",
    },
    {
        "category": "格式资料",
        "name": "企业模板或历史偏好",
        "status": "待确认",
        "required": 0,
        "notes": "用于统一封面、页眉页脚、字体、目录和常用承诺口径。",
    },
)


def _requirement_count(conn: sqlite3.Connection, tender_id: int, kind: str = "") -> int:
    if kind:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM requirements WHERE tender_id = ? AND kind = ?",
                (tender_id, kind),
            ).fetchone()[0]
        )
    return int(conn.execute("SELECT COUNT(*) FROM requirements WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _inferred_status(conn: sqlite3.Connection, tender_id: int, name: str) -> str:
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    task = get_production_task(tender_id, conn=conn)
    raw_text_length = len(str(tender.get("raw_text") or "").strip())
    if name == "完整招标文件":
        return "已具备" if tender.get("file_path") or raw_text_length >= 800 else "待补充"
    if name == "评分办法与技术评审标准":
        return "已识别" if _requirement_count(conn, tender_id, "scoring") else ("待确认" if _requirement_count(conn, tender_id) else "待补充")
    if name == "项目基础资料":
        return "已登记" if profile.get("project_type") and (profile.get("building_area") or profile.get("contract_scope")) else "待补充"
    if name == "工期、质量、安全目标":
        ready = profile.get("duration_days") and profile.get("quality_target") and profile.get("safety_target")
        return "已登记" if ready else "待补充"
    return ""


def ensure_default_materials(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    existing = {
        str(row["name"]): row_to_dict(row)
        for row in conn.execute("SELECT * FROM material_items WHERE tender_id = ?", (tender_id,)).fetchall()
    }
    with conn:
        for item in DEFAULT_MATERIALS:
            inferred = _inferred_status(conn, tender_id, item["name"]) or str(item["status"])
            if item["name"] not in existing:
                conn.execute(
                    """
                    INSERT INTO material_items (tender_id, category, name, status, required, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tender_id,
                        item["category"],
                        item["name"],
                        inferred,
                        int(item["required"]),
                        item["notes"],
                    ),
                )
            elif inferred in DONE_STATUSES and str(existing[item["name"]].get("status") or "") not in DONE_STATUSES:
                conn.execute(
                    """
                    UPDATE material_items
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (inferred, existing[item["name"]]["id"]),
                )
    result = list_material_items(tender_id, conn=conn, sync=False)
    if own_conn:
        conn.close()
    return result


def list_material_items(
    tender_id: int,
    conn: sqlite3.Connection | None = None,
    sync: bool = True,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    if sync:
        ensure_default_materials(tender_id, conn=conn)
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM material_items
            WHERE tender_id = ?
            ORDER BY required DESC, category, id
            """,
            (tender_id,),
        ).fetchall()
    )
    for row in rows:
        row["required"] = bool(row.get("required"))
    if own_conn:
        conn.close()
    return rows


def create_material_item(tender_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Material name is required")
    cleaned = {
        "category": str(data.get("category") or "补充资料").strip(),
        "name": name,
        "status": str(data.get("status") or "待补充").strip(),
        "required": 1 if data.get("required", True) in {True, 1, "1", "true", "yes", "是"} else 0,
        "source": str(data.get("source") or "").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "owner": str(data.get("owner") or "").strip(),
        "due_at": str(data.get("due_at") or "").strip(),
    }
    with conn:
        cur = conn.execute(
            """
            INSERT INTO material_items (tender_id, category, name, status, required, source, notes, owner, due_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tender_id, *[cleaned[field] for field in MATERIAL_FIELDS]),
        )
    item = row_to_dict(conn.execute("SELECT * FROM material_items WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    item["required"] = bool(item.get("required"))
    if own_conn:
        conn.close()
    return item


def update_material_item(item_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = row_to_dict(conn.execute("SELECT * FROM material_items WHERE id = ?", (item_id,)).fetchone())
    if not current:
        raise ValueError(f"Material item not found: {item_id}")
    cleaned: dict[str, Any] = {}
    for field in MATERIAL_FIELDS:
        if field not in data:
            continue
        if field == "required":
            cleaned[field] = 1 if data.get(field) in {True, 1, "1", "true", "yes", "是"} else 0
        else:
            cleaned[field] = str(data.get(field) or "").strip()
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE material_items
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*cleaned.values(), item_id),
            )
    item = row_to_dict(conn.execute("SELECT * FROM material_items WHERE id = ?", (item_id,)).fetchone()) or {}
    item["required"] = bool(item.get("required"))
    if own_conn:
        conn.close()
    return item


def delete_material_item(item_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        cur = conn.execute("DELETE FROM material_items WHERE id = ?", (item_id,))
    if own_conn:
        conn.close()
    return {"material_id": item_id, "deleted": cur.rowcount > 0}


def material_summary(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    items = list_material_items(tender_id, conn=conn)
    required = [item for item in items if item.get("required")]
    completed = [item for item in items if str(item.get("status") or "") in DONE_STATUSES]
    required_completed = [item for item in required if str(item.get("status") or "") in DONE_STATUSES]
    pending_required = [item for item in required if str(item.get("status") or "") not in DONE_STATUSES]
    result = {
        "total": len(items),
        "required": len(required),
        "completed": len(completed),
        "required_completed": len(required_completed),
        "pending_required": len(pending_required),
        "pending_required_items": pending_required,
        "completion_rate": round(len(required_completed) / len(required), 4) if required else 1,
    }
    if own_conn:
        conn.close()
    return result


def render_materials_markdown(tender_id: int, conn: sqlite3.Connection | None = None) -> str:
    own_conn = conn is None
    conn = conn or connect()
    items = list_material_items(tender_id, conn=conn)
    summary = material_summary(tender_id, conn=conn)
    lines = [
        "# 资料清单",
        "",
        f"- 资料总数：{summary['total']}",
        f"- 必要资料：{summary['required']}",
        f"- 必要资料完成：{summary['required_completed']}/{summary['required']}",
        "",
        "## 明细",
    ]
    for item in items:
        required = "必需" if item.get("required") else "可选"
        lines.append(f"- [{item.get('status')}] {item.get('category')} / {item.get('name')}（{required}）")
        detail = "；".join(
            part
            for part in (
                f"来源：{item.get('source')}" if item.get("source") else "",
                f"负责人：{item.get('owner')}" if item.get("owner") else "",
                f"期限：{item.get('due_at')}" if item.get("due_at") else "",
                f"备注：{item.get('notes')}" if item.get("notes") else "",
            )
            if part
        )
        if detail:
            lines.append(f"  - {detail}")
    if own_conn:
        conn.close()
    return "\n".join(lines).strip() + "\n"
