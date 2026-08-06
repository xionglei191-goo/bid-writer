from __future__ import annotations

import json
import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

test_db = BACKEND_DIR.parent / "data" / "test_formal_delivery.sqlite"
for suffix in ("", "-wal", "-shm"):
    target = Path(str(test_db) + suffix)
    if target.exists():
        target.unlink()
os.environ["BID_WRITER_DB"] = str(test_db)
os.environ["BID_WRITER_DISABLE_USER_ENV"] = "1"
os.environ.pop("OPENAI_API_KEY", None)

from bid_writer.acceptance import build_acceptance_status, list_acceptance_runs, run_acceptance
from bid_writer.chapter_contracts import build_chapter_contract, validate_chapter_contract
from bid_writer.db import connect, init_db
from bid_writer.document_settings import update_document_settings
from bid_writer.document_templates import ensure_default_document_template, list_document_templates
from bid_writer.requirement_responses import (
    classify_tender_requirements,
    list_requirement_responses,
    rebuild_requirement_responses,
    update_requirement_response,
)
from bid_writer.section_templates import template_for
from bid_writer.template_assets import template_asset_catalog
from bid_writer.tenders import create_requirement, create_tender, get_draft, update_draft


conn = connect()
init_db(conn)

tables = {
    row[0]
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('requirements', 'requirement_responses', 'document_templates', 'acceptance_runs')"
    ).fetchall()
}
assert tables == {"requirements", "requirement_responses", "document_templates", "acceptance_runs"}, tables

catalog = template_asset_catalog()
assert catalog["summary"]["industries"] == 5, catalog["summary"]
assert catalog["summary"]["construction_methods"] >= 40, catalog["summary"]
assert catalog["summary"]["table_templates"] >= 15, catalog["summary"]

default_template = ensure_default_document_template(conn=conn)
assert default_template["is_default"], default_template
assert len(list_document_templates(conn=conn)) == 1

tender = create_tender("正式交付能力测试项目", industry="医院", conn=conn)
tender_id = int(tender["id"])
requirements = [
    create_requirement(
        tender_id,
        {
            "kind": "scoring",
            "priority": "high",
            "content": "施工工艺与技术措施（10分），说明混凝土施工工艺、质量检查和安全措施。",
            "source_hint": "评分办法 第12页",
        },
        conn=conn,
    ),
    create_requirement(
        tender_id,
        {
            "kind": "risk",
            "priority": "high",
            "content": "投标文件必须按要求签章，否则否决投标。",
            "source_hint": "投标人须知 第4页",
        },
        conn=conn,
    ),
]
classification = classify_tender_requirements(tender_id, conn=conn)
assert classification["scopes"]["chapter"] == 1, classification
assert classification["scopes"]["compliance"] == 1, classification

contract = build_chapter_contract(
    "施工工艺及主要施工方法",
    {"project_name": "正式交付能力测试项目", "industry": "医院"},
    [requirements[0]],
    template_for("施工工艺及主要施工方法"),
)
content = "\n".join(
    [
        "# 施工工艺及主要施工方法",
        *[f"## {title}\n{title}应结合招标要求实施，并形成检查记录。" for title in contract["required_subsections"]],
        *[f"### {title}\n混凝土施工过程按审批方案执行，关键参数由项目技术负责人复核。" for title in contract["construction_method_structure"]],
    ]
) + ("\n混凝土施工工艺、质量检查和安全措施形成闭环记录。" * 180)
validation = validate_chapter_contract(content, contract)
assert validation["ready_for_review"], validation

with conn:
    draft_id = int(
        conn.execute(
            """
            INSERT INTO drafts (
                tender_id, section_title, requirements_json, content, citations_json,
                review_json, generation_mode, generation_model, generation_error, status
            ) VALUES (?, ?, ?, ?, '[]', ?, 'llm', 'test-model', '', 'draft')
            """,
            (
                tender_id,
                "施工工艺及主要施工方法",
                json.dumps([requirements[0]], ensure_ascii=False),
                content,
                json.dumps(
                    {
                        "findings": [],
                        "chapter_contract": contract,
                        "contract_validation": validation,
                    },
                    ensure_ascii=False,
                ),
            ),
        ).lastrowid
    )
    conn.execute(
        """
        INSERT INTO section_plans (
            tender_id, order_no, section_title, template_name, requirement_ids_json, draft_id
        ) VALUES (?, 1, ?, ?, ?, ?)
        """,
        (
            tender_id,
            "施工工艺及主要施工方法",
            "施工工艺及主要施工方法",
            json.dumps([requirements[0]["id"]]),
            draft_id,
        ),
    )

evidence_result = rebuild_requirement_responses(tender_id, conn=conn)
assert evidence_result["responses"] >= 1, evidence_result
responses = list_requirement_responses(tender_id, conn=conn)
assert responses and responses[0]["coverage_score"] > 0, responses
approved = update_requirement_response(
    int(responses[0]["id"]),
    {"review_status": "approved", "reviewed_by": "测试复核人"},
    conn=conn,
)
assert approved["response_status"] == "verified", approved

loaded = get_draft(draft_id, conn=conn)
assert loaded["chapter_contract"]["section_title"] == "施工工艺及主要施工方法", loaded
assert loaded["contract_validation"]["ready_for_review"], loaded
edited = update_draft(draft_id, content + "\n新增修改内容。", conn=conn)
assert edited["chapter_contract"], edited
stale = list_requirement_responses(tender_id, conn=conn)[0]
assert stale["review_status"] == "stale", stale

settings = update_document_settings(
    tender_id,
    {"template_id": default_template["id"], "reviewed_by": "测试复核人"},
    conn=conn,
)
assert int(settings["template_id"]) == int(default_template["id"]), settings

acceptance = build_acceptance_status(tender_id, conn=conn)
assert not acceptance["ready"], acceptance
assert any(item["key"] == "profile" for item in acceptance["blockers"]), acceptance["blockers"]
recorded = run_acceptance(tender_id, manual_edit_hours=9, conclusion="测试验收", conn=conn)
assert any(item["key"] == "manual_edit_hours" for item in recorded["blockers"]), recorded["blockers"]
assert len(list_acceptance_runs(tender_id, conn=conn)) == 1

conn.close()
print("formal delivery capability ok")
