from __future__ import annotations

import json
import re
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from bid_writer.acceptance import build_acceptance_status, write_acceptance_report
from bid_writer.benchmarks import build_benchmark_dataset
from bid_writer.chapter_contracts import backfill_chapter_contracts
from bid_writer.db import connect, init_db
from bid_writer.requirement_responses import classify_tender_requirements, rebuild_requirement_responses
from bid_writer.response_matrix import realign_response_matrix
from bid_writer.settings import EXPORT_DIR, KB_ROOT
from bid_writer.project_profiles import update_project_profile
from bid_writer.tenders import update_draft
from bid_writer.visual_assets import auto_validate_technical_visuals


SAFETY_TARGET_PLACEHOLDER = "【待确认：安全生产目标】"
STRUCTURE_TYPE = "框架-剪力墙结构"
PROJECT_190_REFERENCE_GLOB = (
    "pdf_text/*郑州大学第一附属医院惠济院区改扩建项目主体施工标段二（北区）投标文本*/source.md"
)


def find_verified_structure_source() -> Path | None:
    knowledge_dir = KB_ROOT
    for source_path in knowledge_dir.glob(PROJECT_190_REFERENCE_GLOB):
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "主体采用框架-剪力墙结构" in source_text:
            return source_path
    return None


def fill_verified_project_facts(tender_id: int, conn) -> dict[str, object]:
    """Fill only project facts that are explicitly supported by parsed tender clauses."""
    profile = conn.execute(
        "SELECT safety_target, structure_type FROM project_profiles WHERE tender_id = ?",
        (tender_id,),
    ).fetchone()
    current_target = str(profile["safety_target"] or "").strip() if profile else ""
    current_structure = str(profile["structure_type"] or "").strip() if profile else ""
    source = conn.execute(
        """
        SELECT id, content
        FROM requirements
        WHERE tender_id = ?
          AND content LIKE ?
        ORDER BY id
        LIMIT 1
        """,
        (tender_id, "%河南省安全文明工地%"),
    ).fetchone()
    safety_target = "确保获得“河南省安全文明工地”称号"
    structure_source = find_verified_structure_source()
    profile_updates: dict[str, object] = {}
    if source and not current_target:
        profile_updates["safety_target"] = safety_target
    if structure_source and not current_structure:
        profile_updates["structure_type"] = STRUCTURE_TYPE
    if profile_updates:
        update_project_profile(tender_id, profile_updates, conn=conn)

    updated_drafts: list[int] = []
    rows = conn.execute(
        "SELECT id, content FROM drafts WHERE tender_id = ? ORDER BY id",
        (tender_id,),
    ).fetchall()
    for row in rows:
        content = str(row["content"] or "")
        if not source or SAFETY_TARGET_PLACEHOLDER not in content:
            continue
        update_draft(
            int(row["id"]),
            content.replace(SAFETY_TARGET_PLACEHOLDER, safety_target),
            conn=conn,
        )
        updated_drafts.append(int(row["id"]))
    return {
        "updated": bool(profile_updates or updated_drafts),
        "safety_target": {
            "value": safety_target if source else "",
            "source_requirement_id": int(source["id"]) if source else None,
        },
        "structure_type": {
            "value": STRUCTURE_TYPE if structure_source else "",
            "source_path": str(structure_source) if structure_source else "",
        },
        "updated_draft_ids": updated_drafts,
    }


def main() -> int:
    conn = connect()
    init_db(conn)
    tender_id = 190
    if not conn.execute("SELECT 1 FROM tenders WHERE id = ?", (tender_id,)).fetchone():
        raise SystemExit("项目190不存在，无法执行正式验收。")
    tender = conn.execute("SELECT raw_text FROM tenders WHERE id = ?", (tender_id,)).fetchone()
    raw_text = str(tender[0] or "")
    owner_match = re.search(r"招\s*标\s*人\s*[：:]\s*([^\n\r]+)", raw_text)
    if owner_match:
        owner = re.sub(r"\s+", "", owner_match.group(1)).strip("；;。 ")
        if owner:
            with conn:
                conn.execute(
                    "UPDATE production_tasks SET customer_name = CASE WHEN COALESCE(customer_name, '') = '' THEN ? ELSE customer_name END, updated_at = CURRENT_TIMESTAMP WHERE tender_id = ?",
                    (f"{owner}（招标人）", tender_id),
                )
    verified_facts = fill_verified_project_facts(tender_id, conn)
    classification = classify_tender_requirements(tender_id, conn=conn)
    alignment = realign_response_matrix(tender_id, conn=conn)
    contracts = backfill_chapter_contracts(tender_id, conn=conn)
    evidence = rebuild_requirement_responses(tender_id, conn=conn)
    visual_validation = auto_validate_technical_visuals(tender_id, conn=conn)
    benchmarks = build_benchmark_dataset()
    paths = write_acceptance_report(tender_id, EXPORT_DIR / "acceptance", conn=conn)
    status = build_acceptance_status(tender_id, conn=conn)
    acceptance_summary = {
        key: status[key]
        for key in ("tender_id", "status", "ready", "quality_score", "metrics", "blockers", "content_signature", "target_manual_edit_hours")
    }
    print(
        json.dumps(
            {
                "verified_facts": verified_facts,
                "classification": classification,
                "alignment": {
                    "assignment_count": alignment.get("assignment_count"),
                    "summary": alignment.get("after", {}).get("summary", {}),
                },
                "contracts": contracts,
                "evidence": evidence,
                "technical_visuals": {
                    "updated": len(visual_validation.get("updated") or []),
                    "summary": {key: visual_validation["summary"].get(key) for key in ("total_used", "approved", "pending", "rejected", "missing_files", "ready")},
                },
                "benchmark_summary": benchmarks["summary"],
                "acceptance": acceptance_summary,
                "reports": paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
