from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bid_writer_v2.production.generation_state import read_generation
from bid_writer_v2.utils import content_hash
import test_section_generation_batches as fixtures


class GenerationRepairTest(unittest.TestCase):
    setUp = fixtures.SectionGenerationBatchesTest.setUp
    rows = fixtures.SectionGenerationBatchesTest.rows
    publish_fixture = fixtures.SectionGenerationBatchesTest.publish_fixture
    section = fixtures.SectionGenerationBatchesTest.section
    reply = fixtures.SectionGenerationBatchesTest.reply

    def incomplete(self):
        section_id, ids = self.section(13)
        def transform(payload, requirements):
            if requirements[0]["id"] == ids[-1]:
                payload["evidence"] = []
            return payload
        self.payload_transform = transform
        first = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(first["generation_status"], "incomplete")
        self.payload_transform = None
        self.generate.reset_mock()
        self.knowledge.search.reset_mock()
        return section_id, ids, first

    def repair(self, section_id, first, **kwargs):
        return self.production.generate_section(self.project_id, section_id, repair_only=True,
                                                target_hash=content_hash(first["content"]), **kwargs)

    def test_repair_only_failed_part_preserves_good_bytes_and_creates_version(self):
        section_id, ids, first = self.incomplete()
        before = read_generation(self.rows("project_drafts")[0])
        second = self.repair(section_id, first)
        after = read_generation(self.rows("project_drafts")[-1])
        self.assertEqual(self.generate.call_count, 1)
        self.knowledge.search.assert_not_called()
        self.assertEqual(before["parts"][0]["content"], after["parts"][0]["content"])
        self.assertEqual(before["parts"][0]["evidence"], after["parts"][0]["evidence"])
        self.assertTrue(after["parts"][0]["reused"])
        self.assertFalse(after["parts"][1]["reused"])
        self.assertEqual(second["generation_status"], "ai")
        self.assertEqual(second["version_no"], 2)
        self.assertEqual(self.rows("project_drafts")[0]["content"], first["content"])
        self.assertFalse(second["generation"]["can_repair"])
        current_responses = [row for row in self.rows("requirement_responses") if row["draft_id"] == second["draft_id"]]
        self.assertEqual({row["requirement_id"] for row in current_responses}, set(ids))
        self.assertTrue(all(row["review_status"] != "confirmed" for row in current_responses))

    def test_edited_body_cannot_restore_old_parts(self):
        section_id, _ids, first = self.incomplete()
        self.production.update_draft(first["draft_id"], first["content"] + "\n人工新增措施。")
        with self.assertRaisesRegex(ValueError, "版本已变化"):
            self.repair(section_id, first)
        self.generate.assert_not_called()

    def test_changed_project_and_mapping_cannot_reuse_snapshot(self):
        section_id, _ids, first = self.incomplete()
        self.production.update_project(self.project_id, {"profile": {"duration_days": 850}})
        with self.assertRaisesRegex(ValueError, "资料、条款"):
            self.repair(section_id, first)
        self.generate.assert_not_called()

    def test_retired_source_rejected_before_model_call(self):
        section_id, _ids, first = self.incomplete()
        with self.db.connect() as conn:
            conn.execute("UPDATE knowledge_publications SET status='retired'")
        with self.assertRaisesRegex(ValueError, "知识版本已失效"):
            self.repair(section_id, first)
        self.generate.assert_not_called()

    def test_concurrent_manual_edit_wins_over_generation(self):
        section_id, _ids, first = self.incomplete()
        edited = first["content"] + "\n人工新增措施。"
        self.before_call = lambda: self.production.update_draft(first["draft_id"], edited)
        with self.assertRaisesRegex(ValueError, "未覆盖"):
            self.repair(section_id, first)
        self.assertEqual(len(self.rows("project_drafts")), 1)
        self.assertEqual(self.rows("project_drafts")[0]["content"], edited)

    def test_cancelled_repair_keeps_only_original_version(self):
        section_id, _ids, first = self.incomplete()
        state = {"cancelled": False}
        self.before_call = lambda: state.update(cancelled=True)
        result = self.repair(section_id, first, cancelled=lambda: state["cancelled"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(self.rows("project_drafts")), 1)
        self.assertEqual(self.rows("project_drafts")[0]["content"], first["content"])

    def test_cancellation_while_waiting_for_save_lock_does_not_save(self):
        section_id, _ids, first = self.incomplete()
        state = {"cancelled": False}
        original_lock = self.production._lock_project_for_update
        def lock_then_cancel(conn, project_id):
            original_lock(conn, project_id)
            state["cancelled"] = True
        self.production._lock_project_for_update = lock_then_cancel
        result = self.repair(section_id, first, cancelled=lambda: state["cancelled"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(self.rows("project_drafts")), 1)
        self.assertEqual(self.rows("generation_runs")[-1]["status"], "cancelled")

    def test_failed_part_cannot_be_signed_by_typing_a_resolution(self):
        section_id, _ids, first = self.incomplete()
        with self.assertRaisesRegex(ValueError, "未完成的生成部分"):
            self.production.confirm_draft(first["draft_id"], "实际复核人", target_hash=content_hash(first["content"]),
                                          resolutions=[{"index": index, "resolution": "fixture typed decision"} for index in range(len(first["confirmations"]))])

    def test_failed_retry_remains_repairable_and_not_ai_complete(self):
        section_id, _ids, first = self.incomplete()
        self.generate.side_effect = lambda *_args: {"content": "", "error": "fixture unavailable"}
        result = self.repair(section_id, first)
        self.assertEqual(result["generation_status"], "partial_fallback")
        self.assertTrue(result["generation"]["can_repair"])
        self.assertEqual(result["reused_parts"], 1)

    def test_fallback_requirement_quote_is_not_counted_as_technical_response(self):
        section_id, _ids = self.section(1)
        self.generate.side_effect = lambda *_args: {"content": "", "error": "fixture unavailable"}
        draft = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 0)
        self.production.update_draft(draft["draft_id"], draft["content"] + "\n人工添加一条无关的说明。")
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 0)
        self.assertTrue(all(row["coverage_score"] == 0 for row in self.rows("requirement_responses")))

    def test_remapping_keeps_prose_but_removes_old_response_from_metrics(self):
        section_id, ids = self.section(1)
        first = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 1)
        with self.db.connect() as conn:
            other_id = int(conn.execute("INSERT INTO project_sections(project_id,order_no,title) VALUES (?,2,'新的响应章节')", (self.project_id,)).lastrowid)
        snapshot = self.production.requirements_workflow.snapshot(self.project_id)
        self.production.requirements_workflow.map_requirement(self.project_id, ids[0], "实际复核人", snapshot["items"][0]["requirement_fingerprint"], [other_id])
        self.assertEqual(self.rows("project_drafts")[0]["content"], first["content"])
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 0)

    def test_legacy_fallback_score_one_cannot_count_as_actual_response(self):
        section_id, ids = self.section(1)
        self.generate.side_effect = lambda *_args: {"content": "", "error": "fixture unavailable"}
        first = self.production.generate_section(self.project_id, section_id)
        with self.db.connect() as conn:
            conn.execute("UPDATE requirement_responses SET coverage_score=1 WHERE draft_id=?", (first["draft_id"],))
            conn.execute("UPDATE project_drafts SET generation_json='{}' WHERE id=?", (first["draft_id"],))
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 0)

    def test_ai_copy_of_tender_requirement_is_incomplete(self):
        section_id, ids = self.section(1)
        def copy_request(payload, requirements):
            text = requirements[0]["requirement_key"] + "：" + requirements[0]["content"]
            return {**payload, "content": text, "evidence": [{"requirement_id": ids[0], "text": text}]}
        self.payload_transform = copy_request
        first = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(first["generation_status"], "incomplete")
        self.assertEqual(first["generation_batches"][0]["missing_requirement_ids"], ids)
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 0)

    def test_post_analysis_warning_merge_preserves_human_response_binding(self):
        section_id, ids = self.section(1)
        self.payload_transform = lambda payload, requirements: {**payload, "evidence": []}
        analyze = self.production.evidence.analyze_draft

        def bind_after_analysis(run_id, draft_id, content, sources):
            result = analyze(run_id, draft_id, content, sources)
            item = self.production.requirements_workflow.snapshot(self.project_id)["items"][0]
            quote = f"{item['requirement_key']}响应：施工前组织条件检查，作业过程记录完成情况。"
            self.production.requirements_workflow.bind_response(
                self.project_id, ids[0], draft_id, "实际复核人", content_hash(content),
                item["requirement_fingerprint"], quote)
            return {**result, "unsupported_high": ["分析结束时的旧风险提示"]}

        with patch.object(self.production.evidence, "analyze_draft", side_effect=bind_after_analysis):
            result = self.production.generate_section(self.project_id, section_id)
        draft = self.rows("project_drafts")[0]
        self.assertEqual(read_generation(draft)["status"], "ai")
        self.assertFalse(any("缺少可核验的正文响应" in text for text in json.loads(draft["confirmations_json"])))
        self.assertFalse(any("缺少可核验的正文响应" in text for text in result["confirmations"]))
        self.assertEqual(self.production.workbench(self.project_id)["metrics"]["responded"], 1)

    def test_multi_section_mapping_keeps_each_missing_response_action_visible(self):
        section_id, ids = self.section(1)
        first = self.production.generate_section(self.project_id, section_id)
        with self.db.connect() as conn:
            second_id = int(conn.execute("INSERT INTO project_sections(project_id,order_no,title,requirement_ids_json) VALUES (?,2,'另一技术章节',?)", (self.project_id, json.dumps(ids))).lastrowid)
            other_body = "另一个章节已写其他施工安排，需要定位该条款的实际响应。"
            second_draft = int(conn.execute("INSERT INTO project_drafts(project_id,section_id,content,content_hash) VALUES (?,?,?,?)", (self.project_id, second_id, other_body, content_hash(other_body))).lastrowid)
        self.production.evidence.refresh_project_evidence(self.project_id)
        workbench = self.production.workbench(self.project_id)
        self.assertEqual(workbench["metrics"]["responded"], 1)
        task = next(task for task in workbench["tasks"] if task.get("draft_id") == second_draft and task["kind"] == "response")
        self.assertEqual(task["requirement_id"], ids[0])
        self.assertEqual(task["action"], "locate_response")

    def test_human_response_during_model_call_is_not_overwritten(self):
        section_id, ids, first = self.incomplete()
        def bind_during_model():
            self.before_call = None
            snapshot = self.production.requirements_workflow.snapshot(self.project_id)
            requirement = next(item for item in snapshot["items"] if item["id"] == ids[-1])
            quote = f"{requirement['requirement_key']}响应：施工前组织条件检查，作业过程记录完成情况。"
            self.production.requirements_workflow.bind_response(self.project_id, ids[-1], first["draft_id"],
                "实际复核人", content_hash(first["content"]), requirement["requirement_fingerprint"], quote)
        self.before_call = bind_during_model
        with self.assertRaisesRegex(ValueError, "未覆盖"):
            self.repair(section_id, first)
        self.assertEqual(len(self.rows("project_drafts")), 1)
        self.assertTrue(self.db.row("SELECT id FROM requirement_responses WHERE requirement_id=? AND draft_id=?", (ids[-1], first["draft_id"])))


if __name__ == "__main__":
    unittest.main()
