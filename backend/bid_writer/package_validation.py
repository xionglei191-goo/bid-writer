from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict
from .delivery_records import latest_delivery_record


CORE_FILES = (
    "技术标初稿.docx",
    "技术标初稿.md",
    "README.txt",
    "项目总览.md",
    "项目总览.json",
    "项目生产履历.md",
    "项目生产履历.json",
    "目录完整性审计.md",
    "目录完整性审计.json",
    "响应矩阵挂接报告.md",
    "响应矩阵挂接报告.json",
    "响应覆盖报告.json",
    "引用来源审计.md",
    "引用来源审计.json",
    "生产流程状态.json",
    "质量门禁报告.md",
    "质量门禁报告.json",
    "修订任务台账.md",
    "修订任务台账.json",
    "最终核对清单.md",
    "最终核对清单.json",
    "成稿确认报告.md",
    "成稿确认报告.json",
    "交付审查报告.md",
    "交付审查报告.json",
    "交付说明.md",
)

ARCHIVE_FILES = (
    "成稿格式设置.md",
    "成稿格式设置.json",
    "投标单位资料.md",
    "投标单位资料.json",
    "投标响应策略.md",
    "投标响应策略.json",
    "新单生产向导.md",
    "新单生产向导.json",
    "渠道运营助手.md",
    "渠道运营助手.json",
    "生产启动包.md",
    "生产启动包.json",
    "生产任务.json",
    "项目资料.json",
    "接单评估.md",
    "接单评估.json",
    "客户沟通记录.md",
    "客户沟通记录.json",
    "报价测算.md",
    "报价测算.json",
    "收款记录.md",
    "收款记录.json",
    "订单确认单.md",
    "订单确认单.json",
    "资料清单.md",
    "资料清单.json",
    "项目化校正记录.md",
    "项目化校正记录.json",
    "结案确认单.md",
    "结案确认单.json",
    "项目复盘.md",
    "项目复盘.json",
    "案例资产.md",
    "案例资产.json",
)

READINESS_FILES = (
    "项目可交付性评估.md",
    "项目可交付性评估.json",
)

REPORT_FILES = (
    "交付放行单.md",
    "交付放行单.json",
    "交付包清单核验.md",
    "交付包清单核验.json",
)

JSON_FILES = tuple(file for file in (*CORE_FILES, *ARCHIVE_FILES, *READINESS_FILES, *REPORT_FILES) if file.endswith(".json"))


def _file_item(name: str, names: set[str], sizes: dict[str, int], level: str) -> dict[str, Any]:
    exists = name in names
    size = int(sizes.get(name) or 0)
    status = "complete" if exists and size > 0 else ("missing" if not exists else "empty")
    return {
        "name": name,
        "level": level,
        "exists": exists,
        "size": size,
        "status": status,
    }


def _validate_json(archive: zipfile.ZipFile, names: set[str], json_files: tuple[str, ...]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in json_files:
        if name not in names:
            continue
        try:
            json.loads(archive.read(name).decode("utf-8"))
            results.append({"name": name, "valid": True, "error": ""})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "valid": False, "error": f"{type(exc).__name__}: {exc}"})
    return results


