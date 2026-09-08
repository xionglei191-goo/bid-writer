from __future__ import annotations

import re
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from docx import Document


PLACEHOLDER_PATTERNS = (
    re.compile(r"【\s*待确认(?:[^】]*)】", re.IGNORECASE),
    re.compile(
        r"\[(?![^\]\r\n]+\]\((?:https?://|mailto:))[^\]\r\n]*"
        r"(?:待确认|项目名称|联系电话|投标单位|姓名|证书|数量|尺寸|位置|接驳点|TODO|TBD)"
        r"[^\]\r\n]*\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"<(?:待确认|项目名称|联系电话|投标单位|姓名|证书|数量|尺寸|位置|接驳点)[^>]*>",
        re.IGNORECASE,
    ),
    re.compile(r"(?<![\w/.-])(?:TODO|TBD)(?![\w/.-])", re.IGNORECASE),
)

TEST_DATA_PATTERNS = (
    re.compile(r"HTTP\s*测试(?:投标单位|建设集团有限公司)?", re.IGNORECASE),
    re.compile(r"(?:默认|测试)(?:投标单位|建设集团(?:有限公司)?)"),
)

INTERNAL_CONTENT_PATTERNS = (
    re.compile(r"(?:收款记录|生产任务|客户沟通记录|报价测算|修订任务台账)"),
    re.compile(r"(?:来源路径|模型说明|内部审计资料|内部业务内容)"),
    re.compile(r"(?:[A-Za-z]:\\|/workspace/|bid_writer_app[/\\]data[/\\])[^\s\]\[）)<>\"']*", re.IGNORECASE),
)

UNAPPROVED_VISUAL_PATTERNS = (
    re.compile(r"历史(?:项目|资料)(?:图片|素材|示例图)"),
    re.compile(r"AI\s*(?:生成|场景|图片|素材|说明)", re.IGNORECASE),
    re.compile(r"使用前人工核对适用性"),
    re.compile(r"未(?:经|获)(?:复核|审批|批准)(?:的)?(?:图片|视觉素材)"),
)

RULES = (
    ("placeholder", PLACEHOLDER_PATTERNS),
    ("test_data", TEST_DATA_PATTERNS),
    ("internal_content", INTERNAL_CONTENT_PATTERNS),
    ("unapproved_visual", UNAPPROVED_VISUAL_PATTERNS),
)

REVIEW_PACKAGE_SUFFIXES = {".docx", ".pdf", ".md", ".txt"}


def _context(text: str, start: int, end: int, radius: int = 45) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - radius) : min(len(text), end + radius)]).strip()


def audit_text(text: str, *, source: str = "text") -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, int, int, str]] = set()
    occupied: dict[str, list[tuple[int, int]]] = {}
    url_spans = [match.span() for match in re.finditer(r"(?:https?|mailto):[^\s）)<>\"']+", text or "", re.IGNORECASE)]
    for kind, patterns in RULES:
        for pattern in patterns:
            for match in pattern.finditer(text or ""):
                span = match.span()
                if any(start <= span[0] and span[1] <= end for start, end in url_spans):
                    continue
                if any(max(span[0], start) < min(span[1], end) for start, end in occupied.get(kind, [])):
                    continue
                key = (kind, match.start(), match.end(), match.group(0))
                if key in seen:
                    continue
                seen.add(key)
                occupied.setdefault(kind, []).append(span)
                findings.append(
                    {
                        "kind": kind,
                        "source": source,
                        "match": match.group(0)[:160],
                        "context": _context(text, match.start(), match.end()),
                    }
                )
    findings.sort(key=lambda item: (item["source"], item["kind"], item["context"]))
    counts = Counter(item["kind"] for item in findings)
    return {
        "ready": not findings,
        "source": source,
        "findings": findings,
        "counts": {kind: int(counts.get(kind, 0)) for kind, _patterns in RULES},
    }


def merge_audits(audits: Iterable[dict[str, Any]], *, source: str = "artifacts") -> dict[str, Any]:
    findings = [finding for audit in audits for finding in audit.get("findings") or []]
    counts = Counter(finding.get("kind") or "unknown" for finding in findings)
    return {
        "ready": not findings,
        "source": source,
        "findings": findings,
        "counts": {kind: int(counts.get(kind, 0)) for kind, _patterns in RULES},
    }


