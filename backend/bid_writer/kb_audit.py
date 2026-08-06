from __future__ import annotations

import csv
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect
from .settings import KB_ROOT, MANIFEST_PATH, PROJECT_ROOT


def _first_dir(path: str) -> str:
    text = str(path or "").replace("/", "\\").strip("\\")
    return text.split("\\", 1)[0] if text else "未归类"


def _int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _markdown_exists(markdown_path: str) -> bool:
    if not markdown_path:
        return False
    rel = Path(markdown_path)
    return (PROJECT_ROOT / rel).exists() or (KB_ROOT / rel).exists()


def _reason(row: dict[str, str], indexed: bool, markdown_exists: bool) -> str:
    status = row.get("status") or ""
    action = row.get("processing_action") or ""
    policy = row.get("duplicate_policy") or ""
    note = row.get("note") or ""
    if status == "ok" and indexed:
        return ""
    if status == "ok" and not markdown_exists:
        return "Markdown 文件缺失，需重新标准化"
    if status == "ok" and not indexed:
        return "已生成 Markdown，但当前 SQLite 未索引"
    if status == "pending_ocr" or action == "pdf_ocr_pending":
        return "扫描版 PDF OCR 未完成或待重试"
    if action == "skip_exact_duplicate" or policy == "exact_duplicate":
        return "重复文件，已由主文件入库"
    if action == "skip_word_primary" or policy == "pdf_print_version":
        return "PDF 与 Word 版对应，已使用 Word 主文件入库"
    if "encrypted" in note.lower() or "document closed" in note.lower():
        return "文件关闭或加密，无法解析"
    if "too little text" in note.lower():
        return "PDF 文本过少，需 OCR 或人工复核"
    return note or action or status or "未记录原因"


def _new_dir(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "manifest_files": 0,
        "ok_files": 0,
        "indexed_files": 0,
        "skipped_files": 0,
        "pending_ocr": 0,
        "missing_markdown": 0,
        "not_indexed": 0,
        "sections": 0,
        "chunks": 0,
        "char_count": 0,
        "page_count": 0,
        "reason_counts": Counter(),
        "categories": Counter(),
        "samples": [],
    }


def _db_documents(conn: sqlite3.Connection) -> tuple[set[str], dict[str, dict[str, int]]]:
    rows = conn.execute(
        """
        SELECT
            d.source_path,
            d.top_category,
            COALESCE(d.char_count, 0) AS char_count,
            COALESCE(d.page_count, 0) AS page_count,
            COUNT(DISTINCT s.id) AS sections,
            COUNT(DISTINCT c.id) AS chunks
        FROM documents d
        LEFT JOIN sections s ON s.document_id = d.id
        LEFT JOIN chunks c ON c.document_id = d.id
        GROUP BY d.id
        """
    ).fetchall()
    indexed_paths = {str(row["source_path"] or "") for row in rows}
    by_dir: dict[str, dict[str, int]] = defaultdict(lambda: {"documents": 0, "sections": 0, "chunks": 0})
    for row in rows:
        directory = _first_dir(str(row["source_path"] or ""))
        by_dir[directory]["documents"] += 1
        by_dir[directory]["sections"] += int(row["sections"] or 0)
        by_dir[directory]["chunks"] += int(row["chunks"] or 0)
    return indexed_paths, by_dir


