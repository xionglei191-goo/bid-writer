from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .settings import DATA_DIR, MANIFEST_PATH, SECTIONS_PATH


BENCHMARK_PATH = DATA_DIR / "formal_delivery_benchmarks.json"
BENCHMARKS = (
    {"key": "hospital-190", "prefix": "190", "industry": "医院", "tender_id": 190},
    {"key": "school-005", "prefix": "005", "industry": "学校", "match_terms": ["昆明理工大学医学院"]},
    {"key": "municipal-023", "prefix": "023", "industry": "市政", "match_terms": ["红河州泸西县城乡冷链物流园区"]},
    {"key": "factory-011", "prefix": "011", "industry": "厂房", "match_terms": ["杭州三一重工"]},
    {"key": "water-010", "prefix": "010", "industry": "水利水务", "match_terms": ["子牙循环经济产业区污水处理厂"]},
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _convert_benchmark_docx(source: Path, prefix: str) -> tuple[dict[str, Any], list[str]]:
    output_dir = DATA_DIR / "benchmarks" / prefix
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "source.md"
    headings_path = output_dir / "headings.json"
    if markdown_path.exists() and headings_path.exists():
        headings = json.loads(headings_path.read_text(encoding="utf-8"))
    else:
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        with zipfile.ZipFile(source) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        lines: list[str] = []
        headings = []
        for paragraph in root.findall(f".//{{{namespace}}}p"):
            text_value = "".join(node.text or "" for node in paragraph.findall(f".//{{{namespace}}}t")).strip()
            if not text_value:
                continue
            style_node = paragraph.find(f"./{{{namespace}}}pPr/{{{namespace}}}pStyle")
            style = style_node.get(f"{{{namespace}}}val", "") if style_node is not None else ""
            heading_match = re.match(r"^(?:第[一二三四五六七八九十百]+[篇章节]|\d+(?:\.\d+){0,3})[、.\s]", text_value)
            if "heading" in style.lower() or "标题" in style or heading_match:
                level = min(3, max(1, style[-1:].isdigit() and int(style[-1]) or text_value.count(".") + 1))
                lines.append(f"\n{'#' * level} {text_value}\n")
                headings.append(text_value)
            else:
                lines.append(text_value)
        markdown_path.write_text("\n\n".join(lines), encoding="utf-8")
        headings = list(dict.fromkeys(headings))[:80]
        headings_path.write_text(json.dumps(headings, ensure_ascii=False, indent=2), encoding="utf-8")
    return (
        {
            "source_path": str(source),
            "markdown_path": str(markdown_path),
            "char_count": len(markdown_path.read_text(encoding="utf-8", errors="ignore")),
            "section_count": len(headings),
        },
        headings,
    )


def build_benchmark_dataset(*, refresh: bool = False) -> dict[str, Any]:
    if BENCHMARK_PATH.exists() and not refresh:
        current = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
        if current.get("version") == "1.2":
            return current
    manifest = _read_csv(MANIFEST_PATH)
    sections = _read_csv(SECTIONS_PATH)
    projects: list[dict[str, Any]] = []
    for spec in BENCHMARKS:
        prefix = spec["prefix"]
        match_terms = spec.get("match_terms") or []
        source_rows = [
            row
            for row in manifest
            if (
                str(row.get("top_number") or "").zfill(3) == prefix
                or any(term in f"{row.get('top_project') or ''} {row.get('source_path') or ''}" for term in match_terms)
            )
            and row.get("status") == "ok"
            and row.get("duplicate_policy") in {"primary_docx", "primary_pdf", "primary_pdf_text", "standalone"}
        ]
        source_rows.sort(key=lambda row: int(float(row.get("char_count") or 0)), reverse=True)
        selected = source_rows[:5]
        selected_paths = {row.get("markdown_path") or "" for row in selected}
        headings = [
            row.get("heading_text") or ""
            for row in sections
            if row.get("markdown_path") in selected_paths and 1 <= int(row.get("heading_level") or 0) <= 3
        ]
        unique_headings = list(dict.fromkeys(item.strip() for item in headings if item.strip()))[:40]
        fallback_documents: list[dict[str, Any]] = []
        if not selected:
            converted = next((DATA_DIR / "benchmarks" / prefix).glob("*.docx"), None)
            if converted:
                fallback, fallback_headings = _convert_benchmark_docx(converted, prefix)
                fallback_documents.append(fallback)
                unique_headings = fallback_headings[:40]
        project = {
            **spec,
            "status": "ready" if selected or fallback_documents or spec.get("tender_id") else "missing",
            "top_category": selected[0].get("top_category") if selected else spec["industry"],
            "project_name": (selected[0].get("top_project") or Path(selected[0].get("source_path") or "").parts[0]) if selected else ("项目190正式验收基准" if spec.get("tender_id") else "待补基准"),
            "source_documents": fallback_documents or [
                {
                    "source_path": row.get("source_path") or "",
                    "markdown_path": row.get("markdown_path") or "",
                    "char_count": int(float(row.get("char_count") or 0)),
                    "section_count": int(float(row.get("section_count") or 0)),
                }
                for row in selected
            ],
            "representative_headings": unique_headings,
        }
        project["content_fingerprint"] = _fingerprint(project)
        projects.append(project)
    result = {
        "version": "1.2",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fixed": True,
        "projects": projects,
        "summary": {
            "total": len(projects),
            "ready": sum(1 for item in projects if item["status"] == "ready"),
            "industries": [item["industry"] for item in projects],
        },
    }
    result["dataset_fingerprint"] = _fingerprint(projects)
    BENCHMARK_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
