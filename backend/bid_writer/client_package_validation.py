from __future__ import annotations

import re
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .db import connect, row_to_dict
from .delivery_records import latest_delivery_record


REQUIRED_CLIENT_FILES = (
    "技术标初稿_客户版.docx",
    "技术标初稿_客户版.md",
    "客户发货说明.md",
    "客户文件清单.txt",
    "README.txt",
)

FORBIDDEN_FILE_KEYWORDS = (
    "报价",
    "收款",
    "来源审计",
    "引用来源审计",
    "质量门禁",
    "交付放行",
    "生产流程",
    "生产履历",
    "项目复盘",
    "案例资产",
    "接单评估",
    "渠道运营",
    "生产启动",
    "新单生产",
    "修订任务",
    "最终核对",
    "交付审查",
    "响应覆盖",
    "目录完整性审计",
    "交付包清单核验",
)

FORBIDDEN_CONTENT_PATTERNS = (
    "报价测算",
    "收款记录",
    "来源审计",
    "引用来源审计",
    "质量门禁",
    "交付放行单",
    "生产流程状态",
    "项目生产履历",
    "项目复盘",
    "案例资产",
    "接单评估",
    "渠道运营助手",
    "生产启动包",
    "新单生产向导",
    "修订任务台账",
    "最终核对清单",
    "交付审查报告",
    "交付包清单核验",
    "参考来源摘要",
    "需人工确认",
    "内部交付检查",
    "内部归档",
)


def _file_item(name: str, names: set[str], sizes: dict[str, int]) -> dict[str, Any]:
    exists = name in names
    size = int(sizes.get(name) or 0)
    status = "complete" if exists and size > 0 else ("missing" if not exists else "empty")
    return {"name": name, "exists": exists, "size": size, "status": status}


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return ""
    texts: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            texts.append(node.text)
    return "\n".join(texts)


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _content_text(name: str, data: bytes) -> str:
    if name.lower().endswith(".docx"):
        return _docx_text(data)
    if name.lower().endswith((".md", ".txt")):
        return _decode_text(data)
    return ""


def _scan_content(name: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    normalized = re.sub(r"\s+", "", text)
    for pattern in FORBIDDEN_CONTENT_PATTERNS:
        if pattern in text or pattern in normalized:
            findings.append({"file": name, "pattern": pattern})
    return findings


def validate_client_package_path(
    package_path: str,
    tender_id: int | None = None,
    delivery_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(package_path) if package_path else Path("")
    package_exists = bool(package_path and path.exists() and path.is_file())
    package_size = path.stat().st_size if package_exists else 0
    files: list[dict[str, Any]]
    names: set[str] = set()
    sizes: dict[str, int] = {}
    zip_error = ""
    content_findings: list[dict[str, str]] = []

    if package_exists:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                names = {item.filename for item in infos}
                sizes = {item.filename: int(item.file_size) for item in infos}
                for name in sorted(names):
                    text = _content_text(name, archive.read(name))
                    if text:
                        content_findings.extend(_scan_content(name, text))
        except zipfile.BadZipFile as exc:
            zip_error = f"BadZipFile: {exc}"
        except Exception as exc:  # noqa: BLE001
            zip_error = f"{type(exc).__name__}: {exc}"

    files = [_file_item(name, names, sizes) for name in REQUIRED_CLIENT_FILES]
    missing_files = [item for item in files if item["status"] != "complete"]
    forbidden_files = [
        {"name": name, "keyword": keyword}
        for name in sorted(names)
        for keyword in FORBIDDEN_FILE_KEYWORDS
        if keyword in name
    ]
    extra_files = sorted(names - set(REQUIRED_CLIENT_FILES))

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not package_exists:
        blockers.append({"title": "客户发货包不存在", "detail": package_path or "尚未导出客户发货包"})
    if zip_error:
        blockers.append({"title": "客户发货包无法读取", "detail": zip_error})
    if missing_files:
        blockers.append({"title": "客户文件缺失", "detail": "、".join(item["name"] for item in missing_files)})
    if forbidden_files:
        blockers.append({"title": "疑似内部文件误入客户包", "detail": "、".join(item["name"] for item in forbidden_files[:12])})
    if content_findings:
        blockers.append(
            {
                "title": "客户包内容疑似包含内部信息",
                "detail": "、".join(f"{item['file']}:{item['pattern']}" for item in content_findings[:12]),
            }
        )
    if extra_files:
        warnings.append({"title": "客户包存在额外文件", "detail": "、".join(extra_files[:12])})
    if package_exists and package_size < 1024:
        warnings.append({"title": "客户发货包体积异常偏小", "detail": f"当前大小 {package_size} 字节。"})

    summary = {
        "package_exists": package_exists,
        "package_size": package_size,
        "zip_readable": package_exists and not zip_error,
        "expected_files": len(REQUIRED_CLIENT_FILES),
        "present_files": sum(1 for item in files if item["status"] == "complete"),
        "missing_files": len(missing_files),
        "forbidden_files": len(forbidden_files),
        "content_findings": len(content_findings),
        "extra_files": len(extra_files),
        "readiness": "blocked" if blockers else ("warning" if warnings else "ready"),
    }
    report = {
        "tender_id": tender_id,
        "delivery_record": delivery_record or {},
        "package": {
            "path": str(path) if package_path else "",
            "name": path.name if package_path else "",
            "exists": package_exists,
            "size": package_size,
        },
        "summary": summary,
        "files": files,
        "extra_files": extra_files,
        "forbidden_files": forbidden_files,
        "content_findings": content_findings,
        "blockers": blockers,
        "warnings": warnings,
    }
    report["markdown"] = render_client_package_validation_markdown(report)
    return report


def validate_latest_client_package(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    record = latest_delivery_record(tender_id, conn=conn, package_formats=("client_zip",))
    report = validate_client_package_path(str((record or {}).get("package_path") or ""), tender_id=tender_id, delivery_record=record or {})
    report["tender"] = {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""}
    report["markdown"] = render_client_package_validation_markdown(report)
    if own_conn:
        conn.close()
    return report


def render_client_package_validation_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    package = report.get("package") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 客户发货包安全核验",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or report.get('tender_id') or '未登记'}",
        f"- 客户包：{package.get('name') or '未生成'}",
        f"- 路径：{package.get('path') or '未生成'}",
        f"- 大小：{summary.get('package_size', 0)} 字节",
        "",
        "## 核验概览",
        f"- ZIP 可读取：{'是' if summary.get('zip_readable') else '否'}",
        f"- 文件齐全：{summary.get('present_files', 0)}/{summary.get('expected_files', 0)}",
        f"- 缺失文件：{summary.get('missing_files', 0)}",
        f"- 疑似内部文件：{summary.get('forbidden_files', 0)}",
        f"- 内容风险：{summary.get('content_findings', 0)}",
        f"- 核验状态：{summary.get('readiness')}",
        "",
        "## 阻断项",
    ]
    blockers = report.get("blockers") or []
    if not blockers:
        lines.append("- 暂无阻断项。")
    for item in blockers:
        lines.append(f"- {item.get('title')}：{item.get('detail')}")
    lines.extend(["", "## 提醒项"])
    warnings = report.get("warnings") or []
    if not warnings:
        lines.append("- 暂无提醒项。")
    for item in warnings:
        lines.append(f"- {item.get('title')}：{item.get('detail')}")
    lines.extend(["", "## 客户文件清单"])
    for item in report.get("files") or []:
        lines.append(f"- [{item.get('status')}] {item.get('name')} / {item.get('size', 0)} 字节")
    return "\n".join(lines).strip() + "\n"