def _iter_table_text(table: Any) -> Iterable[str]:
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                if paragraph.text:
                    yield paragraph.text
            for nested in cell.tables:
                yield from _iter_table_text(nested)


def _visible_image_count(document: Document) -> int:
    return len(document.part.element.xpath(".//w:drawing"))


def audit_docx_path(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    document = Document(target)
    audits: list[dict[str, Any]] = []
    body_text = "\n".join(
        [paragraph.text for paragraph in document.paragraphs]
        + [text for table in document.tables for text in _iter_table_text(table)]
    )
    audits.append(audit_text(body_text, source=f"{target.name}:body"))
    for index, section in enumerate(document.sections, start=1):
        for story_name, story in (("header", section.header), ("footer", section.footer)):
            story_text = "\n".join(
                [paragraph.text for paragraph in story.paragraphs]
                + [text for table in story.tables for text in _iter_table_text(table)]
            )
            audits.append(audit_text(story_text, source=f"{target.name}:{story_name}:{index}"))
    # Captions and drawing descriptions may be split across runs or stored only in
    # OOXML attributes, so scan every Word XML part as a final safety net.
    xml_text = "\n".join(
        blob.decode("utf-8", errors="ignore")
        for name, blob in _zip_members(target)
        if name.startswith("word/") and name.endswith(".xml")
    )
    drawing_metadata = "\n".join(re.findall(r"<(?:wp:docPr|pic:cNvPr)\b[^>]*>", xml_text))
    audits.append(audit_text(drawing_metadata, source=f"{target.name}:drawing-metadata"))
    result = merge_audits(audits, source=str(target))
    result.update(
        {
            "path": str(target),
            "visible_images": _visible_image_count(document),
            "paragraphs": len(document.paragraphs),
            "tables": len(document.tables),
            "size_bytes": target.stat().st_size,
        }
    )
    return result


def _zip_members(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        return [(name, archive.read(name)) for name in archive.namelist()]


def audit_zip_path(
    path: str | Path,
    *,
    allowed_names: set[str] | None = None,
    require_review_package_types: bool = False,
) -> dict[str, Any]:
    target = Path(path)
    findings: list[dict[str, str]] = []
    audits: list[dict[str, Any]] = []
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        for name in names:
            normalized = name.replace("\\", "/")
            if normalized.endswith("/"):
                continue
            basename = Path(normalized).name
            if allowed_names is not None and normalized not in allowed_names and basename not in allowed_names:
                findings.append(
                    {
                        "kind": "package_whitelist",
                        "source": target.name,
                        "match": normalized,
                        "context": "客户包包含白名单以外的文件",
                    }
                )
            if require_review_package_types and Path(basename).suffix.lower() not in REVIEW_PACKAGE_SUFFIXES:
                findings.append(
                    {
                        "kind": "package_whitelist",
                        "source": target.name,
                        "match": normalized,
                        "context": "送审包仅允许 DOCX、PDF、送审说明和文件清单",
                    }
                )
            suffix = Path(basename).suffix.lower()
            if suffix in {".md", ".txt"}:
                audits.append(audit_text(archive.read(name).decode("utf-8", errors="replace"), source=f"{target.name}:{normalized}"))
            elif suffix == ".docx":
                with tempfile.TemporaryDirectory() as temp_dir:
                    extracted = Path(temp_dir) / basename
                    extracted.write_bytes(archive.read(name))
                    audits.append(audit_docx_path(extracted))
    merged = merge_audits(audits, source=str(target))
    merged["findings"] = findings + merged["findings"]
    counts = Counter(item.get("kind") or "unknown" for item in merged["findings"])
    merged["counts"] = {kind: int(counts.get(kind, 0)) for kind, _patterns in RULES}
    merged["counts"]["package_whitelist"] = int(counts.get("package_whitelist", 0))
    merged.update({"ready": not merged["findings"], "path": str(target), "files": names})
    return merged