def validate_package_path(
    package_path: str,
    tender_id: int | None = None,
    delivery_record: dict[str, Any] | None = None,
    include_readiness: bool = True,
) -> dict[str, Any]:
    path = Path(package_path) if package_path else Path("")
    package_exists = bool(package_path and path.exists() and path.is_file())
    package_size = path.stat().st_size if package_exists else 0
    files: list[dict[str, Any]] = []
    json_checks: list[dict[str, Any]] = []
    zip_error = ""
    names: set[str] = set()
    core_files = (*CORE_FILES, *READINESS_FILES) if include_readiness else CORE_FILES
    expected_json_files = tuple(
        file
        for file in (*core_files, *ARCHIVE_FILES, *REPORT_FILES)
        if file.endswith(".json")
    )

    if package_exists:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                names = {item.filename for item in infos}
                sizes = {item.filename: int(item.file_size) for item in infos}
                files = [
                    *[_file_item(name, names, sizes, "core") for name in core_files],
                    *[_file_item(name, names, sizes, "archive") for name in ARCHIVE_FILES],
                ]
                json_checks = _validate_json(archive, names, expected_json_files)
        except zipfile.BadZipFile as exc:
            zip_error = f"BadZipFile: {exc}"
        except Exception as exc:  # noqa: BLE001
            zip_error = f"{type(exc).__name__}: {exc}"
    else:
        files = [
            *[_file_item(name, set(), {}, "core") for name in core_files],
            *[_file_item(name, set(), {}, "archive") for name in ARCHIVE_FILES],
        ]

    core_missing = [item for item in files if item["level"] == "core" and item["status"] != "complete"]
    archive_missing = [item for item in files if item["level"] == "archive" and item["status"] != "complete"]
    invalid_json = [item for item in json_checks if not item["valid"]]
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not package_exists:
        blockers.append({"title": "交付包文件不存在", "detail": package_path or "尚未导出交付包"})
    if zip_error:
        blockers.append({"title": "ZIP 文件无法读取", "detail": zip_error})
    if core_missing:
        blockers.append({"title": "核心交付文件缺失", "detail": "、".join(item["name"] for item in core_missing[:12])})
    if invalid_json:
        blockers.append({"title": "结构化报告无法解析", "detail": "、".join(item["name"] for item in invalid_json[:12])})
    if archive_missing:
        warnings.append({"title": "辅助归档文件缺失", "detail": "、".join(item["name"] for item in archive_missing[:12])})
    if package_exists and package_size < 1024:
        warnings.append({"title": "交付包体积异常偏小", "detail": f"当前大小 {package_size} 字节。"})

    summary = {
        "package_exists": package_exists,
        "package_size": package_size,
        "zip_readable": package_exists and not zip_error,
        "expected_files": len(files),
        "present_files": sum(1 for item in files if item["status"] == "complete"),
        "core_missing": len(core_missing),
        "archive_missing": len(archive_missing),
        "json_checked": len(json_checks),
        "invalid_json": len(invalid_json),
        "extra_files": max(0, len(names) - len({item["name"] for item in files}) - len(set(REPORT_FILES) & names)),
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
        "json_checks": json_checks,
        "blockers": blockers,
        "warnings": warnings,
    }
    report["markdown"] = render_package_validation_markdown(report)
    return report


def validate_latest_package(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    record = latest_delivery_record(tender_id, conn=conn, package_formats=("zip", "package"))
    report = validate_package_path(str((record or {}).get("package_path") or ""), tender_id=tender_id, delivery_record=record or {})
    report["tender"] = {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""}
    report["markdown"] = render_package_validation_markdown(report)
    if own_conn:
        conn.close()
    return report


def render_package_validation_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    package = report.get("package") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 交付包清单核验报告",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or report.get('tender_id') or '未登记'}",
        f"- 交付包：{package.get('name') or '未生成'}",
        f"- 路径：{package.get('path') or '未生成'}",
        f"- 大小：{summary.get('package_size', 0)} 字节",
        "",
        "## 核验概览",
        f"- ZIP 可读取：{'是' if summary.get('zip_readable') else '否'}",
        f"- 期望文件：{summary.get('expected_files', 0)}",
        f"- 已具备文件：{summary.get('present_files', 0)}",
        f"- 核心缺失：{summary.get('core_missing', 0)}",
        f"- 辅助缺失：{summary.get('archive_missing', 0)}",
        f"- JSON 校验：{summary.get('json_checked', 0)} 项，异常 {summary.get('invalid_json', 0)} 项",
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
    lines.extend(["", "## 文件清单"])
    for item in report.get("files") or []:
        lines.append(f"- [{item.get('status')}] {item.get('level')} / {item.get('name')} / {item.get('size', 0)} 字节")
    return "\n".join(lines).strip() + "\n"
