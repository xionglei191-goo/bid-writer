from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .db import connect, row_to_dict
from .draft_scope import active_drafts
from .project_consistency import project_consistency_findings
from .project_profiles import get_project_profile
from .text_utils import keywords
from .chapter_contracts import structured_generation_result, validate_chapter_contract


def _normalized_project_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value).replace("招标文件定稿", "").replace("招标文件", "")


def _same_project_name(candidate: str, current: str) -> bool:
    left = _normalized_project_name(candidate)
    right = _normalized_project_name(current)
    return bool(left and right and (left == right or left in right or right in left))


def review_draft(draft_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone())
    if not draft:
        raise ValueError(f"Draft not found: {draft_id}")
    requirements = json.loads(draft.get("requirements_json") or "[]")
    citations = json.loads(draft.get("citations_json") or "[]")
    content = draft.get("content", "")
    profile = get_project_profile(int(draft["tender_id"]), conn=conn)
    findings: list[dict[str, Any]] = []

    if not citations:
        findings.append({"severity": "high", "type": "citation_missing", "message": "章节没有引用历史来源，建议重新检索或补充引用。"})

    for req in requirements[:30]:
        req_keywords = [term for term in keywords(req.get("content", "")) if len(term) >= 3][:5]
        if req_keywords and not any(term in content for term in req_keywords[:2]):
            findings.append(
                {
                    "severity": "medium",
                    "type": "requirement_coverage",
                    "message": f"可能未充分响应条款：{req.get('content')}",
                }
            )

    vague_terms = ["根据实际情况", "结合实际", "适时", "必要时", "相关要求"]
    for term in vague_terms:
        if content.count(term) >= 3:
            findings.append({"severity": "low", "type": "vague_language", "message": f"'{term}' 出现较多，建议改成可执行措施。"})

    for finding in project_consistency_findings(profile, str(draft.get("section_title") or ""), content):
        findings.append(finding)

    old_project_candidates = set()
    for citation in citations:
        source = citation.get("source_path", "")
        match = re.match(r"^\d{3}、[^：:]+[：:][^-]+-(.+?)(?:技术标|施工组织设计|$)", source)
        if match:
            old_project_candidates.add(match.group(1).strip())
    for project in old_project_candidates:
        if project and len(project) > 4 and project in content and not _same_project_name(project, str(profile.get("project_name") or "")):
            findings.append({"severity": "high", "type": "old_project_name", "message": f"疑似残留历史项目名称：{project}"})

    stored_review = json.loads(draft.get("review_json") or "[]")
    chapter_contract = stored_review.get("chapter_contract") if isinstance(stored_review, dict) else {}
    review_payload = {
        "findings": findings,
        "chapter_contract": chapter_contract or {},
        "contract_validation": validate_chapter_contract(content, chapter_contract or {}),
        "structured_result": structured_generation_result(content, chapter_contract or {}),
    }
    with conn:
        conn.execute(
            "UPDATE drafts SET review_json = ? WHERE id = ?",
            (json.dumps(review_payload, ensure_ascii=False), draft_id),
        )
    if own_conn:
        conn.close()
    return findings


def review_tender(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    drafts = active_drafts(conn, tender_id)
    findings: list[dict[str, Any]] = []
    for draft in drafts:
        for finding in review_draft(int(draft["id"]), conn=conn):
            finding["draft_id"] = draft["id"]
            findings.append(finding)
    if own_conn:
        conn.close()
    return findings
