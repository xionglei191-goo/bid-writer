from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict
from .draft_scope import active_drafts
from .project_profiles import get_project_profile
from .settings import KB_ROOT, PROJECT_ROOT


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _markdown_exists(markdown_path: str) -> bool:
    text = str(markdown_path or "").strip()
    if not text:
        return False
    path = Path(text)
    if path.is_absolute():
        return path.exists()
    candidates: list[Path] = []
    if path.parts and path.parts[0] == KB_ROOT.name:
        candidates.append(PROJECT_ROOT / path)
    candidates.extend([KB_ROOT / path, PROJECT_ROOT / path])
    return any(candidate.exists() for candidate in candidates)


def _indexed_kb_citation(conn: sqlite3.Connection, citation: dict[str, Any]) -> bool:
    chunk_id = citation.get("chunk_id")
    if chunk_id not in ("", None):
        row = conn.execute("SELECT 1 FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row:
            return True
    source_path = str(citation.get("source_path") or "").strip()
    heading = str(citation.get("heading_text") or "").strip()
    if not source_path:
        return False
    if heading:
        row = conn.execute(
            """
            SELECT 1
            FROM chunks
            WHERE source_path = ? AND COALESCE(heading_text, '') = ?
            LIMIT 1
            """,
            (source_path, heading),
        ).fetchone()
        if row:
            return True
    return bool(conn.execute("SELECT 1 FROM documents WHERE source_path = ? LIMIT 1", (source_path,)).fetchone())


def _indexed_case_asset(conn: sqlite3.Connection, citation: dict[str, Any]) -> bool:
    chunk_id = citation.get("chunk_id")
    if chunk_id not in ("", None):
        return bool(conn.execute("SELECT 1 FROM case_assets WHERE id = ?", (chunk_id,)).fetchone())
    source_path = str(citation.get("source_path") or "")
    match = re.match(r"^案例资产/([^/]+)/(.+)$", source_path)
    if not match:
        return False
    return bool(
        conn.execute(
            """
            SELECT 1
            FROM case_assets
            WHERE project_name = ? AND section_title = ?
            LIMIT 1
            """,
            (match.group(1), match.group(2)),
        ).fetchone()
    )


def _citation_status(conn: sqlite3.Connection, citation: dict[str, Any]) -> dict[str, Any]:
    source_type = str(citation.get("source_type") or "kb_chunk")
    markdown_path = str(citation.get("markdown_path") or "")
    if source_type == "case_asset":
        indexed = _indexed_case_asset(conn, citation)
    else:
        indexed = _indexed_kb_citation(conn, citation)
    return {
        "source_type": source_type,
        "source_path": str(citation.get("source_path") or ""),
        "markdown_path": markdown_path,
        "heading_text": str(citation.get("heading_text") or ""),
        "chunk_id": citation.get("chunk_id"),
        "indexed": indexed,
        "markdown_file_exists": _markdown_exists(markdown_path),
    }


def _old_project_candidates(citations: list[dict[str, Any]]) -> set[str]:
    candidates: set[str] = set()
    for citation in citations:
        source = str(citation.get("source_path") or "")
        match = re.match(r"^\d{3}、[^：:]+[：:][^-]+-(.+?)(?:技术标|施工组织设计|$)", source)
        if match:
            name = match.group(1).strip()
            if len(name) > 4:
                candidates.add(name)
    return candidates


def _same_project_name(candidate: str, current: str) -> bool:
    normalize = lambda value: re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value).replace("招标文件定稿", "").replace("招标文件", "")
    left = normalize(candidate)
    right = normalize(current)
    return bool(left and right and (left == right or left in right or right in left))


