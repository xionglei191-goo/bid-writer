from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .client_package_validation import validate_latest_client_package
from .db import connect, row_to_dict
from .delivery_review import build_delivery_review
from .final_document import build_final_document
from .package_validation import validate_latest_package, validate_package_path
from .production_readiness import build_production_readiness
from .quality_gate import build_quality_gate
from .source_audit import build_source_audit


def _check(
    key: str,
    title: str,
    status: str,
    detail: str,
    action: str = "",
    severity: str = "medium",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "detail": detail,
        "action": action,
        "severity": severity if status in {"blocked", "warning"} else "info",
    }


def _status_label(status: str) -> str:
    return {
        "complete": "已通过",
        "warning": "需人工确认",
        "blocked": "阻断放行",
    }.get(status, status)


def _release_label(status: str) -> str:
    return {
        "ready": "可放行交付",
        "conditional": "人工确认后放行",
        "blocked": "暂不放行",
    }.get(status, status)


def _dedupe_actions(items: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()
    for item in items:
        action = str(item.get("action") or "").strip()
        if action and action not in seen:
            seen.add(action)
            actions.append(action)
    return actions[:12] or ["执行人工终审，确认项目参数、格式、页码、签章和客户交付边界。"]


def _latest_delivery_record(conn: sqlite3.Connection, tender_id: int) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM delivery_records
            WHERE tender_id = ?
            ORDER BY exported_at DESC, id DESC
            LIMIT 1
            """,
            (tender_id,),
        ).fetchone()
    ) or {}


def build_delivery_release(
    tender_id: int,
    *,
    package_path: str = "",
    production_readiness: dict[str, Any] | None = None,
    package_validation: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")

    readiness = production_readiness or build_production_readiness(tender_id, package_path=package_path, conn=conn)
    delivery = build_delivery_review(tender_id, conn=conn)
    quality = build_quality_gate(tender_id, conn=conn)
    source = build_source_audit(tender_id, conn=conn)
    final_document = build_final_document(tender_id, include_content=False, conn=conn)
    package = package_validation or (
        validate_package_path(package_path, tender_id=tender_id) if package_path else validate_latest_package(tender_id, conn=conn)
    )
    client_package = validate_latest_client_package(tender_id, conn=conn)
    latest_delivery = _latest_delivery_record(conn, tender_id)

    readiness_summary = readiness.get("summary") or {}
    delivery_summary = delivery.get("summary") or {}
    quality_summary = quality.get("summary") or {}
    source_summary = source.get("summary") or {}
    final_summary = final_document.get("summary") or {}
    package_summary = package.get("summary") or {}
    client_package_summary = client_package.get("summary") or {}
    checks: list[dict[str, Any]] = []

    readiness_status = str(readiness_summary.get("readiness") or "")
    if readiness_status == "ready_to_deliver":
        checks.append(
            _check(
                "production_readiness",
                "项目可交付性",
                "complete",
                f"{readiness_summary.get('decision') or '可承诺交付'}，评估分 {readiness_summary.get('score', 0)}。",
            )
        )
    elif readiness_status == "ready_for_final_review":
        checks.append(
            _check(
                "production_readiness",
                "项目可交付性",
                "warning",
                f"{readiness_summary.get('decision') or '可进入终审'}，尚未达到直接交付状态。",
                "完成人工终审、成稿确认和交付边界确认。",
                "medium",
            )
        )
    else:
        checks.append(
            _check(
                "production_readiness",
                "项目可交付性",
                "blocked",
                f"{readiness_summary.get('decision') or '暂不具备交付条件'}，阻断项 {readiness_summary.get('blockers', 0)} 个。",
                "先处理项目可交付性评估中的阻断项。",
                "high",
            )
        )

    delivery_status = str(delivery_summary.get("readiness") or "")
    if delivery_status == "ready":
        checks.append(
            _check(
                "delivery_review",
                "交付审查",
                "complete",
                delivery_summary.get("readiness_label") or "可进入交付终审。",
            )
        )
    elif delivery_status == "needs_review":
        checks.append(
            _check(
                "delivery_review",
                "交付审查",
                "warning",
                delivery_summary.get("readiness_label") or "需要人工复核。",
                "处理交付审查报告中的提醒项后再发送。",
                "medium",
            )
        )
    else:
        checks.append(
            _check(
                "delivery_review",
                "交付审查",
                "blocked",
                delivery_summary.get("readiness_label") or "尚未具备交付条件。",
                "处理交付审查报告中的主要阻碍。",
                "high",
            )
        )

    quality_status = str(quality.get("status") or "")
    if quality_status == "pass":
        checks.append(
            _check(
                "quality_gate",
                "质量门禁",
                "complete",
                f"{quality.get('status_label') or '通过'}，质量分 {quality.get('score', 0)}。",
            )
        )
    elif int(quality_summary.get("high") or 0):
        checks.append(
            _check(
                "quality_gate",
                "质量门禁",
                "blocked",
                f"{quality.get('status_label') or '暂不建议交付'}，高风险任务 {quality_summary.get('high', 0)} 条。",
                "同步修订任务并优先处理高风险问题。",
                "high",
            )
        )
    else:
        checks.append(
            _check(
                "quality_gate",
                "质量门禁",
                "warning",
                f"{quality.get('status_label') or '需要复核'}，修订任务 {quality_summary.get('task_count', 0)} 条。",
                "处理质量门禁中的中低风险任务或人工确认可接受。",
                "medium",
            )
        )

    source_status = str(source_summary.get("readiness") or "")
    if source_status == "ready":
        checks.append(
            _check(
                "source_audit",
                "来源追溯",
                "complete",
                f"引用 {source_summary.get('valid_citations', 0)}/{source_summary.get('total_citations', 0)} 条可定位。",
            )
        )
    elif int(source_summary.get("uncited_drafts") or 0) or int(source_summary.get("invalid_citations") or 0) or int(source_summary.get("old_project_findings") or 0):
        checks.append(
            _check(
                "source_audit",
                "来源追溯",
                "blocked",
                (
                    f"缺引用章节 {source_summary.get('uncited_drafts', 0)} 个，"
                    f"失效引用 {source_summary.get('invalid_citations', 0)} 条，"
                    f"旧项目名风险 {source_summary.get('old_project_findings', 0)} 个。"
                ),
                "补齐来源引用，清理历史项目名残留后再放行。",
                "high",
            )
        )
    else:
        checks.append(
            _check(
                "source_audit",
                "来源追溯",
                "warning",
                "引用来源过于集中或需要人工复核。",
                "人工确认引用来源适配本项目。",
                "medium",
            )
        )

    if final_summary.get("approval_status") == "approved" and final_summary.get("can_approve"):
        checks.append(
            _check(
                "final_document",
                "成稿确认",
                "complete",
                f"已由 {final_document.get('approval', {}).get('approved_by') or '未填写确认人'} 确认。",
            )
        )
    elif final_summary.get("approval_status") == "approved":
        checks.append(
            _check(
                "final_document",
                "成稿确认",
                "blocked",
                "成稿已确认但当前内容或检查状态发生变化，需要重新确认。",
                "重新刷新整本成稿预览，处理风险提示后再次确认定稿。",
                "high",
            )
        )
    else:
        checks.append(
            _check(
                "final_document",
                "成稿确认",
                "blocked",
                f"当前状态 {final_summary.get('approval_status') or 'draft'}，尚未人工定稿。",
                "在整本成稿预览中完成最终核对并点击确认定稿。",
                "high",
            )
        )

    if package_summary.get("zip_readable") and int(package_summary.get("core_missing") or 0) == 0 and int(package_summary.get("invalid_json") or 0) == 0:
        status = "warning" if int(package_summary.get("archive_missing") or 0) else "complete"
        checks.append(
            _check(
                "package_validation",
                "交付包核验",
                status,
                (
                    f"ZIP 可读取，核心文件缺失 {package_summary.get('core_missing', 0)} 项，"
                    f"JSON 异常 {package_summary.get('invalid_json', 0)} 项，辅助缺失 {package_summary.get('archive_missing', 0)} 项。"
                ),
                "补齐辅助归档文件或人工确认不影响本次交付。" if status == "warning" else "",
                "low",
            )
        )
    else:
        checks.append(
            _check(
                "package_validation",
                "交付包核验",
                "blocked",
                (
                    f"ZIP 可读取：{'是' if package_summary.get('zip_readable') else '否'}，"
                    f"核心缺失 {package_summary.get('core_missing', 0)} 项，"
                    f"JSON 异常 {package_summary.get('invalid_json', 0)} 项。"
                ),
                "重新导出 ZIP 交付包并执行清单核验。",
                "high",
            )
        )

    if (
        client_package_summary.get("zip_readable")
        and int(client_package_summary.get("missing_files") or 0) == 0
        and int(client_package_summary.get("forbidden_files") or 0) == 0
        and int(client_package_summary.get("content_findings") or 0) == 0
    ):
        status = "warning" if int(client_package_summary.get("extra_files") or 0) else "complete"
        checks.append(
            _check(
                "client_package_validation",
                "客户发货包安全核验",
                status,
                (
                    f"ZIP 可读取，文件 {client_package_summary.get('present_files', 0)}/{client_package_summary.get('expected_files', 0)}，"
                    f"内部文件 {client_package_summary.get('forbidden_files', 0)} 个，内容风险 {client_package_summary.get('content_findings', 0)} 个。"
                ),
                "人工确认额外文件均可发给客户。" if status == "warning" else "",
                "medium" if status == "warning" else "low",
            )
        )
    else:
        checks.append(
            _check(
                "client_package_validation",
                "客户发货包安全核验",
                "blocked",
                (
                    f"ZIP 可读取：{'是' if client_package_summary.get('zip_readable') else '否'}，"
                    f"缺失文件 {client_package_summary.get('missing_files', 0)} 个，"
                    f"内部文件 {client_package_summary.get('forbidden_files', 0)} 个，"
                    f"内容风险 {client_package_summary.get('content_findings', 0)} 个。"
                ),
                "导出客户发货包并确认其中不包含报价、收款、来源审计、质量门禁、放行单和复盘资料。",
                "high",
            )
        )

    blockers = [item for item in checks if item["status"] == "blocked"]
    warnings = [item for item in checks if item["status"] == "warning"]
    release_status = "blocked" if blockers else ("conditional" if warnings else "ready")
    package_info = package.get("package") or {}
    summary = {
        "release_status": release_status,
        "release_label": _release_label(release_status),
        "score": min(int(readiness_summary.get("score") or 0), int(quality.get("score") or 0)),
        "blockers": len(blockers),
        "warnings": len(warnings),
        "checks": len(checks),
        "generated_sections": readiness_summary.get("generated_sections", final_summary.get("generated_sections", 0)),
        "total_sections": readiness_summary.get("total_sections", final_summary.get("total_sections", 0)),
        "quality_score": quality.get("score", 0),
        "source_readiness": source_status,
        "package_readiness": package_summary.get("readiness"),
        "client_package_readiness": client_package_summary.get("readiness"),
        "package_exists": package_summary.get("package_exists"),
        "client_package_exists": client_package_summary.get("package_exists"),
        "zip_readable": package_summary.get("zip_readable"),
        "client_zip_readable": client_package_summary.get("zip_readable"),
        "approval_status": final_summary.get("approval_status"),
    }
    client_package_info = client_package.get("package") or {}
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or "", "region": tender.get("region") or ""},
        "summary": summary,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": _dedupe_actions([*blockers, *warnings]),
        "artifacts": {
            "package_path": package_info.get("path") or package_path or str(latest_delivery.get("package_path") or ""),
            "package_name": package_info.get("name") or "",
            "package_size": package_summary.get("package_size", package_info.get("size", 0)),
            "client_package_path": client_package_info.get("path") or "",
            "client_package_name": client_package_info.get("name") or "",
            "client_package_size": client_package_summary.get("package_size", client_package_info.get("size", 0)),
            "delivery_record": latest_delivery,
        },
        "snapshots": {
            "production_readiness": readiness_summary,
            "delivery_review": delivery_summary,
            "quality_gate": {"status": quality.get("status"), "status_label": quality.get("status_label"), **quality_summary},
            "source_audit": source_summary,
            "final_document": final_summary,
            "package_validation": package_summary,
            "client_package_validation": client_package_summary,
        },
        "policy": {
            "human_review_required": True,
            "automation_boundary": "放行单只生成交付判断和人工检查清单，不自动发送、自动收款或自动操作闲鱼发货。",
        },
    }
    report["markdown"] = render_delivery_release_markdown(report)
    if own_conn:
        conn.close()
    return report


def render_delivery_release_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    artifacts = report.get("artifacts") or {}
    lines = [
        "# 交付放行单",
        "",
        "## 放行结论",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 项目 ID：{tender.get('id') or '未登记'}",
        f"- 生成时间：{report.get('generated_at') or ''}",
        f"- 放行状态：{summary.get('release_label') or ''}",
        f"- 综合分：{summary.get('score', 0)}",
        f"- 阻断项：{summary.get('blockers', 0)}",
        f"- 提醒项：{summary.get('warnings', 0)}",
        f"- 章节进度：{summary.get('generated_sections', 0)}/{summary.get('total_sections', 0)}",
        f"- 质量分：{summary.get('quality_score', 0)}",
        f"- 内部归档包：{artifacts.get('package_path') or '未生成'}",
        f"- 客户发货包：{artifacts.get('client_package_path') or '未生成'}",
        "",
        "## 放行检查",
    ]
    for item in report.get("checks") or []:
        lines.append(f"- [{_status_label(str(item.get('status') or ''))}] {item.get('title')}：{item.get('detail')}")
        if item.get("action") and item.get("status") != "complete":
            lines.append(f"  - 建议：{item.get('action')}")
    lines.extend(["", "## 下一步动作"])
    for action in report.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.extend(
        [
            "",
            "## 自动化边界",
            f"- {((report.get('policy') or {}).get('automation_boundary') or '')}",
        ]
    )
    return "\n".join(lines).strip() + "\n"
