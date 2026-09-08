from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from bid_writer_v2.production.generation_state import context_fingerprint, read_generation
from bid_writer_v2.utils import content_hash
import test_section_generation_batches as fixtures


class GenerationResponseBindingTest(unittest.TestCase):
    setUp = fixtures.SectionGenerationBatchesTest.setUp
    rows = fixtures.SectionGenerationBatchesTest.rows
    publish_fixture = fixtures.SectionGenerationBatchesTest.publish_fixture
    section = fixtures.SectionGenerationBatchesTest.section
    reply = fixtures.SectionGenerationBatchesTest.reply

    def incomplete(self, count=13, missing_positions=(0, 12), human_confirmation=""):
        section_id, ids = self.section(count)
        missing = {ids[index] for index in missing_positions}

        def transform(payload, requirements):
            payload["evidence"] = [value for value in payload["evidence"] if value["requirement_id"] not in missing]
            if human_confirmation:
                payload["confirmations"] = [human_confirmation]
            return payload

        self.payload_transform = transform
        first = self.production.generate_section(self.project_id, section_id)
        self.payload_transform = None
        self.assertEqual(first["generation_status"], "incomplete")
        return section_id, ids, first

    def quote(self, rid):
        requirement = self.db.row("SELECT requirement_key FROM project_requirements WHERE id=?", (rid,))
        return f"{requirement['requirement_key']}响应：施工前组织条件检查，作业过程记录完成情况。"

    def bind(self, draft_id, rid, quote=None):
        workflow = self.production.requirements_workflow
        requirement = next(value for value in workflow.snapshot(self.project_id)["items"] if value["id"] == rid)
        raw = self.db.row("SELECT * FROM project_drafts WHERE id=?", (draft_id,))
        return workflow.bind_response(self.project_id, rid, draft_id, "实际响应复核人", content_hash(raw["content"]),
                                      requirement["requirement_fingerprint"], quote or self.quote(rid))

    def current_draft(self, section_id):
        return next(section["draft"] for section in self.production.get_project(self.project_id)["sections"] if section["id"] == section_id)

    def test_bound_omission_keeps_prose_and_audit_then_allows_real_signoff(self):
        human = "请确认实际进场人员名单。"
        section_id, ids, first = self.incomplete(1, (0,), human)
        before = self.db.row("SELECT * FROM project_drafts WHERE id=?", (first["draft_id"],))
        before_metadata = read_generation(before)
        claims_before = self.rows("claims")
        calls_before = self.generate.call_count
        self.bind(first["draft_id"], ids[0])
        draft = self.current_draft(section_id)
        after = self.db.row("SELECT * FROM project_drafts WHERE id=?", (first["draft_id"],))
        metadata = read_generation(after)
        self.assertEqual(after["content"], before["content"])
        self.assertEqual(metadata["parts"][0]["content"], before_metadata["parts"][0]["content"])
        self.assertEqual(metadata["parts"][0]["ai_run_id"], before_metadata["parts"][0]["ai_run_id"])
        self.assertEqual(self.generate.call_count, calls_before)
        self.assertEqual(self.rows("claims"), claims_before)
        self.assertEqual(draft["generation"]["status"], "ai")
        self.assertEqual(draft["generation"]["failed_parts"], 0)
        self.assertEqual(draft["missing_response_requirement_ids"], [])
        self.assertEqual(draft["confirmations"], [human])
        self.assertEqual(metadata["parts"][0]["evidence"][0]["manual_review"]["reviewer"], "实际响应复核人")
        self.assertEqual(self.rows("requirement_responses")[0]["review_status"], "pending")
        event = self.db.row("SELECT actor,record_json FROM requirement_workflow_events WHERE event_type='response_bound'")
        binding = json.loads(event["record_json"])["generation_binding"]
        self.assertEqual(event["actor"], "实际响应复核人")
        self.assertEqual(binding["outcome"], "omission_reconciled")
        self.assertNotEqual(binding["generation_before_hash"], binding["generation_after_hash"])
        with self.assertRaisesRegex(ValueError, "待确认事项"):
            self.production.confirm_draft(first["draft_id"], "实际章节签审人", target_hash=content_hash(first["content"]))
        self.production.confirm_draft(first["draft_id"], "实际章节签审人", target_hash=content_hash(first["content"]),
                                      resolutions=[{"index": draft["confirmation_required_indices"][0], "resolution": "已依据实际进场名单核对人员安排"}])
        self.assertEqual(self.current_draft(section_id)["status"], "reviewed")
        self.assertEqual(self.rows("requirement_responses")[0]["review_status"], "confirmed")

    def test_remaining_omission_can_repair_after_human_binding_without_scope_change(self):
        section_id, ids, first = self.incomplete()
        self.bind(first["draft_id"], ids[0])
        raw = self.db.row("SELECT * FROM project_drafts WHERE id=?", (first["draft_id"],))
        metadata = read_generation(raw)
        project = self.production.get_project(self.project_id)
        section = next(section for section in project["sections"] if section["id"] == section_id)
        self.assertEqual(metadata["context_fingerprint"], context_fingerprint(project, section, project["requirements"], metadata["sources"]))
        self.assertEqual([part["status"] for part in metadata["parts"]], ["ai", "ai_incomplete"])
        self.assertTrue(section["draft"]["generation"]["can_repair"])
        self.assertTrue(any(f"要求ID：{ids[-1]}" in text for text in section["draft"]["confirmations"]))
        self.generate.reset_mock()
        repaired = self.production.generate_section(self.project_id, section_id, repair_only=True, target_hash=content_hash(first["content"]))
        after = read_generation(self.db.row("SELECT * FROM project_drafts WHERE id=?", (repaired["draft_id"],)))
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(after["parts"][0]["content"], metadata["parts"][0]["content"])
        self.assertEqual(after["parts"][0]["evidence"], metadata["parts"][0]["evidence"])
        self.assertEqual(after["parts"][0]["evidence"][-1]["manual_review"]["reviewer"], "实际响应复核人")
        self.assertEqual(repaired["generation_status"], "ai")

    def test_binding_never_marks_fallback_part_complete(self):
        section_id, ids = self.section(13)

        def fallback_last(instructions, prompt, tokens):
            requirements = json.loads(prompt.split("本部分条款：", 1)[1].split("\n\n已审核知识：", 1)[0])
            return {"content": "", "error": "fixture unavailable"} if requirements[0]["id"] == ids[-1] else self.reply(instructions, prompt, tokens)

        self.generate.side_effect = fallback_last
        first = self.production.generate_section(self.project_id, section_id)
        self.bind(first["draft_id"], ids[-1], self.quote(ids[0]))
        draft = self.current_draft(section_id)
        metadata = read_generation(self.db.row("SELECT * FROM project_drafts WHERE id=?", (first["draft_id"],)))
        self.assertEqual(metadata["parts"][-1]["status"], "fallback")
        self.assertEqual(draft["generation"]["status"], "partial_fallback")
        self.assertTrue(any("AI编写失败" in text for text in draft["confirmations"]))
        self.assertEqual(draft["missing_response_requirement_ids"], [])
        with self.assertRaisesRegex(ValueError, "未完成的生成部分"):
            self.production.confirm_draft(first["draft_id"], "实际章节签审人", target_hash=content_hash(first["content"]))

    def test_cross_part_binding_stops_partial_repair_but_can_finish_by_hand(self):
        section_id, ids, first = self.incomplete()
        self.bind(first["draft_id"], ids[0], self.quote(ids[-1]))
        draft = self.current_draft(section_id)
        self.assertTrue(draft["generation"]["repair_blocked"])
        self.assertIn("其他分段", draft["generation"]["repair_blocked_reason"])
        self.assertFalse(draft["generation"]["can_repair"])
        self.assertTrue(draft["generation"]["has_snapshot"])
        with self.assertRaises(ValueError):
            self.production.generate_section(self.project_id, section_id, repair_only=True, target_hash=content_hash(first["content"]))
        self.bind(first["draft_id"], ids[-1])
        completed = self.current_draft(section_id)
        self.assertEqual(completed["generation"]["status"], "ai")
        self.assertTrue(completed["generation"]["repair_blocked"])
        self.assertEqual(completed["content"], first["content"])
        self.assertEqual(completed["missing_response_requirement_ids"], [])
        self.production.confirm_draft(first["draft_id"], "实际章节签审人", target_hash=content_hash(first["content"]))
        self.assertEqual(self.current_draft(section_id)["status"], "reviewed")

    def test_stale_scope_allows_response_record_without_upgrading_old_parts(self):
        section_id, ids, first = self.incomplete(1, (0,))
        self.production.update_project(self.project_id, {"source_text": "新增本项目施工安排补充要求。"})
        self.bind(first["draft_id"], ids[0])
        draft = self.current_draft(section_id)
        self.assertEqual(draft["generation"]["status"], "incomplete")
        self.assertTrue(draft["generation"]["repair_blocked"])
        self.assertEqual(draft["missing_response_requirement_ids"], [])
        with self.assertRaisesRegex(ValueError, "重新核验证据"):
            self.production.confirm_draft(first["draft_id"], "实际章节签审人", target_hash=content_hash(first["content"]))

    def test_invalid_snapshot_and_legacy_omission_never_auto_complete(self):
        section_id, ids, first = self.incomplete(1, (0,))
        raw = self.db.row("SELECT * FROM project_drafts WHERE id=?", (first["draft_id"],))
        valid = read_generation(raw)
        invalid = json.loads(json.dumps(valid))
        invalid["parts"][0]["part_hash"] = "corrupted"
        for metadata in (invalid, {}):
            with self.subTest(snapshot=bool(metadata)), self.db.connect() as conn:
                conn.execute("UPDATE project_drafts SET generation_json=? WHERE id=?", (json.dumps(metadata), first["draft_id"]))
            self.bind(first["draft_id"], ids[0])
            draft = self.current_draft(section_id)
            self.assertTrue(any("缺少可核验的正文响应" in text for text in draft["confirmations"]))
            with self.assertRaisesRegex(ValueError, "未完成的生成部分"):
                self.production.confirm_draft(first["draft_id"], "实际章节签审人", target_hash=content_hash(first["content"]))

    def test_failures_after_response_metadata_or_audit_roll_back_every_change(self):
        section_id, ids, first = self.incomplete(1, (0,))
        with self.db.connect() as conn:
            conn.execute("INSERT INTO draft_review_decisions(draft_id,reviewer,target_hash,decision) VALUES (?,?,?,'approved')", (first["draft_id"], "历史章节复核人", content_hash(first["content"])))
            conn.execute("INSERT INTO delivery_manifests(project_id,project_hash,manifest_json,manifest_hash) VALUES (?,'fixture','{}','fixture')", (self.project_id,))

        def state():
            return {table: self.db.rows(f"SELECT * FROM {table}") for table in ("projects", "project_drafts", "requirement_responses", "requirement_classifications", "requirement_workflow_events", "draft_review_decisions", "delivery_manifests")}

        original_connect = self.db.connect
        for prefix in ("INSERT INTO requirement_responses", "UPDATE project_drafts SET generation_json", "INSERT INTO requirement_workflow_events"):
            with self.subTest(prefix=prefix):
                before = state()

                @contextmanager
                def failing_connect():
                    with original_connect() as connection:
                        class Connection:
                            def __getattr__(self, name):
                                return getattr(connection, name)

                            def execute(self, sql, *args):
                                value = connection.execute(sql, *args)
                                if " ".join(sql.split()).startswith(prefix):
                                    raise RuntimeError("injected transaction failure")
                                return value
                        yield Connection()

                with patch.object(self.db, "connect", side_effect=failing_connect):
                    with self.assertRaisesRegex(RuntimeError, "injected transaction failure"):
                        self.bind(first["draft_id"], ids[0])
                self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