def build_source_audit(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    drafts = active_drafts(conn, tender_id)
    for draft in drafts:
        draft["char_count"] = len(str(draft.get("content") or ""))

    section_items: list[dict[str, Any]] = []
    source_counter: Counter[str] = Counter()
    source_details: dict[str, dict[str, Any]] = {}
    total_citations = 0
    valid_citations = 0
    invalid_citations = 0
    case_asset_citations = 0
    kb_citations = 0
    old_project_findings = 0

    for draft in drafts:
        raw_citations = [item for item in _json_list(draft.get("citations_json")) if isinstance(item, dict)]
        citation_items = [_citation_status(conn, item) for item in raw_citations]
        citation_counter = Counter(item["source_path"] or "未登记来源" for item in citation_items)
        section_valid = sum(1 for item in citation_items if item["indexed"])
        section_invalid = len(citation_items) - section_valid
        total_citations += len(citation_items)
        valid_citations += section_valid
        invalid_citations += section_invalid
        case_asset_citations += sum(1 for item in citation_items if item["source_type"] == "case_asset")
        kb_citations += sum(1 for item in citation_items if item["source_type"] != "case_asset")
        problems: list[dict[str, str]] = []
        if not citation_items:
            problems.append({"level": "high", "title": "缺少来源引用", "detail": "本章没有历史素材或案例资产引用。"})
        if section_invalid:
            problems.append({"level": "high", "title": "引用索引失效", "detail": f"{section_invalid} 条引用无法在当前知识库或案例资产中定位。"})
        if len(citation_items) >= 4 and citation_counter:
            source, count = citation_counter.most_common(1)[0]
            if count / len(citation_items) >= 0.75:
                problems.append({"level": "medium", "title": "来源过度集中", "detail": f"{count}/{len(citation_items)} 条引用来自同一来源：{source}"})
        content = str(draft.get("content") or "")
        old_names = [
            name
            for name in sorted(_old_project_candidates(citation_items))
            if name in content and not _same_project_name(name, str(profile.get("project_name") or ""))
        ]
        if old_names:
            old_project_findings += len(old_names)
            problems.append({"level": "high", "title": "疑似历史项目名残留", "detail": "、".join(old_names[:5])})

        for item in citation_items:
            key = item["source_path"] or f"{item['source_type']}:{item.get('chunk_id') or 'unknown'}"
            source_counter[key] += 1
            source_details.setdefault(
                key,
                {
                    "source_path": item["source_path"],
                    "markdown_path": item["markdown_path"],
                    "source_type": item["source_type"],
                    "indexed": item["indexed"],
                    "markdown_file_exists": item["markdown_file_exists"],
                    "headings": set(),
                },
            )
            source_details[key]["indexed"] = bool(source_details[key]["indexed"] or item["indexed"])
            source_details[key]["markdown_file_exists"] = bool(source_details[key]["markdown_file_exists"] or item["markdown_file_exists"])
            if item["heading_text"]:
                source_details[key]["headings"].add(item["heading_text"])

        section_items.append(
            {
                "draft_id": draft["id"],
                "section_title": draft["section_title"],
                "status": draft.get("status") or "",
                "generation_mode": draft.get("generation_mode") or "",
                "generation_model": draft.get("generation_model") or "",
                "char_count": int(draft.get("char_count") or 0),
                "citations_count": len(citation_items),
                "valid_citations": section_valid,
                "invalid_citations": section_invalid,
                "unique_sources": len(citation_counter),
                "case_asset_citations": sum(1 for item in citation_items if item["source_type"] == "case_asset"),
                "kb_citations": sum(1 for item in citation_items if item["source_type"] != "case_asset"),
                "problems": problems,
                "citations": citation_items,
            }
        )

    sources = []
    for key, detail in source_details.items():
        source_type = str(detail.get("source_type") or "kb_chunk")
        headings = sorted(detail.pop("headings", set()))
        sources.append(
            {
                **detail,
                "key": key,
                "citations_count": source_counter[key],
                "headings": headings[:12],
            }
        )
    sources.sort(key=lambda item: (int(item.get("citations_count") or 0), str(item.get("source_path") or "")), reverse=True)

    uncited_sections = [item for item in section_items if not item["citations_count"]]
    invalid_sections = [item for item in section_items if item["invalid_citations"]]
    problem_sections = [item for item in section_items if item["problems"]]
    diversity_warning = bool(total_citations >= 4 and len(sources) <= 1)
    summary = {
        "drafts": len(drafts),
        "cited_drafts": len(drafts) - len(uncited_sections),
        "uncited_drafts": len(uncited_sections),
        "total_citations": total_citations,
        "valid_citations": valid_citations,
        "invalid_citations": invalid_citations,
        "unique_sources": len(sources),
        "kb_citations": kb_citations,
        "case_asset_citations": case_asset_citations,
        "sections_with_invalid_citations": len(invalid_sections),
        "sections_with_problems": len(problem_sections),
        "old_project_findings": old_project_findings,
        "source_diversity_warning": diversity_warning,
        "readiness": "needs_work" if uncited_sections or invalid_sections or old_project_findings else ("needs_review" if diversity_warning else "ready"),
    }
    recommendations: list[str] = []
    if uncited_sections:
        recommendations.append(f"{len(uncited_sections)} 个章节缺少引用，建议重新检索历史片段或人工补充来源说明。")
    if invalid_sections:
        recommendations.append(f"{len(invalid_sections)} 个章节存在失效引用，建议重新生成或更新引用来源。")
    if old_project_findings:
        recommendations.append("发现疑似历史项目名残留，请先执行项目化校正后再交付。")
    if diversity_warning:
        recommendations.append("引用来源过于集中，建议增加不同项目或案例资产作为参考。")
    if not recommendations:
        recommendations.append("已生成章节均具备可定位来源，可进入人工内容复核。")

    result = {
        "tender": {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""},
        "summary": summary,
        "sections": section_items,
        "sources": sources,
        "recommendations": recommendations,
    }
    result["markdown"] = render_source_audit_markdown(result)
    if own_conn:
        conn.close()
    return result


def render_source_audit_markdown(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    summary = report.get("summary") or {}
    lines = [
        "# 引用来源审计报告",
        "",
        "## 基本信息",
        f"- 项目名称：{tender.get('name') or '未登记'}",
        f"- 行业：{tender.get('industry') or '未登记'}",
        "",
        "## 审计概览",
        f"- 草稿章节：{summary.get('drafts', 0)}",
        f"- 有引用章节：{summary.get('cited_drafts', 0)}",
        f"- 缺引用章节：{summary.get('uncited_drafts', 0)}",
        f"- 引用总数：{summary.get('total_citations', 0)}",
        f"- 可定位引用：{summary.get('valid_citations', 0)}",
        f"- 失效引用：{summary.get('invalid_citations', 0)}",
        f"- 独立来源：{summary.get('unique_sources', 0)}",
        f"- 案例资产引用：{summary.get('case_asset_citations', 0)}",
        f"- 审计状态：{summary.get('readiness') or '待检查'}",
        "",
        "## 处理建议",
    ]
    lines.extend(f"- {item}" for item in report.get("recommendations") or [])
    lines.extend(["", "## 章节明细"])
    sections = report.get("sections") or []
    if not sections:
        lines.append("- 暂无草稿章节。")
    for section in sections:
        lines.append(
            f"- {section.get('section_title') or '未命名章节'}："
            f"引用 {section.get('citations_count', 0)} 条，"
            f"可定位 {section.get('valid_citations', 0)} 条，"
            f"失效 {section.get('invalid_citations', 0)} 条，"
            f"独立来源 {section.get('unique_sources', 0)} 个。"
        )
        for problem in section.get("problems") or []:
            lines.append(f"  - {problem.get('title')}：{problem.get('detail')}")
    lines.extend(["", "## 高频来源"])
    sources = report.get("sources") or []
    if not sources:
        lines.append("- 暂无引用来源。")
    for source in sources[:30]:
        lines.append(
            f"- {source.get('source_path') or source.get('key') or '未登记来源'}："
            f"{source.get('citations_count', 0)} 次 / {source.get('source_type') or ''} / "
            f"{'已索引' if source.get('indexed') else '未定位'}"
        )
    return "\n".join(lines).strip() + "\n"
