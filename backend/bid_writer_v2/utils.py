from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def family_key(path: Path) -> str:
    stem = path.stem.lower()
    stem = re.sub(r"(?:最终|定稿|修改|新版|扫描|盖章|打印|副本|copy|final|v\d+)", "", stem)
    stem = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", stem)
    return stem[:160] or content_hash(path.name)[:24]


def infer_industry(path: Path) -> str:
    text = str(path)
    mappings = [
        ("医院", "医院"),
        ("学校", "学校"),
        ("市政", "市政"),
        ("道路", "市政"),
        ("厂房", "厂房"),
        ("工业", "厂房"),
        ("水利", "水利"),
        ("河道", "水利"),
    ]
    for keyword, industry in mappings:
        if keyword in text:
            return industry
    return "通用"


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def public_payload(value: Any) -> Any:
    """Remove secrets and host filesystem paths from API-facing payloads."""
    hidden = {
        "absolute_path",
        "file_path",
        "local_mirror_path",
        "markdown_path",
        "password_hash",
        "token_hash",
        "code_verifier",
    }
    if isinstance(value, list):
        return [public_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in hidden:
            if key.endswith("path") and item:
                result[f"{key}_name"] = Path(str(item)).name
            continue
        result[key] = public_payload(item)
    return result
