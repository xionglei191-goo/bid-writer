from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from pypdf import PdfReader, PdfWriter

from ..settings import Settings
from ..utils import normalize_text, write_text_atomic


JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
MODEL = "PaddleOCR-VL-1.5"


def ocr_pdf(path: Path, source_id: int, settings: Settings) -> tuple[str, int]:
    token = os.environ.get("PADDLE_OCR_TOKEN") or os.environ.get("OCR_TOKEN")
    if not token:
        raise RuntimeError("PADDLE_OCR_TOKEN未配置")
    reader = PdfReader(str(path))
    chunk_dir = settings.cache_root / "ocr_chunks" / str(source_id)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for start in range(0, len(reader.pages), 100):
        end = min(start + 100, len(reader.pages))
        chunk_path = chunk_dir / f"pages_{start + 1}_{end}.pdf"
        if not chunk_path.exists():
            writer = PdfWriter()
            for page in reader.pages[start:end]:
                writer.add_page(page)
            with chunk_path.open("wb") as handle:
                writer.write(handle)
        result_path = chunk_path.with_suffix(".md")
        if result_path.exists():
            parts.append(result_path.read_text(encoding="utf-8"))
            continue
        markdown = _run_job(chunk_path, token, start)
        write_text_atomic(result_path, markdown)
        parts.append(markdown)
    return normalize_text("\n\n".join(parts)), len(reader.pages)


def _run_job(path: Path, token: str, page_offset: int) -> str:
    headers = {"Authorization": f"bearer {token}"}
    optional = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": True,
    }
    with path.open("rb") as handle:
        response = requests.post(
            JOB_URL,
            headers=headers,
            data={"model": MODEL, "optionalPayload": json.dumps(optional)},
            files={"file": handle},
            timeout=180,
        )
    response.raise_for_status()
    job_id = response.json()["data"]["jobId"]
    for _ in range(720):
        status_response = requests.get(f"{JOB_URL}/{job_id}", headers=headers, timeout=60)
        status_response.raise_for_status()
        data = status_response.json()["data"]
        state = data["state"]
        if state == "done":
            json_url = data["resultUrl"]["jsonUrl"]
            result = requests.get(json_url, timeout=180)
            result.raise_for_status()
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
        time.sleep(5)
    raise TimeoutError(f"OCR任务超时：{job_id}")
