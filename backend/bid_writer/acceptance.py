from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .document_settings import get_document_settings
from .docx_audit import build_preflight_signature, load_docx_audit
from .final_document import build_final_document
from .project_profiles import get_project_profile
from .response_matrix import build_response_matrix
from .source_audit import build_source_audit
from .visual_assets import visual_review_summary
from .workflow import PROFILE_REQUIRED_FIELDS
from .workflow_confirmations import list_workflow_confirmations


def _json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _run_row(row: dict[str, Any]) -> dict[str, Any]:
    row["metrics"] = _json(row.get("metrics_json"), {})
    row["blockers"] = _json(row.get("blockers_json"), [])
    row["exports"] = _json(row.get("exports_json"), {})
    return row


def build_acceptance_status(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    matrix = build_response_matrix(tender_id, conn=conn)
    source = build_source_audit(tender_id, conn=conn)
    visuals = visual_review_summary(tender_id, conn=conn)
    final_document = build_final_document(tender_id, conn=conn)
    confirmations = list_workflow_confirmations(tender_id, conn=conn)["items"]
    profile = get_project_profile(tender_id, conn=conn)
    settings = get_document_settings(tender_id, conn=conn)
    task = row_to_dict(conn.execute("SELECT * FROM production_tasks WHERE tender_id = ?", (tender_id,)).fetchone()) or {}
    drafts = rows_to_dicts(conn.execute("SELECT id, section_title, content, generation_mode, generation_error FROM drafts WHERE tender_id = ?", (tender_id,)).fetchall())
    requirements = rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    blocks = rows_to_dicts(conn.execute("SELECT block_type, COUNT(*) AS count FROM document_blocks WHERE tender_id = ? AND status = 'active' GROUP BY block_type", (tender_id,)).fetchall())
    matrix_summary = matrix.get("summary") or {}
    source_summary = source.get("summary") or {}
    final_summary = final_document.get("summary") or {}
    docx_audit = load_docx_audit(tender_id)
    preflight_signature = build_preflight_signature(tender_id, str(final_summary.get("hash") or ""), conn)
    visual_render = (docx_audit or {}).get("visual_render") or {}
    placeholders = sum(str(row.get("content") or "").count("【待确认") for row in drafts)
    generation_errors = [row for row in drafts if row.get("generation_error") or row.get("generation_mode") != "llm"]
    missing_profile = [field for field in PROFILE_REQUIRED_FIELDS if profile.get(field) in {None, ""}]
    compliance = [row for row in requirements if row.get("response_scope") == "compliance" and int(row.get("applicable", 1))]
    compliance_confirmed = [row for row in compliance if row.get("review_status") == "approved"]
    blockers: list[dict[str, Any]] = []

    def block(key: str, title: str, detail: str, target: str) -> None:
        blockers.append({"key": key, "title": title, "detail": detail, "target": target})

    if missing_profile:
        block("profile", "项目参数未补齐", "仍缺少：" + "、".join(missing_profile), "tender")
    missing_task = [label for field, label in (("customer_name", "客户名称"), ("deadline", "交付期限")) if not task.get(field)]
    if missing_task:
        block("delivery_facts", "交付信息未补齐", "仍缺少：" + "、".join(missing_task), "overview")
    if int(matrix_summary.get("verified_scoring_requirements") or 0) < int(matrix_summary.get("scoring_requirements") or 0):
        block("scoring", "评分点未完全响应", "所有评分点必须具有有效正文证据。", "outline")
    if int(matrix_summary.get("verified_high_requirements") or 0) < int(matrix_summary.get("high_requirements") or 0):
        block("high_requirements", "高优先级要求未完全响应", "高优先级技术要求必须全部验证。", "outline")
    if float(matrix_summary.get("chapter_evidence_rate") or 0) < 0.95:
        block("evidence_rate", "正文证据覆盖不足", f"当前覆盖率为 {float(matrix_summary.get('chapter_evidence_rate') or 0):.1%}，要求不低于95%。", "outline")
    if compliance and len(compliance_confirmed) < len(compliance):
        block("compliance", "合规清单未确认", f"已确认 {len(compliance_confirmed)}/{len(compliance)} 条。", "review")
    if placeholders:
        block("placeholders", "存在待确认字段", f"正文仍有 {placeholders} 个待确认字段。", "editor")
    if generation_errors:
        block("generation", "存在非正式生成章节", f"有 {len(generation_errors)} 个章节未完成大模型生成或二次终审。", "editor")
    if int(source_summary.get("invalid_citations") or 0):
        block("citations", "存在无效来源", f"无效引用 {source_summary.get('invalid_citations')} 条。", "review")
    if int(source_summary.get("old_project_findings") or 0):
        block("old_project", "存在旧项目名称", f"检测到 {source_summary.get('old_project_findings')} 处风险。", "review")
    if not visuals.get("ready"):
        block("visuals", "使用中的视觉素材未全部通过", f"已通过 {visuals.get('approved')}/{visuals.get('total_used')} 项。", "visuals")
    if not docx_audit:
        block("layout", "尚未执行DOCX预检", "请先生成DOCX预检稿并完成结构与版式检查。", "delivery")
    elif docx_audit.get("content_signature") != preflight_signature:
        block("layout", "DOCX预检已失效", "正文已变化，请重新生成DOCX预检稿。", "delivery")
    elif not docx_audit.get("ready"):
        block("layout", "DOCX结构审计未通过", "；".join(docx_audit.get("blockers") or ["存在版式结构问题"]), "delivery")
    elif not visual_render.get("ready"):
        block("layout", "DOCX视觉预检未通过", "请完成Word转PDF逐页检查，清除空白页、越界和异常分页。", "delivery")
    if not settings.get("reviewed_by"):
        block("reviewer", "未登记专业复核人", "正式交付必须由投标人员或技术负责人署名终审。", "delivery")
    if not confirmations.get("review", {}).get("confirmed"):
        block("review_confirmation", "质量审查尚未确认", "完成审查后确认当前内容版本。", "review")
    if final_summary.get("approval_status") != "approved":
        block("final_approval", "整本成稿尚未定稿", "完成整本预览并批准当前内容版本。", "delivery")

    metrics = {
        "requirements": int(matrix_summary.get("requirements") or 0),
        "chapter_requirements": int(matrix_summary.get("chapter_requirements") or 0),
        "scoring_verified": f"{matrix_summary.get('verified_scoring_requirements', 0)}/{matrix_summary.get('scoring_requirements', 0)}",
        "high_verified": f"{matrix_summary.get('verified_high_requirements', 0)}/{matrix_summary.get('high_requirements', 0)}",
        "chapter_evidence_rate": float(matrix_summary.get("chapter_evidence_rate") or 0),
        "compliance_confirmed": f"{len(compliance_confirmed)}/{len(compliance)}",
        "sections": int(final_summary.get("total_sections") or 0),
        "generated_sections": int(final_summary.get("generated_sections") or 0),
        "char_count": int(final_summary.get("char_count") or 0),
        "placeholders": placeholders,
        "valid_citations": int(source_summary.get("valid_citations") or 0),
        "invalid_citations": int(source_summary.get("invalid_citations") or 0),
        "old_project_findings": int(source_summary.get("old_project_findings") or 0),
        "visuals_used": int(visuals.get("total_used") or 0),
        "visuals_approved": int(visuals.get("approved") or 0),
        "document_blocks": {str(row["block_type"]): int(row["count"]) for row in blocks},
        "docx_layout_ready": bool(
            docx_audit
            and docx_audit.get("ready")
            and docx_audit.get("content_signature") == preflight_signature
            and visual_render.get("ready")
        ),
        "docx_layout_metrics": (docx_audit or {}).get("metrics") or {},
        "docx_visual_metrics": visual_render.get("metrics") or {},
    }
    scoring_total = int(matrix_summary.get("scoring_requirements") or 0)
    scoring_verified = int(matrix_summary.get("verified_scoring_requirements") or 0)
    high_total = int(matrix_summary.get("high_requirements") or 0)
    high_verified = int(matrix_summary.get("verified_high_requirements") or 0)
    profile_total = len(PROFILE_REQUIRED_FIELDS)
    profile_ratio = (profile_total - len(missing_profile)) / profile_total if profile_total else 1.0
    visual_ratio = int(visuals.get("approved") or 0) / int(visuals.get("total_used") or 1)
    compliance_ratio = len(compliance_confirmed) / len(compliance) if compliance else 1.0
    score = round(
        25 * metrics["chapter_evidence_rate"]
        + 15 * (scoring_verified / scoring_total if scoring_total else 1.0)
        + 10 * (high_verified / high_total if high_total else 1.0)
        + 10 * (1.0 if not generation_errors else max(0.0, 1 - len(generation_errors) / max(len(drafts), 1)))
        + 10 * (1.0 if not int(source_summary.get("invalid_citations") or 0) and not int(source_summary.get("old_project_findings") or 0) else 0.0)
        + 10 * visual_ratio
        + 5 * profile_ratio
        + 5 * compliance_ratio
        + 5 * (1.0 if not placeholders else max(0.0, 1 - placeholders / max(len(drafts) * 2, 1)))
        + 5 * (1.0 if settings.get("reviewed_by") and confirmations.get("review", {}).get("confirmed") and final_summary.get("approval_status") == "approved" else 0.0)
    )
    signature = hashlib.sha256(
        json.dumps({"metrics": metrics, "final_hash": final_summary.get("hash")}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    result = {
        "tender_id": tender_id,
        "status": "passed" if not blockers and score >= 90 else "needs_work",
        "ready": not blockers and score >= 90,
        "quality_score": score,
        "metrics": metrics,
        "blockers": blockers,
        "visual_review": visuals,
        "content_signature": signature,
        "target_manual_edit_hours": 8,
    }
    if own_conn:
        conn.close()
    return result


def run_acceptance(
    tender_id: int,
    *,
    manual_edit_hours: float | None = None,
    conclusion: str = "",
    exports: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    status = build_acceptance_status(tender_id, conn=conn)
    if manual_edit_hours is not None and manual_edit_hours > 8:
        status["ready"] = False
        status["status"] = "needs_work"
        status["blockers"].append({"key": "manual_edit_hours", "title": "人工精修超时", "detail": f"本次记录 {manual_edit_hours} 小时，目标不超过8小时。", "target": "delivery"})
    with conn:
        cur = conn.execute(
            """
            INSERT INTO acceptance_runs (
                tender_id, run_type, status, quality_score, metrics_json, blockers_json,
                exports_json, manual_edit_hours, conclusion, content_signature
            ) VALUES (?, 'full', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                status["status"],
                status["quality_score"],
                json.dumps(status["metrics"], ensure_ascii=False),
                json.dumps(status["blockers"], ensure_ascii=False),
                json.dumps(exports or {}, ensure_ascii=False),
                manual_edit_hours,
                conclusion,
                status["content_signature"],
            ),
        )
    run = row_to_dict(conn.execute("SELECT * FROM acceptance_runs WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    result = {**status, "run": _run_row(run)}
    if own_conn:
        conn.close()
    return result


def list_acceptance_runs(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = [_run_row(row) for row in rows_to_dicts(conn.execute("SELECT * FROM acceptance_runs WHERE tender_id = ? ORDER BY id DESC", (tender_id,)).fetchall())]
    if own_conn:
        conn.close()
    return rows


def render_acceptance_markdown(status: dict[str, Any]) -> str:
    metrics = status.get("metrics") or {}
    blockers = status.get("blockers") or []
    lines = [
        f"# 项目 {status.get('tender_id')} 正式交付验收报告",
        "",
        f"- 验收状态：{'通过' if status.get('ready') else '需整改'}",
        f"- 质量分：{status.get('quality_score', 0)}",
        f"- 正文证据覆盖率：{float(metrics.get('chapter_evidence_rate') or 0):.1%}",
        f"- 评分点证据：{metrics.get('scoring_verified', '0/0')}",
        f"- 高优先级证据：{metrics.get('high_verified', '0/0')}",
        f"- 合规确认：{metrics.get('compliance_confirmed', '0/0')}",
        f"- 章节：{metrics.get('generated_sections', 0)}/{metrics.get('sections', 0)}",
        f"- 正文字符：{metrics.get('char_count', 0)}",
        f"- 待确认字段：{metrics.get('placeholders', 0)}",
        f"- 视觉素材：{metrics.get('visuals_approved', 0)}/{metrics.get('visuals_used', 0)}",
        "",
        "## 阻断项",
        "",
    ]
    if blockers:
        lines.extend(f"- [{item.get('target', 'review')}] {item.get('title')}：{item.get('detail')}" for item in blockers)
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "当前结果只表示系统门禁状态，正式投标文件仍须由投标人员或技术负责人完成专业终审并署名确认。",
            "",
        ]
    )
    return "\n".join(lines)


def write_acceptance_report(tender_id: int, output_dir: Path, conn: sqlite3.Connection | None = None) -> dict[str, str]:
    status = build_acceptance_status(tender_id, conn=conn)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"project_{tender_id}_acceptance.json"
    markdown_path = output_dir / f"project_{tender_id}_acceptance.md"
    json_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_acceptance_markdown(status), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}
