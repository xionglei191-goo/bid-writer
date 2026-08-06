from __future__ import annotations

import re
import json
import hashlib
import sqlite3
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .settings import QA_DIR


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "a": A_NS, "r": R_NS, "pr": PKG_REL_NS}

INTERNAL_ONLY_TERMS = (
    "收款记录",
    "响应矩阵",
    "内部审查",
    "来源路径",
    "生成任务",
    "客户沟通记录",
    "技术标智能编制系统生成",
    "正式投标前请人工复核",
    "历史资料示例图",
)


def _int_attr(node: ET.Element | None, name: str) -> int | None:
    if node is None:
        return None
    value = node.get(f"{{{W_NS}}}{name}")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def audit_docx(path: str | Path, *, formal: bool = True) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        return {"path": str(source), "ready": False, "blockers": ["DOCX文件不存在"], "warnings": [], "metrics": {}}

    blockers: list[str] = []
    warnings: list[str] = []
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        root = ET.fromstring(archive.read("word/document.xml"))
        text = "".join(node.text or "" for node in root.findall(".//w:t", NS))
        paragraph_texts = [
            "".join(node.text or "" for node in paragraph.findall(".//w:t", NS)).strip()
            for paragraph in root.findall(".//w:p", NS)
        ]
        tables = root.findall(".//w:tbl", NS)
        drawings = root.findall(".//w:drawing", NS)
        page_breaks = [
            node for node in root.findall(".//w:br", NS) if node.get(f"{{{W_NS}}}type") == "page"
        ]
        markdown_separators = re.findall(r"\|\s*:?-{3,}:?\s*\|", text)
        if markdown_separators:
            blockers.append(f"检测到 {len(markdown_separators)} 处Markdown表格分隔符")
        if formal:
            leaked: list[str] = []
            for term in INTERNAL_ONLY_TERMS:
                if term in {"收款记录", "响应矩阵"}:
                    found = any(value.strip("：: ") == term for value in paragraph_texts)
                else:
                    found = any(term in value for value in paragraph_texts)
                if found:
                    leaked.append(term)
            if leaked:
                blockers.append("正式稿包含内部字段：" + "、".join(leaked))

        geometry_issues = 0
        exact_height_rows = 0
        for table in tables:
            tbl_w = _int_attr(table.find("./w:tblPr/w:tblW", NS), "w")
            grid_widths = [_int_attr(node, "w") or 0 for node in table.findall("./w:tblGrid/w:gridCol", NS)]
            if not tbl_w or not grid_widths or abs(tbl_w - sum(grid_widths)) > max(20, len(grid_widths) * 4):
                geometry_issues += 1
            for row in table.findall("./w:tr", NS):
                height = row.find("./w:trPr/w:trHeight", NS)
                if height is not None and height.get(f"{{{W_NS}}}hRule") == "exact":
                    exact_height_rows += 1
        if geometry_issues:
            blockers.append(f"有 {geometry_issues} 个表格的总宽度、网格列宽未完全一致")
        if exact_height_rows:
            blockers.append(f"有 {exact_height_rows} 行使用固定高度，可能截断文字")

        missing_images: list[str] = []
        rel_name = "word/_rels/document.xml.rels"
        if rel_name in names:
            rel_root = ET.fromstring(archive.read(rel_name))
            for rel in rel_root.findall("pr:Relationship", NS):
                rel_type = rel.get("Type") or ""
                target = rel.get("Target") or ""
                if rel_type.endswith("/image"):
                    normalized = str((Path("word") / target).as_posix()).replace("word/../", "")
                    if normalized not in names:
                        missing_images.append(target)
        if missing_images:
            blockers.append(f"有 {len(missing_images)} 个图片关系指向缺失文件")
        if drawings and not any(name.startswith("word/media/") for name in names):
            blockers.append("文档包含绘图引用但未打包媒体文件")
        if not tables:
            warnings.append("文档未包含原生Word表格")
        if not drawings:
            warnings.append("文档未包含图形或图片")

    metrics = {
        "tables": len(tables),
        "drawings": len(drawings),
        "page_breaks": len(page_breaks),
        "markdown_table_separators": len(markdown_separators),
        "table_geometry_issues": geometry_issues,
        "fixed_height_rows": exact_height_rows,
        "missing_images": len(missing_images),
        "char_count": len(text),
    }
    return {
        "path": str(source),
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": metrics,
    }


def build_preflight_signature(tender_id: int, final_hash: str, conn: sqlite3.Connection) -> str:
    blocks = [
        tuple(row)
        for row in conn.execute(
            """
            SELECT db.id, db.block_type, db.title, db.caption, db.asset_id, db.updated_at,
                   va.file_path, va.review_status, va.updated_at
            FROM document_blocks db
            LEFT JOIN visual_assets va ON va.id = db.asset_id
            WHERE db.tender_id = ? AND db.status = 'active'
            ORDER BY db.id
            """,
            (tender_id,),
        ).fetchall()
    ]
    settings = conn.execute("SELECT * FROM document_settings WHERE tender_id = ?", (tender_id,)).fetchone()
    payload = {
        "final_hash": final_hash,
        "blocks": blocks,
        "settings": tuple(settings) if settings else (),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def save_docx_audit(tender_id: int, audit: dict[str, Any], content_signature: str) -> dict[str, Any]:
    output_dir = QA_DIR / "docx"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"project_{tender_id}_docx_audit.json"
    previous = load_docx_audit(tender_id)
    visual_render = None
    if previous and previous.get("content_signature") == content_signature:
        visual_render = previous.get("visual_render")
    payload = {**audit, "tender_id": tender_id, "content_signature": content_signature}
    if visual_render:
        payload["visual_render"] = visual_render
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["report_path"] = str(output_path)
    return payload


def attach_visual_render_audit(tender_id: int, visual_render: dict[str, Any]) -> dict[str, Any]:
    payload = load_docx_audit(tender_id)
    if not payload:
        raise ValueError("请先完成DOCX结构审计")
    payload["visual_render"] = visual_render
    path = QA_DIR / "docx" / f"project_{tender_id}_docx_audit.json"
    payload.pop("report_path", None)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["report_path"] = str(path)
    return payload


def load_docx_audit(tender_id: int) -> dict[str, Any] | None:
    path = QA_DIR / "docx" / f"project_{tender_id}_docx_audit.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["report_path"] = str(path)
    return payload
