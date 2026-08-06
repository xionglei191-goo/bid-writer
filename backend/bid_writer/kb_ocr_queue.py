from __future__ import annotations

import csv
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import connect, init_db
from .document_processing import record_document_processing
from .kb_importer import index_manifest_row
from .ocr import OCRFailed, OCRNotConfigured, ocr_pdf_to_markdown
from .settings import KB_ROOT, MANIFEST_PATH, PROJECT_ROOT
from .text_utils import parse_markdown_sections


def _item_id(source_path: str) -> str:
    return hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:16]


def _token_configured() -> bool:
    return bool(os.environ.get("PADDLEOCR_TOKEN") or os.environ.get("PADDLEOCR_API_TOKEN"))


def _is_pending_ocr(row: dict[str, str]) -> bool:
    return row.get("status") == "pending_ocr" or row.get("processing_action") == "pdf_ocr_pending"


def _resolve_source(source_path: str) -> Path:
    path = Path(source_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _safe_name(text: str, max_len: int = 42) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return (cleaned or "ocr_pdf")[:max_len]


def _manifest_backup_path() -> Path:
    return MANIFEST_PATH.with_name(f"{MANIFEST_PATH.name}.bak_{datetime.now():%Y%m%d%H%M%S}")


def _read_manifest() -> tuple[list[str], list[dict[str, str]]]:
    if not MANIFEST_PATH.exists():
        return [], []
    with MANIFEST_PATH.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def _write_manifest(fieldnames: list[str], rows: list[dict[str, str]]) -> Path:
    backup_path = _manifest_backup_path()
    shutil.copy2(MANIFEST_PATH, backup_path)
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return backup_path


def _try_pdf_pages(path: Path) -> tuple[int | None, str]:
    if not path.exists() or path.suffix.lower() != ".pdf":
        return None, ""
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        return len(reader.pages), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _queue_item(row: dict[str, str], row_number: int, token_configured: bool) -> dict[str, Any]:
    source_path = row.get("source_path") or ""
    source = _resolve_source(source_path)
    file_exists = source.exists()
    size_mb = round(source.stat().st_size / 1024 / 1024, 3) if file_exists else 0
    estimated_pages, page_error = _try_pdf_pages(source)
    note = row.get("note") or ""
    warnings: list[str] = []
    if not token_configured:
        warnings.append("未配置 PADDLEOCR_TOKEN 或 PADDLEOCR_API_TOKEN。")
    if not file_exists:
        warnings.append("原始 PDF 文件不存在，需先恢复文件。")
    if source.suffix.lower() != ".pdf":
        warnings.append("当前记录不是 PDF，暂不进入 OCR 补录。")
    if estimated_pages and estimated_pages > 100:
        warnings.append("超过 100 页，OCR API 可能只解析前 100 页。")
    if "encrypted" in note.lower() or "document closed" in note.lower():
        warnings.append("疑似文件关闭或加密，建议先人工解锁或重新导出 PDF。")
    if page_error:
        warnings.append(f"页数预检失败：{page_error}")

    ready_file = file_exists and source.suffix.lower() == ".pdf"
    can_run = token_configured and ready_file
    status_label = "可补录" if can_run else "待准备"
    if can_run and warnings:
        status_label = "可尝试补录"
    return {
        "id": _item_id(source_path),
        "row_number": row_number,
        "source_path": source_path,
        "source_abs_path": str(source),
        "file_exists": file_exists,
        "source_format": row.get("source_format") or source.suffix.lower().lstrip("."),
        "size_mb": size_mb,
        "estimated_pages": estimated_pages,
        "top_dir": row.get("top_dir") or "",
        "top_category": row.get("top_category") or "",
        "top_project": row.get("top_project") or "",
        "processing_action": row.get("processing_action") or "",
        "duplicate_policy": row.get("duplicate_policy") or "",
        "note": note,
        "status_label": status_label,
        "can_run": can_run,
        "ready_file": ready_file,
        "warnings": warnings,
    }


def build_kb_ocr_queue(limit: int = 80) -> dict[str, Any]:
    fieldnames, rows = _read_manifest()
    token_configured = _token_configured()
    pending = [
        _queue_item(row, row_number=index + 2, token_configured=token_configured)
        for index, row in enumerate(rows)
        if _is_pending_ocr(row)
    ]
    pending.sort(key=lambda item: (not item["can_run"], -float(item["size_mb"] or 0), item["source_path"]))
    shown = pending[:limit] if limit else pending
    summary = {
        "title": "OCR 补录队列",
        "manifest_exists": MANIFEST_PATH.exists(),
        "manifest_fields": len(fieldnames),
        "pending_count": len(pending),
        "shown": len(shown),
        "token_configured": token_configured,
        "ready_files": sum(1 for item in pending if item["ready_file"]),
        "runnable_count": sum(1 for item in pending if item["can_run"]),
        "missing_files": sum(1 for item in pending if not item["file_exists"]),
        "over_100_pages": sum(1 for item in pending if (item.get("estimated_pages") or 0) > 100),
        "total_size_mb": round(sum(float(item.get("size_mb") or 0) for item in pending), 3),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "items": shown,
        "policy": {
            "execution": "仅在人工点击单条补录时调用 OCR；列表刷新不会消耗 OCR 额度。",
            "token": "通过环境变量 PADDLEOCR_TOKEN 或 PADDLEOCR_API_TOKEN 配置，不写入代码。",
            "page_limit": "OCR 服务超过 100 页可能忽略后续页面，补录后仍需人工复核。",
        },
    }


def _find_pending_row(item_id: str) -> tuple[list[str], list[dict[str, str]], int, dict[str, str]]:
    fieldnames, rows = _read_manifest()
    for index, row in enumerate(rows):
        if _is_pending_ocr(row) and _item_id(row.get("source_path") or "") == item_id:
            return fieldnames, rows, index, row
    raise ValueError(f"OCR queue item not found: {item_id}")


def _store_kb_markdown(item_id: str, source_path: Path, text: str) -> tuple[str, str]:
    output_dir = KB_ROOT / "ocr_backlog" / f"{item_id}_{_safe_name(source_path.stem)}"
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "source.md"
    markdown_path.write_text(text.strip() + "\n", encoding="utf-8")
    return str(markdown_path.relative_to(PROJECT_ROOT)), str(output_dir.relative_to(PROJECT_ROOT))


def run_kb_ocr_item(item_id: str, *, reindex: bool = True) -> dict[str, Any]:
    if not _token_configured():
        raise OCRNotConfigured("未配置 PADDLEOCR_TOKEN 或 PADDLEOCR_API_TOKEN，不能执行 OCR 补录。")
    fieldnames, rows, index, row = _find_pending_row(item_id)
    source = _resolve_source(row.get("source_path") or "")
    if not source.exists():
        raise FileNotFoundError(f"原始 PDF 文件不存在：{source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError(f"OCR 补录仅支持 PDF：{source}")

    original_note = row.get("note") or ""
    conn = connect()
    init_db(conn)
    try:
        result = ocr_pdf_to_markdown(source)
        text = str(result.get("text") or "").strip()
        if not text:
            raise OCRFailed("OCR 未返回可入库文本。")
        markdown_rel, output_rel = _store_kb_markdown(item_id, source, text)
        page_count = int(result.get("page_count") or 0)
        section_count = len(parse_markdown_sections(text, default_heading=source.stem))
        updated = dict(row)
        updated.update(
            {
                "markdown_path": markdown_rel,
                "output_dir": output_rel,
                "status": "ok",
                "processing_action": "pdf_ocr_to_markdown",
                "page_count": str(page_count),
                "section_count": str(section_count),
                "char_count": str(len(text)),
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": f"OCR 补录完成；原备注：{original_note}".strip("；"),
            }
        )
        rows[index] = updated
        backup_path = _write_manifest(fieldnames, rows)
        index_counters = {"documents": 0, "sections": 0, "chunks": 0, "missing_markdown": 0}
        if reindex:
            with conn:
                index_counters = index_manifest_row(conn, updated)
        processing = record_document_processing(
            {
                "source_path": str(source),
                "original_filename": source.name,
                "file_type": "pdf",
                "action": "kb_pdf_ocr_to_markdown",
                "status": "success",
                "text_chars": len(text),
                "page_count": page_count,
                "ocr_job_id": result.get("job_id") or "",
                "ocr_output_dir": result.get("output_dir") or "",
                "markdown_path": markdown_rel,
            },
            conn=conn,
        )
        return {
            "item_id": item_id,
            "status": "success",
            "source_path": row.get("source_path") or "",
            "markdown_path": markdown_rel,
            "output_dir": output_rel,
            "manifest_backup": str(backup_path),
            "ocr_job_id": result.get("job_id") or "",
            "page_count": page_count,
            "text_chars": len(text),
            "section_count": section_count,
            "index_counters": index_counters,
            "processing_record": processing,
        }
    except Exception as exc:
        record_document_processing(
            {
                "source_path": str(source),
                "original_filename": source.name,
                "file_type": "pdf",
                "action": "kb_pdf_ocr_to_markdown",
                "status": "failed",
                "error_message": str(exc),
            },
            conn=conn,
        )
        raise
    finally:
        conn.close()
