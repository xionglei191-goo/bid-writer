from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bid_writer_v2.database import Database, postgres_migration_statements
from bid_writer_v2.production.requirements_api import build_router
from bid_writer_v2.production.requirements_workflow import RequirementsWorkflow, suggest_classification
from bid_writer_v2.production.service import ProductionService
from bid_writer_v2.settings import Settings
from bid_writer_v2.utils import content_hash


class RequirementWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="requirement-workflow-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        settings = Settings(workspace_root=root, app_root=root / "app", raw_root=root / "raw", knowledge_root=root / "knowledge",
                            delivery_root=root / "delivery", data_root=root / "data", db_path=root / "data" / "fixture.sqlite3",
                            upload_root=root / "uploads", cache_root=root / "cache", export_root=root / "exports", qa_root=root / "qa",
                            operations_enabled=False)
        settings.ensure_directories()
        self.db = Database(settings.db_path)
        self.db.migrate()
        self.production = ProductionService(self.db, settings, Mock(), llm=Mock(), storage=Mock(), audit=Mock())
        self.workflow = RequirementsWorkflow(self.production)
        self.source = "[第27页]\n水性漆的应用方案（3分）：水性漆的应用方案合理、可行\n[第44页]\n承包人提交的竣工资料必须及时、真实、准确、完整。"
        self.project_id = self.production.create_project({"name": "医院门诊综合楼", "industry": "医院", "source_text": self.source})["id"]
        self.api = FastAPI()
        self.api.include_router(build_router(self.workflow))
        self.client = TestClient(self.api)
        self.addCleanup(self.client.close)

    def requirement(self, content: str, kind: str = "technical", page: int = 27, priority: str = "high", project_id: int | None = None) -> int:
        project_id = project_id or self.project_id
        with self.db.connect() as conn:
            index = int(conn.execute("SELECT COUNT(*) FROM project_requirements WHERE project_id=?", (project_id,)).fetchone()[0]) + 1
            return int(conn.execute("INSERT INTO project_requirements(project_id,requirement_key,kind,content,priority,source_page) VALUES (?,?,?,?,?,?)",
                                    (project_id, f"REQ-{index:04d}", kind, content, priority, page)).lastrowid)

    def section(self, requirement_ids: list[int], title: str = "主要施工方案与技术措施", project_id: int | None = None) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("INSERT INTO project_sections(project_id,order_no,title,requirement_ids_json) VALUES (?,1,?,?)",
                                    (project_id or self.project_id, title, json.dumps(requirement_ids))).lastrowid)

    def item(self, requirement_id: int) -> dict:
        return next(item for item in self.workflow.snapshot(self.project_id)["items"] if item["id"] == requirement_id)

    def reviewed_item(self, requirement_id: int, category: str, **fields) -> dict:
        return {"requirement_id": requirement_id, "expected_fingerprint": self.item(requirement_id)["requirement_fingerprint"],
                "category": category, "reason": "人工核对原条款内容及适用范围", **fields}

    def draft(self, section_id: int, content: str = "施工前组织材料条件检查，完成后整理竣工资料并留存交接记录。", version: int = 1) -> int:
        with self.db.connect() as conn:
            draft_id = int(conn.execute("INSERT INTO project_drafts(project_id,section_id,content,content_hash,evidence_status,version_no) VALUES (?,?,?,?,'not_applicable',?)",
                                        (self.project_id, section_id, content, content_hash(content), version)).lastrowid)
        run_id = self.production.evidence.create_generation_run(self.project_id, section_id, content_hash(content), "fixture", "1", "1", None, [])
        self.production.evidence.analyze_draft(run_id, draft_id, content, [])
        return draft_id

    def test_rule_proposals_preserve_technical_scoring_and_veto_ambiguity(self) -> None:
        cases = [
            ("水性漆的应用方案（3分）：水性漆的应用方案合理、可行", "scoring", "technical"),
            ("承包人提交的竣工资料必须及时、真实、准确、完整。", "veto", "technical"),
            ("评标委员会将否决未提交水性漆施工方案的投标文件。", "veto", "technical"),
            ("投标人须提交营业执照及投标资格证明。", "qualification", "qualification"),
            ("投标人须提供有效安全生产许可证。", "qualification", "qualification"),
            ("投标人须提交混凝土工程的类似项目业绩证明。", "qualification", "unclassified"),
            ("投标人的投标报价不得超过招标控制价。", "veto", "commercial"),
            ("分包前必须经发包人、监理人审定并书面同意后方可分包。", "veto", "contract"),
            ("评分分值计算保留小数点后两位，小数点后第三位四舍五入。", "scoring", "reference"),
            ("2.2.4 评分标准", "scoring", "reference"),
            ("未按本项规定实施的应当否决其投标。", "veto", "unclassified"),
        ]
        for text, kind, expected in cases:
            with self.subTest(text=text):
                suggested = suggest_classification({"content": text, "kind": kind, "source_page": 27})
                self.assertEqual(suggested["suggested_category"], expected)
                self.assertEqual(suggested["suggestion_excerpt"], text)
                self.assertEqual(suggested["source_page"], 27)
                self.assertTrue(suggested["suggestion_reason"])

    def test_suggestions_do_not_approve_or_reduce_formal_denominator(self) -> None:
        technical = self.requirement("水性漆施工方案应明确工艺及材料检查方法。", "scoring")
        commercial = self.requirement("投标人的投标报价不得超过招标控制价。", "veto")
        uncertain = self.requirement("未按本项规定实施的应当否决其投标。", "veto")
        snapshot = self.workflow.snapshot(self.project_id)
        self.assertEqual(self.db.rows("SELECT * FROM requirement_classifications"), [])
        self.assertEqual(snapshot["metrics"]["formal_technical_ids"], [technical, commercial, uncertain])
        self.assertEqual(snapshot["metrics"]["scope_pending_ids"], [commercial, uncertain])
        self.assertEqual(snapshot["metrics"]["classification_unreviewed"], 3)
        refreshed = self.workflow.refresh_suggestions(self.project_id)
        self.assertEqual(refreshed["metrics"]["formal_technical_total"], 3)
        self.assertTrue(all(item["classification"]["status"] == "pending" for item in refreshed["items"]))
        self.assertTrue(all(row["reviewer"] == "" for row in self.db.rows("SELECT * FROM requirement_classifications")))
        count = len(self.db.rows("SELECT * FROM requirement_workflow_events"))
        self.workflow.refresh_suggestions(self.project_id)
        self.assertEqual(len(self.db.rows("SELECT * FROM requirement_workflow_events")), count)

    def test_non_technical_confirmation_requires_separate_response_and_basis(self) -> None:
        rid = self.requirement("投标人须提交营业执照及投标资格证明。", "qualification")
        original = self.db.row("SELECT * FROM project_requirements WHERE id=?", (rid,))
        first = self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "qualification")])
        self.assertEqual(first["metrics"]["formal_technical_total"], 0)
        self.assertEqual(first["metrics"]["classification_pending"], 0)
        self.assertEqual(first["metrics"]["checklist_pending_ids"], [rid])
        self.assertIn("requirement_checklists", {item["key"] for item in first["blockers"]})
        with self.assertRaisesRegex(ValueError, "实际响应"):
            self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "qualification", response_text="全部符合要求", basis_text="默认符合")])
        complete = self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "qualification",
            response_text="已在资格资料册提交有效营业执照复印件", basis_text="资格资料册第二页营业执照及第三页资质证明")])
        self.assertEqual(complete["metrics"]["checklist_pending"], 0)
        self.assertEqual(complete["items"][0]["classification"]["response_status"], "responded")
        self.assertEqual(self.db.row("SELECT * FROM project_requirements WHERE id=?", (rid,)), original)

    def test_not_applicable_requires_human_reviewer_and_actual_basis(self) -> None:
        rid = self.requirement("联合体各方不得再以自己名义单独参与同一项目投标。", "veto")
        with self.assertRaisesRegex(ValueError, "实际分类复核人"):
            self.workflow.review(self.project_id, "  ", [self.reviewed_item(rid, "qualification")])
        with self.assertRaisesRegex(ValueError, "不适用也必须"):
            self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "qualification", applicability="not_applicable")])
        result = self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "qualification", applicability="not_applicable",
            basis_text="本项目投标主体为单一法人，投标登记表第五页可核查")])
        self.assertEqual(result["items"][0]["classification"]["response_status"], "not_applicable")
        self.assertEqual(result["metrics"]["checklist_pending"], 0)

    def test_reference_originals_remain_visible_after_explicit_scope_review(self) -> None:
        rid = self.requirement("2.2.4 评分标准", "scoring", page=27)
        before = self.workflow.snapshot(self.project_id)
        self.assertEqual(before["metrics"]["formal_technical_total"], 1)
        result = self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "reference", reason="本行仅为评分表标题，具体评分条款另行保留响应")])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["content"], "2.2.4 评分标准")
        self.assertEqual(result["items"][0]["source_page"], 27)
        self.assertEqual(result["metrics"]["formal_technical_total"], 0)

    def test_stale_source_and_review_revision_reject_replayed_confirmation(self) -> None:
        rid = self.requirement("投标人的投标报价不得超过招标控制价。", "veto")
        payload = self.reviewed_item(rid, "commercial")
        self.workflow.review(self.project_id, "陈工", [payload])
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.workflow.review(self.project_id, "陈工", [payload])
        current_payload = self.reviewed_item(rid, "commercial")
        self.production.update_project(self.project_id, {"source_text": self.source + "\n新增正式补遗要求。"})
        state = self.item(rid)
        self.assertEqual(state["classification"]["status"], "stale")
        self.assertTrue(state["formal_technical"])
        self.assertEqual(self.workflow.snapshot(self.project_id)["metrics"]["scope_pending_ids"], [rid])
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.workflow.review(self.project_id, "陈工", [current_payload])
        self.assertEqual(len(self.db.rows("SELECT * FROM requirement_workflow_events")), 1)

    def test_stale_manual_technical_review_still_blocks_scope_after_source_change(self) -> None:
        rid = self.requirement("水性漆施工方案应明确工艺及材料检查方法。", "scoring")
        self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "technical")])
        self.production.update_project(self.project_id, {"source_text": self.source + "\n新版招标说明。"})
        self.assertEqual(self.item(rid)["planning_category"], "technical")
        self.assertEqual(self.workflow.snapshot(self.project_id)["metrics"]["scope_pending_ids"], [rid])

    def test_batch_scope_validation_is_atomic_and_rejects_another_project(self) -> None:
        rid = self.requirement("投标人的投标报价不得超过招标控制价。", "veto")
        other = self.production.create_project({"name": "另一项目"})["id"]
        foreign = self.requirement("投标人须提交营业执照。", project_id=other)
        before = self.db.rows("SELECT * FROM requirement_classifications")
        with self.assertRaises(KeyError):
            self.workflow.review(self.project_id, "陈工", [self.reviewed_item(rid, "commercial"),
                {"requirement_id": foreign, "expected_fingerprint": "not-current", "category": "qualification", "reason": "人工核对原条款适用资格"}])
        self.assertEqual(self.db.rows("SELECT * FROM requirement_classifications"), before)
        self.assertEqual(self.db.rows("SELECT * FROM requirement_workflow_events"), [])

    def test_expected_project_hash_rejects_concurrent_project_fact_update(self) -> None:
        rid = self.requirement("投标人须提交营业执照。", "qualification")
        current = self.workflow.snapshot(self.project_id)
        payload = self.reviewed_item(rid, "qualification")
        self.production.update_project(self.project_id, {"region": "新地区"})
        with self.assertRaisesRegex(ValueError, "项目内容已变化"):
            self.workflow.review(self.project_id, "陈工", [payload], current["project_hash"])
        self.assertEqual(self.db.rows("SELECT * FROM requirement_classifications"), [])

    def test_mapping_keeps_body_and_invalidates_related_signoffs_and_deliveries(self) -> None:
        rid = self.requirement("水性漆施工方案应明确工艺及材料检查方法。", "scoring")
        first = self.section([rid])
        second = self.section([], "质量保证体系与措施")
        draft_id = self.draft(first)
        body = self.db.row("SELECT content FROM project_drafts WHERE id=?", (draft_id,))["content"]
        self.workflow.bind_response(self.project_id, rid, draft_id, "陈工", content_hash(body), self.item(rid)["requirement_fingerprint"], body)
        self.production.confirm_draft(draft_id, "陈工")
        before = self.db.row("SELECT content FROM project_drafts WHERE id=?", (draft_id,))
        with self.db.connect() as conn:
            conn.execute("INSERT INTO delivery_manifests(project_id,project_hash,manifest_json,manifest_hash) VALUES (?,'fixture','{}','fixture-manifest')", (self.project_id,))
        old_fingerprint = self.item(rid)["requirement_fingerprint"]
        self.workflow.map_requirement(self.project_id, rid, "陈工", old_fingerprint, [second])
        self.assertEqual(self.db.row("SELECT content FROM project_drafts WHERE id=?", (draft_id,)), before)
        self.assertEqual(self.item(rid)["section_ids"], [second])
        self.assertEqual(self.db.row("SELECT status FROM project_drafts WHERE id=?", (draft_id,))["status"], "draft")
        self.assertEqual(self.db.row("SELECT decision FROM draft_review_decisions WHERE draft_id=?", (draft_id,))["decision"], "invalidated")
        self.assertEqual(self.db.row("SELECT status FROM delivery_manifests")["status"], "invalidated")
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.workflow.map_requirement(self.project_id, rid, "陈工", old_fingerprint, [first])

    def test_cross_project_section_mapping_is_rejected_without_changes(self) -> None:
        rid = self.requirement("水性漆施工方案应明确工艺及材料检查方法。")
        own = self.section([rid])
        other = self.production.create_project({"name": "另一项目"})["id"]
        foreign = self.section([], project_id=other)
        with self.assertRaises(KeyError):
            self.workflow.map_requirement(self.project_id, rid, "陈工", self.item(rid)["requirement_fingerprint"], [foreign])
        self.assertEqual(self.item(rid)["section_ids"], [own])

    def test_existing_outline_and_body_survive_supplementary_technical_mapping(self) -> None:
        paint = self.requirement("水性漆的应用方案（3分）：水性漆的应用方案合理、可行", "scoring")
        records = self.requirement("承包人提交的竣工资料必须及时、真实、准确、完整。", "deliverable", page=44)
        section_id = self.section([])
        draft_id = self.draft(section_id)
        before = self.db.row("SELECT content FROM project_drafts WHERE id=?", (draft_id,))
        outline = self.production.build_outline(self.project_id)
        by_title = {item["title"]: item for item in outline["sections"]}
        self.assertEqual(by_title["主要施工方案与技术措施"]["id"], section_id)
        self.assertIn(paint, by_title["主要施工方案与技术措施"]["requirement_ids"])
        self.assertIn(records, by_title["质量保证体系与措施"]["requirement_ids"])
        self.assertEqual(self.db.row("SELECT content FROM project_drafts WHERE id=?", (draft_id,)), before)
        self.production.build_outline(self.project_id)
        self.assertEqual(len(self.production.get_project(self.project_id)["sections"]), len(outline["sections"]))

    def test_repeated_parse_keeps_original_ids_and_pages(self) -> None:
        first = self.production.parse_requirements(self.project_id)
        self.assertTrue(first["requirements"])
        originals = self.db.rows("SELECT * FROM project_requirements ORDER BY id")
        second = self.production.parse_requirements(self.project_id)
        self.assertTrue(second["retained_originals"])
        self.assertEqual(self.db.rows("SELECT * FROM project_requirements ORDER BY id"), originals)
        self.assertEqual([item["id"] for item in first["requirements"]], [item["id"] for item in second["requirements"]])

    def test_missing_response_can_be_bound_but_requires_new_chapter_signoff(self) -> None:
        rid = self.requirement("水性漆施工方案应明确工艺及材料检查方法。", "scoring")
        section_id = self.section([rid])
        quote = "水性漆施工前组织材料条件检查，完成后留存工艺交接记录。"
        draft_id = self.draft(section_id, quote)
        with self.assertRaisesRegex(ValueError, "实际正文响应"):
            self.production.confirm_draft(draft_id, "陈工")
        # A historical approval must not survive a newly bound response.
        with self.db.connect() as conn:
            conn.execute("INSERT INTO draft_review_decisions(draft_id,reviewer,target_hash,decision) VALUES (?,?,?,'approved')", (draft_id, "历史复核人", content_hash(quote)))
        result = self.workflow.bind_response(self.project_id, rid, draft_id, "陈工", content_hash(quote), self.item(rid)["requirement_fingerprint"], quote)
        response = self.db.row("SELECT * FROM requirement_responses WHERE requirement_id=? AND draft_id=?", (rid, draft_id))
        self.assertEqual(response["coverage_score"], 1.0)
        self.assertEqual(response["review_status"], "pending")
        self.assertEqual(response["content_fingerprint"], content_hash(quote))
        self.assertEqual(self.db.row("SELECT decision FROM draft_review_decisions WHERE draft_id=?", (draft_id,))["decision"], "invalidated")
        self.assertEqual(result["items"][0]["section_ids"], [section_id])
        self.production.confirm_draft(draft_id, "陈工", target_hash=content_hash(quote))
        self.assertEqual(self.db.row("SELECT review_status FROM requirement_responses WHERE id=?", (response["id"],))["review_status"], "confirmed")

    def test_response_binding_rejects_stale_body_unmapped_and_superseded_drafts(self) -> None:
        rid = self.requirement("水性漆施工方案应明确工艺及材料检查方法。")
        section_id = self.section([rid])
        quote = "水性漆施工前组织材料条件检查，完成后留存工艺交接记录。"
        draft_id = self.draft(section_id, quote)
        fp = self.item(rid)["requirement_fingerprint"]
        with self.assertRaisesRegex(ValueError, "正文已变化"):
            self.workflow.bind_response(self.project_id, rid, draft_id, "陈工", "old-hash", fp, quote)
        with self.assertRaisesRegex(ValueError, "逐字找到"):
            self.workflow.bind_response(self.project_id, rid, draft_id, "陈工", content_hash(quote), fp, "并不存在于草稿中的人工响应文字，不能作为本条证据。")
        self.draft(section_id, quote, version=2)
        with self.assertRaisesRegex(ValueError, "最新章节草稿"):
            self.workflow.bind_response(self.project_id, rid, draft_id, "陈工", content_hash(quote), fp, quote)
        self.assertEqual(self.db.rows("SELECT * FROM requirement_responses"), [])

    def test_binding_a_verbatim_tender_clause_does_not_convert_it_to_a_response(self) -> None:
        text = "水性漆施工方案必须明确应用工艺并提供相应质量检查措施。"
        rid = self.requirement(text, "scoring")
        section_id = self.section([rid])
        quotes = (text, f"REQ-0001：{text}", f"响应措施：{text}", f"{text}按要求落实。")
        body = "# 施工方案\n\n" + "\n".join(quotes)
        draft_id = self.draft(section_id, body)
        for quote in quotes:
            with self.subTest(quote=quote):
                with self.assertRaisesRegex(ValueError, "条款原文不能"):
                    self.workflow.bind_response(self.project_id, rid, draft_id, "陈工", content_hash(body), self.item(rid)["requirement_fingerprint"], quote)
        self.assertEqual(self.db.rows("SELECT * FROM requirement_responses"), [])

    def test_api_preserves_actual_reviewer_and_blocks_author_permission(self) -> None:
        rid = self.requirement("投标人须提交营业执照。", "qualification")
        user = {"roles": ["author"], "display_name": "本地管理员"}
        @self.api.middleware("http")
        async def user_context(request, call_next):
            request.state.user = user
            return await call_next(request)
        payload = {"reviewer": "实际复核人陈工", "items": [self.reviewed_item(rid, "qualification")]}
        # The client has not sent a request yet; Starlette permits adding this
        # isolated test middleware before its application stack is initialized.
        url = f"/api/projects/{self.project_id}/requirements/review"
        denied = self.client.post(url, json=payload)
        self.assertEqual(denied.status_code, 403, denied.text)
        user["roles"] = ["reviewer"]
        accepted = self.client.post(url, json=payload)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["items"][0]["classification"]["reviewer"], "实际复核人陈工")
        stale = self.client.post(url, json=payload)
        self.assertEqual(stale.status_code, 409, stale.text)

    def test_postgres_migration_keeps_audit_records_and_has_no_sqlite_syntax(self) -> None:
        statements = postgres_migration_statements(self.db.migrations_root, through="018_requirement_classification.sql")
        selected = [value for value in statements if value.startswith(("CREATE TABLE requirement_classifications", "CREATE TABLE requirement_workflow_events"))]
        self.assertEqual(len(selected), 2)
        self.assertTrue(all("AUTOINCREMENT" not in value for value in selected))
        self.assertIn("review_source_hash", selected[0])
        self.assertIn("PRIMARY KEY(requirement_id, revision)", selected[1])
        self.assertEqual(self.db.migrate(), [])


if __name__ == "__main__":
    unittest.main()
