from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import requests
from pypdf import PdfReader, PdfWriter

from ..settings import Settings
from ..utils import normalize_text, write_text_atomic


def _raise_for_status(response: requests.Response) -> None:
    """Preserve the provider error body without ever logging credentials."""
    if response.ok:
        return
    detail = normalize_text(response.text)[:800]
    raise RuntimeError(f"OCR API HTTP {response.status_code}: {detail or response.reason}")


def ocr_pdf_step(
    path: Path,
    source_id: int,
    settings: Settings,
    *,
    max_new_chunks: int = 1,
) -> dict[str, object]:
    """Process a bounded number of OCR chunks and persist each result.

    Existing ``.md`` sidecars are the durable provider cache.  A caller can
    invoke this repeatedly after a worker restart; completed chunks are read
    from disk and are never uploaded again.
    """
    token = os.environ.get(settings.ocr_token_env)
    if not token:
        raise RuntimeError(f"{settings.ocr_token_env}未配置")
    reader = PdfReader(str(path))
    chunk_dir = settings.cache_root / "ocr_chunks" / str(source_id)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    completed_chunks = 0
    new_chunks = 0
    total_chunks = math.ceil(len(reader.pages) / settings.ocr_chunk_pages) if reader.pages else 0
    for start in range(0, len(reader.pages), settings.ocr_chunk_pages):
        end = min(start + settings.ocr_chunk_pages, len(reader.pages))
        chunk_path = chunk_dir / f"pages_{start + 1}_{end}.pdf"
        result_path = chunk_path.with_suffix(".md")
        if result_path.exists():
            parts.append(result_path.read_text(encoding="utf-8"))
            completed_chunks += 1
            continue
        if new_chunks >= max(0, max_new_chunks):
            continue
        if not chunk_path.exists():
            writer = PdfWriter()
            for page in reader.pages[start:end]:
                writer.add_page(page)
            with chunk_path.open("wb") as handle:
                writer.write(handle)
        markdown = _run_job(chunk_path, token, start, settings)
        write_text_atomic(result_path, markdown)
        parts.append(markdown)
        completed_chunks += 1
        new_chunks += 1
    completed = completed_chunks == total_chunks
    return {
        "completed": completed,
        "markdown": normalize_text("\n\n".join(parts)) if completed else "",
        "page_count": len(reader.pages),
        "completed_chunks": completed_chunks,
        "total_chunks": total_chunks,
        "completed_pages": min(len(reader.pages), completed_chunks * settings.ocr_chunk_pages),
    }


def ocr_pdf(path: Path, source_id: int, settings: Settings) -> tuple[str, int]:
    """Compatibility wrapper that completes all remaining cached chunks."""
    while True:
        result = ocr_pdf_step(path, source_id, settings, max_new_chunks=1)
        if result["completed"]:
            return str(result["markdown"]), int(result["page_count"])


def _run_job(path: Path, token: str, page_offset: int, settings: Settings) -> str:
    headers = {"Authorization": f"bearer {token}"}
    optional = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": True,
    }
    with path.open("rb") as handle:
        response = requests.post(
            settings.ocr_job_url,
            headers=headers,
            data={"model": settings.ocr_model, "optionalPayload": json.dumps(optional)},
            files={"file": handle},
            timeout=180,
        )
    _raise_for_status(response)
    job_id = response.json()["data"]["jobId"]
    for _ in range(settings.ocr_max_polls):
        status_response = requests.get(f"{settings.ocr_job_url}/{job_id}", headers=headers, timeout=60)
        _raise_for_status(status_response)
        data = status_response.json()["data"]
        state = data["state"]
        if state == "done":
            json_url = data["resultUrl"]["jsonUrl"]
            result = requests.get(json_url, timeout=180)
            _raise_for_status(result)
            blocks: list[str] = []
            page_number = page_offset
            for line in result.text.splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)["result"]
                for parsed in payload.get("layoutParsingResults") or []:
                    page_number += 1
                    blocks.append(f"<!-- page:{page_number} -->")
                    blocks.append(parsed["markdown"]["text"])
            return "\n\n".join(blocks)
        if state == "failed":
            raise RuntimeError(data.get("errorMsg") or "OCR任务失败")
        time.sleep(settings.ocr_poll_interval_seconds)
    raise TimeoutError(f"OCR任务超时：{job_id}")