def build_kb_audit(limit_directories: int = 160, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    indexed_paths, indexed_by_dir = _db_documents(conn)
    indexed_summary = conn.execute(
        "SELECT COUNT(*) AS documents, COALESCE(SUM(char_count), 0) AS chars, COALESCE(SUM(page_count), 0) AS pages FROM documents"
    ).fetchone()
    indexed_sections = int(conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0])
    indexed_chunks = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    status_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    duplicate_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    global_reasons: Counter[str] = Counter()
    directories: dict[str, dict[str, Any]] = {}
    manifest_rows = 0
    ok_rows = 0
    skipped_rows = 0
    pending_rows = 0

    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open("r", newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                manifest_rows += 1
                source_path = row.get("source_path") or ""
                directory = row.get("top_dir") or _first_dir(source_path)
                item = directories.setdefault(directory, _new_dir(directory))
                item["manifest_files"] += 1
                status = row.get("status") or "unknown"
                action = row.get("processing_action") or "unknown"
                policy = row.get("duplicate_policy") or "unknown"
                category = row.get("top_category") or "未分类"
                status_counts[status] += 1
                action_counts[action] += 1
                duplicate_counts[policy] += 1
                category_counts[category] += 1
                item["categories"][category] += 1
                item["char_count"] += _int(row.get("char_count"))
                item["page_count"] += _int(row.get("page_count"))
                indexed = source_path in indexed_paths
                md_exists = _markdown_exists(row.get("markdown_path") or "") if status == "ok" else False
                reason = _reason(row, indexed, md_exists)
                if status == "ok":
                    ok_rows += 1
                    item["ok_files"] += 1
                    if indexed:
                        item["indexed_files"] += 1
                    else:
                        item["not_indexed"] += 1
                elif status == "pending_ocr":
                    pending_rows += 1
                    item["pending_ocr"] += 1
                else:
                    skipped_rows += 1
                    item["skipped_files"] += 1
                if status == "ok" and not md_exists:
                    item["missing_markdown"] += 1
                if reason:
                    item["reason_counts"][reason] += 1
                    global_reasons[reason] += 1
                if len(item["samples"]) < 3 and status == "ok":
                    item["samples"].append(
                        {
                            "source_path": source_path,
                            "markdown_path": row.get("markdown_path") or "",
                            "top_project": row.get("top_project") or "",
                            "top_category": row.get("top_category") or "",
                            "char_count": _int(row.get("char_count")),
                        }
                    )

    for directory, counters in indexed_by_dir.items():
        item = directories.setdefault(directory, _new_dir(directory))
        item["indexed_files"] = max(item["indexed_files"], counters["documents"])
        item["sections"] = counters["sections"]
        item["chunks"] = counters["chunks"]

    directory_items: list[dict[str, Any]] = []
    for item in directories.values():
        issue_count = int(item["skipped_files"] + item["pending_ocr"] + item["missing_markdown"] + item["not_indexed"])
        if item["manifest_files"] and item["ok_files"] == item["indexed_files"] and issue_count == 0:
            state = "complete"
            label = "已入库"
        elif item["indexed_files"]:
            state = "partial"
            label = "部分入库"
        else:
            state = "blocked"
            label = "未完成入库"
        directory_items.append(
            {
                "name": item["name"],
                "state": state,
                "status_label": label,
                "manifest_files": item["manifest_files"],
                "ok_files": item["ok_files"],
                "indexed_files": item["indexed_files"],
                "skipped_files": item["skipped_files"],
                "pending_ocr": item["pending_ocr"],
                "missing_markdown": item["missing_markdown"],
                "not_indexed": item["not_indexed"],
                "sections": item["sections"],
                "chunks": item["chunks"],
                "char_count": item["char_count"],
                "page_count": item["page_count"],
                "issue_count": issue_count,
                "top_reasons": [{"reason": reason, "count": count} for reason, count in item["reason_counts"].most_common(5)],
                "top_categories": [{"category": category, "count": count} for category, count in item["categories"].most_common(3)],
                "samples": item["samples"],
            }
        )
    directory_items.sort(key=lambda row: (row["state"] == "complete", -int(row["issue_count"]), row["name"]))
    if limit_directories:
        directory_items = directory_items[:limit_directories]

    indexed_documents = int((indexed_summary or {})["documents"] if indexed_summary else 0)
    summary = {
        "title": "知识库体检",
        "manifest_exists": MANIFEST_PATH.exists(),
        "manifest_rows": manifest_rows,
        "manifest_ok": ok_rows,
        "manifest_skipped": skipped_rows,
        "manifest_pending_ocr": pending_rows,
        "indexed_documents": indexed_documents,
        "indexed_sections": indexed_sections,
        "indexed_chunks": indexed_chunks,
        "indexed_chars": int((indexed_summary or {})["chars"] if indexed_summary else 0),
        "indexed_pages": int((indexed_summary or {})["pages"] if indexed_summary else 0),
        "indexed_rate": round(indexed_documents / ok_rows, 4) if ok_rows else 0,
        "directories": len(directories),
        "complete_directories": sum(1 for item in directories.values() if item["manifest_files"] and item["ok_files"] == item["indexed_files"] and not (item["skipped_files"] + item["pending_ocr"] + item["missing_markdown"] + item["not_indexed"])),
        "incomplete_directories": sum(1 for item in directories.values() if item["skipped_files"] or item["pending_ocr"] or item["missing_markdown"] or item["not_indexed"] or not item["indexed_files"]),
        "missing_markdown": sum(int(item["missing_markdown"]) for item in directories.values()),
        "not_indexed": sum(int(item["not_indexed"]) for item in directories.values()),
    }
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "status_counts": [{"status": key, "count": count} for key, count in status_counts.most_common()],
        "action_counts": [{"action": key, "count": count} for key, count in action_counts.most_common(12)],
        "duplicate_policy_counts": [{"policy": key, "count": count} for key, count in duplicate_counts.most_common(12)],
        "top_categories": [{"category": key, "count": count} for key, count in category_counts.most_common(20)],
        "top_reasons": [{"reason": key, "count": count} for key, count in global_reasons.most_common(12)],
        "directories": directory_items,
        "report_paths": {
            "manifest": str(MANIFEST_PATH),
            "directory_markdown": str(KB_ROOT / "入库状态_按目录.md"),
            "directory_summary_csv": str(KB_ROOT / "入库状态_按目录汇总.csv"),
            "directory_detail_csv": str(KB_ROOT / "入库状态_按目录明细.csv"),
        },
    }
    result["markdown"] = render_kb_audit_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_kb_audit_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# 知识库体检报告",
        "",
        f"- 生成时间：{report.get('generated_at') or ''}",
        f"- Manifest 记录：{summary.get('manifest_rows', 0)} 条",
        f"- 可入库记录：{summary.get('manifest_ok', 0)} 条",
        f"- 已索引文档：{summary.get('indexed_documents', 0)} 份",
        f"- 已索引章节：{summary.get('indexed_sections', 0)} 个",
        f"- 已索引片段：{summary.get('indexed_chunks', 0)} 个",
        f"- 目录数量：{summary.get('directories', 0)}，未完成目录：{summary.get('incomplete_directories', 0)}",
        f"- 重复或跳过：{summary.get('manifest_skipped', 0)} 条，待 OCR：{summary.get('manifest_pending_ocr', 0)} 条",
        "",
        "## 未入库原因 Top",
    ]
    for item in report.get("top_reasons") or []:
        lines.append(f"- {item.get('reason')}：{item.get('count')}")
    lines.extend(["", "## 行业分布 Top"])
    for item in (report.get("top_categories") or [])[:12]:
        lines.append(f"- {item.get('category')}：{item.get('count')}")
    lines.extend(["", "## 按目录摘要"])
    for item in (report.get("directories") or [])[:80]:
        reasons = "；".join(f"{r.get('reason')} {r.get('count')}" for r in item.get("top_reasons") or [])
        lines.append(
            f"- [{item.get('status_label')}] {item.get('name')}：入库 {item.get('indexed_files', 0)}/{item.get('manifest_files', 0)}，"
            f"章节 {item.get('sections', 0)}，片段 {item.get('chunks', 0)}"
            + (f"，原因：{reasons}" if reasons else "")
        )
    return "\n".join(lines).strip() + "\n"
