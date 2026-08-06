from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import OCR_DIR


JOB_URL = os.environ.get("PADDLEOCR_JOB_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
MODEL = os.environ.get("PADDLEOCR_MODEL", "PaddleOCR-VL-1.5")


class OCRNotConfigured(RuntimeError):
    pass


class OCRFailed(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("PADDLEOCR_TOKEN") or os.environ.get("PADDLEOCR_API_TOKEN")
    if not token:
        raise OCRNotConfigured("未配置 PADDLEOCR_TOKEN，扫描版 PDF 无法自动 OCR。")
    return token


def _request_json(request: urllib.request.Request, timeout: int = 120) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured OCR endpoint.
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise OCRFailed(f"OCR API HTTP {exc.code}: {detail[:500]}") from exc
    return json.loads(body)


def _multipart_body(path: Path, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----bidwriter{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    file_bytes = path.read_bytes()
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8")
        + file_bytes
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def submit_ocr_job(path: Path) -> str:
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    body, boundary = _multipart_body(
        path,
        {
            "model": MODEL,
            "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
        },
    )
    request = urllib.request.Request(
        JOB_URL,
        data=body,
        headers={
            "Authorization": f"bearer {_token()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    payload = _request_json(request)
    try:
        return str(payload["data"]["jobId"])
    except KeyError as exc:
        raise OCRFailed(f"OCR API 返回缺少 jobId：{payload}") from exc


def poll_ocr_job(job_id: str, poll_interval: int = 5, timeout_seconds: int = 600) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    headers = {"Authorization": f"bearer {_token()}"}
    while time.time() < deadline:
        request = urllib.request.Request(f"{JOB_URL}/{urllib.parse.quote(job_id)}", headers=headers, method="GET")
        payload = _request_json(request, timeout=60)
        data = payload.get("data") or {}
        state = data.get("state")
        if state == "done":
            return data
        if state == "failed":
            raise OCRFailed(str(data.get("errorMsg") or "OCR job failed"))
        time.sleep(poll_interval)
    raise OCRFailed(f"OCR job timeout after {timeout_seconds} seconds: {job_id}")


def download_ocr_markdown(json_url: str, source_path: Path) -> dict[str, Any]:
    with urllib.request.urlopen(json_url, timeout=120) as response:  # noqa: S310 - OCR result URL from API.
        jsonl_text = response.read().decode("utf-8")
    output_dir = OCR_DIR / f"{source_path.stem}_{datetime.now():%Y%m%d%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_parts: list[str] = []
    page_count = 0
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line:
            continue
        result = json.loads(line).get("result", {})
        for res in result.get("layoutParsingResults", []):
            markdown = ((res.get("markdown") or {}).get("text") or "").strip()
            if not markdown:
                continue
            page_count += 1
            page_path = output_dir / f"doc_{page_count}.md"
            page_path.write_text(markdown + "\n", encoding="utf-8")
            markdown_parts.append(markdown)
    combined = "\n\n".join(markdown_parts).strip()
    if not combined:
        raise OCRFailed("OCR 完成但未返回可用 Markdown 文本。")
    combined_path = output_dir / "combined.md"
    combined_path.write_text(combined + "\n", encoding="utf-8")
    return {"text": combined, "page_count": page_count, "output_dir": str(output_dir), "combined_path": str(combined_path)}


def ocr_pdf_to_markdown(path: Path) -> dict[str, Any]:
    job_id = submit_ocr_job(path)
    data = poll_ocr_job(job_id)
    result_url = (data.get("resultUrl") or {}).get("jsonUrl")
    if not result_url:
        raise OCRFailed(f"OCR job 完成但缺少 jsonUrl：{data}")
    result = download_ocr_markdown(str(result_url), path)
    result["job_id"] = job_id
    return result
