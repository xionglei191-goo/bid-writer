from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bid_writer_v2.ai_runtime import AiRuntime, KNOWLEDGE_FORMAL_REVIEW_PROMPT
from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.corpus import CorpusCompletionService, FinalizationInterrupted, RECOVERY_CONTRACT, RETIRED_PUBLICATION_REVISION_PROMPT
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.retrieval import HybridRetrievalService
from bid_writer_v2.settings import Settings
from bid_writer_v2.storage import ObjectStorage
from bid_writer_v2.utils import content_hash


class CorpusRetiredRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="retired-recovery-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.settings = Settings(
            workspace_root=root, app_root=root / "app", raw_root=root / "raw", knowledge_root=root / "knowledge",
            delivery_root=root / "delivery", data_root=root / "data", db_path=root / "data" / "test.sqlite3",
            upload_root=root / "uploads", cache_root=root / "cache", export_root=root / "exports", qa_root=root / "qa",
            operations_enabled=False,
        )
        self.settings.ensure_directories()
        self.db = Database(self.settings.db_path)
        self.db.migrate()
        self.runtime = AiRuntime(self.db)
        self.knowledge = KnowledgeService(self.db, self.settings, ai_runtime=self.runtime)
        self.retrieval = HybridRetrievalService(self.db, self.settings, ObjectStorage(self.db, self.settings))
        self.corpus = CorpusCompletionService(self.db, self.knowledge, Mock(), self.retrieval, self.runtime)
        self.addCleanup(patch.stopall)
        patch.object(self.runtime.llm, "generate", side_effect=AssertionError("no real model in this test")).start()
        patch("requests.sessions.Session.request", side_effect=AssertionError("no network in this test")).start()
        patch("httpx.Client.request", side_effect=AssertionError("no network in this test")).start()
        with self.db.connect() as conn:
            self.run_id = int(conn.execute("INSERT INTO corpus_runs(snapshot_hash,status,stage) VALUES ('fixture','running','publication_audit')").lastrowid)
        self.original_body = "施工前复核图纸和现场条件，施工中检查偏差并整改。"
        self.corrected = "施工前复核图纸和现场条件，完成技术交底；施工中检查并记录偏差，整改后组织复验形成闭环。"
        self.corrected_summary = "施工质量管理包括交底、偏差检查和整改复验闭环。"
        self.corrected_applicability = "适用于施工质量过程管理，实施前需复核图纸及现场条件。"
        self.artifact = self.corpus._recovery_artifact(self.corrected, self.corrected_summary, self.corrected_applicability)
        self.responses: dict[str, dict] = {}
        self.calls: list[dict] = []
        patch.object(self.corpus, "_ai_review", side_effect=self.model).start()

    def retired(self, *, risk: str = "medium") -> dict:
        ordinal = int(self.db.row("SELECT COUNT(*) AS count FROM knowledge_units")["count"]) + 1
        with self.db.connect() as conn:
            source_id = int(conn.execute(
                """INSERT INTO source_files(absolute_path,relative_path,file_name,extension,size_bytes,sha256,family_key,status)
                VALUES (?,?,?,'.txt',100,?,?,'processed')""",
                (f"fixture-{ordinal}.txt", f"fixture-{ordinal}.txt", f"fixture-{ordinal}.txt", str(ordinal), str(ordinal)),
            ).lastrowid)
            document_id = int(conn.execute(
                "INSERT INTO standard_documents(source_id,title,markdown_path,parser,char_count,text_fingerprint) VALUES (?,'质量管理','fixture.md','fixture',100,?)",
                (source_id, str(ordinal)),
            ).lastrowid)
            section_id = int(conn.execute(
                "INSERT INTO document_sections(document_id,order_no,level,heading,content,content_fingerprint) VALUES (?,1,1,'质量管理',?,?)",
                (document_id, self.corrected, content_hash(self.corrected)),
            ).lastrowid)
            unit_id = int(conn.execute(
                "INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,risk_level,content_fingerprint) VALUES (?,'management_measure','质量管理',?,?,?,?)",
                (f"unit-{ordinal}", self.original_body, self.original_body, risk, content_hash(self.original_body)),
            ).lastrowid)
            conn.execute("INSERT INTO knowledge_unit_sources(unit_id,section_id,source_id,excerpt) VALUES (?,?,?,?)", (unit_id, section_id, source_id, self.corrected))
            version_id = int(conn.execute(
                "INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,1,?,?,'approved')",
                (unit_id, self.original_body, content_hash(self.original_body)),
            ).lastrowid)
            pipeline_id = int(conn.execute(
                "INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status) VALUES (?,?,?,'completed')",
                (document_id, f"pipeline-{ordinal}", str(ordinal)),
            ).lastrowid)
            candidate_id = int(conn.execute(
                """INSERT INTO knowledge_ai_candidates(pipeline_run_id,document_id,source_id,source_section_id,candidate_index,
                title,unit_type,content,risk_level,source_quote,review_decision,review_confidence,status,unit_id)
                VALUES (?,?,?,?,0,'质量管理','management_measure',?,?,?,'pass',0.99,'accepted',?)""",
                (pipeline_id, document_id, source_id, section_id, self.original_body, risk, self.original_body, unit_id),
            ).lastrowid)
            conn.execute(
                """INSERT INTO corpus_run_items(run_id,source_id,source_hash,item_kind,stage,status,terminal_reason,pipeline_run_id)
                VALUES (?,?,'fixture','text','complete','terminal','knowledge_published',?)""", (self.run_id, source_id, pipeline_id),
            )
        publication = self.knowledge.publish_unit(unit_id, version_id, "fixture AI")
        target = {"id": candidate_id, "unit_id": unit_id}
        self.corpus._decision(self.run_id, target, "published_revalidation", "revise", 0.95,
                              [{"code": "source_omission", "severity": "medium", "message": "遗漏技术交底及整改后的复验闭环"}],
                              publication_binding=self.corpus._publication_review_binding(self.corpus._published_audit_rows(unit_id)[0]))
        self.knowledge.retire_publication(publication["publication_id"], "fixture AI audit")
        self.corpus._decision(self.run_id, target, "published_artifact_audit", "retire", 1.0, ["published_revalidation_failed"])
        return {"candidate_id": candidate_id, "unit_id": unit_id, "publication_id": publication["publication_id"],
                "version_id": version_id, "source_id": source_id, "document_id": document_id,
                "section_id": section_id, "pipeline_id": pipeline_id}

    def model(self, candidate, task_type, formal=False, *, recovery_context=None) -> dict:
        self.calls.append(copy.deepcopy({"candidate": candidate, "task_type": task_type, "formal": formal, "context": recovery_context}))
        if task_type in self.responses:
            return copy.deepcopy(self.responses[task_type])
        if task_type == "retired_publication_revision":
            return {"decision": "revise", "confidence": 0.99, "issues": [], "corrected_content": self.corrected,
                    "corrected_summary": self.corrected_summary, "corrected_applicability": self.corrected_applicability}
        return {"decision": "pass", "confidence": 0.99, "issues": []}

    def candidate(self, target: dict) -> dict:
        return self.db.row("SELECT * FROM knowledge_ai_candidates WHERE id=?", (target["candidate_id"],))

    def active(self, target: dict) -> list[dict]:
        return self.db.rows("SELECT * FROM knowledge_publications WHERE unit_id=? AND status='published'", (target["unit_id"],))

    def test_success_creates_new_version_in_same_unit_preserves_candidates_and_retirement(self) -> None:
        target = self.retired()
        original = self.candidate(target)
        retired_before = self.db.row("SELECT * FROM knowledge_publications WHERE id=?", (target["publication_id"],))
        callback = Mock()
        self.knowledge.on_publication_changed = callback
        result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(len(result["published"]), 1)
        self.assertEqual(result["published"][0]["status"], "pending_revalidation")
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["remaining"], [])
        self.assertEqual(self.candidate(target), original)
        self.assertEqual(self.db.row("SELECT * FROM knowledge_publications WHERE id=?", (target["publication_id"],)), retired_before)
        self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM knowledge_units")["count"], 1)
        new = self.active(target)[0]
        self.assertNotEqual(new["id"], target["publication_id"])
        self.assertNotEqual(new["version_id"], target["version_id"])
        version = self.db.row("SELECT content,summary FROM knowledge_versions WHERE id=?", (new["version_id"],))
        self.assertEqual(version["content"], self.artifact["content"])
        self.assertEqual(version["summary"], self.corrected_summary)
        self.assertIn(self.artifact["content"], Path(new["file_path"]).read_text(encoding="utf-8"))
        for call in self.calls[1:]:
            for key in ("content", "summary", "applicability"):
                self.assertEqual(call["candidate"][key], self.artifact[key])
        self.assertEqual(self.corpus.completion(self.run_id)["formal_eligible"], 1)
        self.assertEqual(self.corpus.completion(self.run_id)["formal_published"], 1)
        self.assertIs(self.knowledge.on_publication_changed, callback)
        callback.assert_not_called()
        again = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(again["scanned"], 0)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 2)
        self.assertEqual(self.calls[0]["context"]["old_publication_id"], target["publication_id"])
        self.assertIn("遗漏技术交底", self.calls[0]["context"]["prior_findings"][0]["message"])
        self.assertNotIn("遗漏技术交底", self.calls[0]["candidate"]["source_quote"])
        self.assertEqual(self.calls[0]["candidate"]["source_quote"], self.corrected)

    def test_invalid_repairs_and_reviews_keep_accepted_denominator_and_open_blocker(self) -> None:
        target = self.retired(risk="low")
        original = self.candidate(target)
        cases = [
            ("retired_publication_revision", {"decision": "revise", "confidence": 0.99, "issues": [], "corrected_content": ""}),
            ("retired_publication_revision", {"decision": "revise", "confidence": 0.99, "issues": [], "corrected_content": self.original_body}),
            ("retired_publication_revision", {"decision": "pass", "confidence": 0.99, "issues": [], "corrected_content": self.corrected}),
            ("retired_publication_post_revision_review", {"decision": "pass", "confidence": 0.92, "issues": []}),
            ("retired_publication_post_revision_review", {"decision": "pass", "confidence": 0.99, "issues": [{"severity": "medium", "message": "需要复核"}]}),
            ("retired_publication_formal_adjudication", {"decision": "reject", "confidence": 0.99, "issues": []}),
        ]
        for task, response in cases:
            with self.subTest(task=task, response=response):
                self.responses = {task: response}
                result = self.corpus._recover_retired_candidates(self.run_id)
                self.assertEqual(len(result["blocked"]), 1)
                self.assertEqual(self.candidate(target), original)
                self.assertEqual(self.active(target), [])
                self.assertEqual(self.corpus.completion(self.run_id)["formal_eligible"], 1)
                self.assertEqual(self.corpus.completion(self.run_id)["formal_published"], 0)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 1)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_exception_tasks WHERE issue_code='retired_publication_recovery' AND status='open'")), 1)

    def test_high_risk_requires_another_independent_review_at_097(self) -> None:
        target = self.retired(risk="high")
        self.responses["retired_publication_second_review"] = {"decision": "pass", "confidence": 0.96, "issues": []}
        result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(result["blocked"][0]["reason"], "high_risk_second_review_not_passed")
        self.assertEqual(self.active(target), [])
        self.assertEqual(len(self.calls), 3)

    def test_same_unit_candidates_are_deduplicated_and_scope_is_bounded(self) -> None:
        first, second = self.retired(), self.retired()
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO knowledge_ai_candidates(pipeline_run_id,document_id,source_id,source_section_id,candidate_index,
                title,unit_type,content,status,unit_id) VALUES (?,?,?,?,1,'共享单元','management_measure',?,'accepted',?)""",
                         (first["pipeline_id"], first["document_id"], first["source_id"], first["section_id"], self.original_body, first["unit_id"]))
        result = self.corpus._recover_retired_candidates(self.run_id, candidate_ids=[first["candidate_id"]], limit=1)
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.active(first)), 1)
        self.assertEqual(self.active(second), [])
        self.assertEqual(len(result["remaining"]), 1)
        self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM knowledge_ai_candidates WHERE status='accepted'")["count"], 3)
        self.assertEqual(self.corpus.completion(self.run_id)["formal_eligible"], 3)
        self.assertEqual(self.corpus.completion(self.run_id)["formal_published"], 2)
        with self.assertRaisesRegex(ValueError, "not accepted in this corpus run"):
            self.corpus._recover_retired_candidates(self.run_id, candidate_ids=[999999])

    def test_missing_source_and_source_changes_during_model_calls_block_publication(self) -> None:
        target = self.retired()
        original = self.candidate(target)
        with self.db.connect() as conn:
            conn.execute("UPDATE document_sections SET content='' WHERE id=?", (target["section_id"],))
        result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertIn("provenance", result["blocked"][0]["reason"])
        self.assertEqual(self.calls, [])
        with self.db.connect() as conn:
            conn.execute("UPDATE document_sections SET content=? WHERE id=?", (self.corrected, target["section_id"]))

        def changing_model(*args, **kwargs):
            response = self.model(*args, **kwargs)
            if args[1] == "retired_publication_formal_adjudication":
                with self.db.connect() as conn:
                    conn.execute("UPDATE document_sections SET content=content || '来源已更新' WHERE id=?", (target["section_id"],))
            return response

        with patch.object(self.corpus, "_ai_review", side_effect=changing_model):
            result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertIn("recovery_input_changed", result["blocked"][0]["reason"])
        self.assertEqual(self.active(target), [])
        self.assertEqual(self.candidate(target), original)

    def test_cancellation_after_model_return_does_not_publish_and_restores_callback(self) -> None:
        target = self.retired()
        requested = False
        callback = Mock()
        self.knowledge.on_publication_changed = callback

        def cancel_after_model(*args, **kwargs):
            nonlocal requested
            requested = True
            return self.model(*args, **kwargs)

        with patch.object(self.corpus, "_ai_review", side_effect=cancel_after_model), self.assertRaises(FinalizationInterrupted):
            self.corpus._recover_retired_candidates(self.run_id, cancelled=lambda: requested)
        self.assertEqual(self.active(target), [])
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 1)
        self.assertIs(self.knowledge.on_publication_changed, callback)

    def test_unpublished_new_version_is_reused_after_publication_interruption(self) -> None:
        target = self.retired()
        original = self.candidate(target)
        with patch.object(self.knowledge, "publish_unit", side_effect=OSError("fixture disk interruption")):
            failed = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(len(failed["blocked"]), 1)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 2)
        recovered = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(len(recovered["published"]), 1)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 2)
        self.assertEqual(self.candidate(target), original)

    def test_mixed_success_and_failure_still_audits_successful_publication(self) -> None:
        first, second = self.retired(), self.retired()

        def mixed_model(candidate, task, **kwargs):
            if task == "retired_publication_revision" and candidate["id"] == second["candidate_id"]:
                return {"decision": "reject", "confidence": 0.99, "issues": []}
            return self.model(candidate, task, **kwargs)

        with patch.object(self.corpus, "_ai_review", side_effect=mixed_model), patch.object(self.retrieval, "build_index") as build:
            result = self.corpus._finalize_run(self.run_id)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(len(self.active(first)), 1)
        self.assertEqual(self.active(second), [])
        new_id = self.active(first)[0]["id"]
        self.assertTrue(any(call["task_type"] == "published_knowledge_revalidation" and call["candidate"]["id"] == new_id for call in self.calls))
        self.assertEqual(result["checkpoint"]["finalization"]["retired_recovery"]["published"][0]["status"], "revalidated")
        build.assert_not_called()

    def test_resume_audits_prior_recovery_version_and_closes_its_open_exception(self) -> None:
        target = self.retired()
        with patch.object(self.knowledge, "publish_unit", side_effect=OSError("publication interrupted")):
            self.corpus._recover_retired_candidates(self.run_id)
        recovered = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(len(recovered["published"]), 1)
        self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM knowledge_exception_tasks WHERE status='open'")["count"], 1)
        # Simulate a crash after publication and before the decision/checkpoint.
        with self.db.connect() as conn:
            conn.execute("DELETE FROM knowledge_review_decisions WHERE decision_stage='retired_recovery_publication'")
        audit = self.corpus._audit_recovery_publications(self.run_id)
        self.assertEqual(audit["revalidated_publication_ids"], [recovered["published"][0]["publication_id"]])
        self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM knowledge_exception_tasks WHERE status='open'")["count"], 0)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 2)
        self.assertEqual(self.corpus._recover_retired_candidates(self.run_id)["scanned"], 0)

    def test_shared_unit_uses_the_same_first_source_as_publication_audit(self) -> None:
        first, other = self.retired(), self.retired()
        with self.db.connect() as conn:
            conn.execute("UPDATE knowledge_ai_candidates SET unit_id=? WHERE id=?", (first["unit_id"], other["candidate_id"]))
            conn.execute("UPDATE document_sections SET content='另一份来源的不同表述。' WHERE id=?", (other["section_id"],))
            conn.execute("INSERT INTO knowledge_unit_sources(unit_id,section_id,source_id,excerpt) VALUES (?,?,?,'另一份来源')", (first["unit_id"], other["section_id"], other["source_id"]))
        recovered = self.corpus._recover_retired_candidates(self.run_id, candidate_ids=[other["candidate_id"]])
        self.assertEqual(recovered["blocked"], [])
        self.assertEqual(self.calls[0]["candidate"]["source_section_id"], first["section_id"])
        self.corpus._audit_recovery_publications(self.run_id)
        self.assertEqual(self.calls[-1]["candidate"]["source_section_id"], first["section_id"])

    def test_same_second_old_failure_cannot_authorize_recovery_of_another_publication(self) -> None:
        target = self.retired()
        with self.db.connect() as conn:
            new_version = int(conn.execute("INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,2,?,?,'approved')",
                                           (target["unit_id"], self.corrected, content_hash(self.corrected))).lastrowid)
        another = self.knowledge.publish_unit(target["unit_id"], new_version, "fixture operator")
        self.knowledge.retire_publication(another["publication_id"], "fixture operator")
        with self.db.connect() as conn:
            conn.execute("UPDATE knowledge_publications SET retired_at='2026-09-08 00:00:00' WHERE unit_id=?", (target["unit_id"],))
            conn.execute("UPDATE knowledge_review_decisions SET created_at='2026-09-08 00:00:00' WHERE unit_id=?", (target["unit_id"],))
        result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(result["blocked"][0]["reason"], "retirement_evidence_not_bound_to_publication")
        self.assertEqual(self.calls, [])

    def test_legacy_failure_requires_the_exact_publication_id_and_body_hash(self) -> None:
        target = self.retired()
        review = self.db.row("SELECT * FROM knowledge_review_decisions WHERE unit_id=? AND decision_stage='published_revalidation'", (target["unit_id"],))
        ai_input = {"payload": {"candidate_id": target["publication_id"], "content_hash": content_hash(self.original_body)}}
        with self.db.connect() as conn:
            ai_id = int(conn.execute(
                "INSERT INTO ai_runs(task_type,prompt_key,prompt_version,prompt_hash,input_hash,cache_key,model,base_url,wire_api,status,input_json) VALUES ('published_knowledge_revalidation','knowledge.formal-review','1',?,'input','cache','fixture','fixture','responses','succeeded',?)",
                (KNOWLEDGE_FORMAL_REVIEW_PROMPT.prompt_hash, json.dumps(ai_input)),
            ).lastrowid)
            findings = [finding for finding in json.loads(review["findings_json"]) if finding.get("code") != "publication_binding"]
            conn.execute("UPDATE knowledge_review_decisions SET findings_json=?,ai_run_id=? WHERE id=?", (json.dumps(findings), ai_id, review["id"]))
        self.assertEqual(self.corpus._retired_recovery_state(target["candidate_id"])["context"]["old_publication_id"], target["publication_id"])
        with self.db.connect() as conn:
            ai_input["payload"]["candidate_id"] = target["publication_id"] + 100
            conn.execute("UPDATE ai_runs SET input_json=? WHERE id=?", (json.dumps(ai_input), ai_id))
        with self.assertRaisesRegex(ValueError, "not_bound"):
            self.corpus._retired_recovery_state(target["candidate_id"])

    def test_pause_during_final_fresh_check_stops_publication(self) -> None:
        target = self.retired()
        fresh = self.corpus._retired_recovery_state
        calls = 0

        def pause_before_return(candidate_id):
            nonlocal calls
            state = fresh(candidate_id)
            calls += 1
            if calls == 3:
                self.corpus.pause(self.run_id, "fixture pause during last fresh check")
            return state

        with patch.object(self.corpus, "_retired_recovery_state", side_effect=pause_before_return), patch.object(self.knowledge, "publish_unit") as publish, self.assertRaises(FinalizationInterrupted):
            self.corpus._recover_retired_candidates(self.run_id)
        publish.assert_not_called()
        self.assertEqual(self.active(target), [])

    def test_new_publication_has_no_synthetic_binding_and_is_revalidated(self) -> None:
        target = self.retired()
        recovered = self.corpus._recover_retired_candidates(self.run_id)
        publication_id = recovered["published"][0]["publication_id"]
        self.assertFalse(self.db.rows("SELECT id FROM knowledge_review_decisions WHERE decision_stage='publication'"))
        audit = self.corpus._audit_active_publications(self.run_id)
        self.assertEqual(audit["reused"], 0)
        self.assertEqual(self.calls[-1]["task_type"], "published_knowledge_revalidation")
        for key in ("content", "summary", "applicability", "source_quote"):
            self.assertEqual(self.calls[-1]["candidate"][key], self.calls[1]["candidate"][key])
        self.assertEqual(self.active(target)[0]["id"], publication_id)
        self.assertEqual(self.corpus._audit_active_publications(self.run_id)["reused"], 1)

    def test_finalization_blocks_before_index_and_evaluation(self) -> None:
        target = self.retired()
        self.responses["retired_publication_revision"] = {"decision": "reject", "confidence": 0.99, "issues": []}
        with patch.object(self.retrieval, "build_index") as build, patch.object(self.corpus, "_build_and_run_evaluation") as evaluate:
            result = self.corpus._finalize_run(self.run_id)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["stage"], "retired_recovery")
        self.assertIn(str(target["candidate_id"]), result["pause_reason"])
        self.assertEqual(result["completion"]["formal_eligible_publication_rate"], 0)
        build.assert_not_called()
        evaluate.assert_not_called()

    def test_failed_new_publication_audit_pauses_without_automatic_repair_loop(self) -> None:
        target = self.retired()
        self.responses["published_knowledge_revalidation"] = {"decision": "reject", "confidence": 0.99, "issues": [{"severity": "medium", "message": "still unsupported"}]}
        with patch.object(self.retrieval, "build_index") as build:
            result = self.corpus._finalize_run(self.run_id)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["stage"], "retired_recovery")
        self.assertEqual(self.active(target), [])
        self.assertEqual(self.candidate(target)["status"], "accepted")
        self.assertEqual(len(self.calls), 4)
        build.assert_not_called()

    def test_recovery_prompt_preserves_source_and_rejects_wrong_response_index(self) -> None:
        target = self.retired()
        candidate = self.candidate(target)
        context = {"prior_findings": [{"message": "遗漏闭环"}], "old_publication_id": target["publication_id"]}
        good = {"candidate_index": 0, "decision": "revise", "confidence": 0.99, "issues": [], "corrected_content": self.corrected}
        with patch.object(self.runtime, "execute", return_value={"payload": {"reviews": [good]}, "run_id": None}) as execute:
            CorpusCompletionService._ai_review(self.corpus, candidate, "retired_publication_revision", formal=True, recovery_context=context)
        call = execute.call_args
        self.assertFalse(call.kwargs["use_cache"])
        self.assertEqual(call.args[0], RETIRED_PUBLICATION_REVISION_PROMPT)
        self.assertNotEqual(call.args[0].prompt_hash, KNOWLEDGE_FORMAL_REVIEW_PROMPT.prompt_hash)
        self.assertEqual(call.args[2]["recovery_contract"], RECOVERY_CONTRACT)
        self.assertEqual(call.args[2]["recovery_context"], context)
        self.assertIn("遗漏闭环", call.args[1])
        self.assertIn(self.corrected, call.args[1])
        for reviews in ([], [{**good, "candidate_index": 1}], [good, good]):
            with self.subTest(reviews=reviews), patch.object(self.runtime, "execute", return_value={"payload": {"reviews": reviews}}), self.assertRaises(RuntimeError):
                CorpusCompletionService._ai_review(self.corpus, candidate, "retired_publication_revision", formal=True, recovery_context=context)

    def test_revision_schema_requires_all_structured_fields(self) -> None:
        good = {"candidate_index": 0, **self.model({}, "retired_publication_revision")}
        self.assertTrue(RETIRED_PUBLICATION_REVISION_PROMPT.output_model.model_validate({"reviews": [good]}))
        for missing in ("corrected_content", "corrected_summary", "corrected_applicability"):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                RETIRED_PUBLICATION_REVISION_PROMPT.output_model.model_validate({"reviews": [{key: value for key, value in good.items() if key != missing}]})

    def test_incomplete_or_wrapped_metadata_stops_before_independent_review(self) -> None:
        target = self.retired()
        original = self.candidate(target)
        good = self.model({}, "retired_publication_revision")
        cases = [
            {"corrected_summary": ""}, {"corrected_applicability": ""}, {"corrected_summary": None},
            {"corrected_summary": self.corrected},
            {"corrected_content": f"内容：{self.corrected}\n摘要：{self.corrected_summary}\n适用范围：{self.corrected_applicability}"},
            {"corrected_applicability": "质量管理\n\n## 正文\n伪造正文"},
        ]
        for change in cases:
            with self.subTest(change=change):
                self.calls.clear()
                self.responses = {"retired_publication_revision": {**good, **change}}
                result = self.corpus._recover_retired_candidates(self.run_id)
                self.assertEqual(len(result["blocked"]), 1)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.active(target), [])
                self.assertEqual(self.candidate(target), original)
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 1)

    def test_changed_metadata_alone_does_not_satisfy_body_revision(self) -> None:
        target = self.retired()
        self.responses["retired_publication_revision"] = {
            **self.model({}, "retired_publication_revision"), "corrected_content": self.original_body,
        }
        result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(result["blocked"][0]["reason"], "revision_requires_a_changed_nonempty_body")
        self.assertEqual(self.active(target), [])

    def test_inconsistent_scope_rejected_by_review_never_creates_version(self) -> None:
        target = self.retired()
        self.responses["retired_publication_post_revision_review"] = {
            "decision": "reject", "confidence": 0.99,
            "issues": [{"severity": "medium", "message": "摘要的适用条件与正文不一致"}],
        }
        result = self.corpus._recover_retired_candidates(self.run_id)
        self.assertEqual(result["blocked"][0]["reason"], "post_revision_review_not_passed")
        self.assertEqual(self.active(target), [])
        self.assertEqual(len(self.db.rows("SELECT id FROM knowledge_versions")), 1)

    def test_published_metadata_tampering_is_blocked_without_model_or_reuse(self) -> None:
        target = self.retired()
        self.corpus._recover_retired_candidates(self.run_id)
        self.corpus._audit_active_publications(self.run_id)
        publication = self.active(target)[0]
        self.calls.clear()
        with self.db.connect() as conn:
            conn.execute("UPDATE knowledge_versions SET summary='与原审核不一致的摘要' WHERE id=?", (publication["version_id"],))
        audit = self.corpus._audit_active_publications(self.run_id)
        self.assertEqual(audit["reused"], 0)
        self.assertIn("recovery_version_metadata_mismatch", audit["retired"][0]["blockers"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.active(target), [])

    def test_recovery_version_without_metadata_does_not_get_default_scope(self) -> None:
        target = self.retired()
        self.corpus._recover_retired_candidates(self.run_id)
        publication = self.active(target)[0]
        with self.db.connect() as conn:
            conn.execute("UPDATE knowledge_versions SET content=?,summary='',content_hash=? WHERE id=?",
                         (self.corrected, content_hash(self.corrected), publication["version_id"]))
            conn.execute("UPDATE knowledge_publications SET content_hash=? WHERE id=?", (content_hash(self.corrected), publication["id"]))
        self.calls.clear()
        row = self.corpus._published_audit_rows(target["unit_id"])[0]
        self.assertEqual(self.corpus._published_review_candidate(row)["applicability"], "")
        audit = self.corpus._audit_active_publications(self.run_id)
        self.assertIn("recovery_version_missing_structured_metadata", audit["retired"][0]["blockers"])
        self.assertEqual(self.calls, [])

    def test_published_prompt_matches_actual_full_metadata_review_input(self) -> None:
        target = self.retired()
        self.corpus._recover_retired_candidates(self.run_id)
        row = self.corpus._published_audit_rows(target["unit_id"])[0]
        candidate = self.corpus._published_review_candidate(row)
        expected = self.corpus._published_review_prompt(row)
        good = {"candidate_index": 0, "decision": "pass", "confidence": 0.99, "issues": [], "corrected_content": ""}
        with patch.object(self.runtime, "execute", return_value={"payload": {"reviews": [good]}}) as execute:
            CorpusCompletionService._ai_review(self.corpus, candidate, "published_knowledge_revalidation", formal=True)
        self.assertEqual(execute.call_args.args[1], expected)
        self.assertNotEqual(execute.call_args.args[0].prompt_hash, KNOWLEDGE_FORMAL_REVIEW_PROMPT.prompt_hash)
        self.assertEqual(candidate["source_quote"], self.corrected)
        self.assertEqual(candidate["summary"], self.corrected_summary)
        self.assertEqual(candidate["applicability"], self.corrected_applicability)
        for reviews in ([{**good, "candidate_index": 1}], [good, good]):
            with self.subTest(reviews=reviews), patch.object(self.runtime, "execute", return_value={"payload": {"reviews": reviews}}), self.assertRaises(RuntimeError):
                CorpusCompletionService._ai_review(self.corpus, candidate, "published_knowledge_revalidation", formal=True)


if __name__ == "__main__":
    unittest.main()
