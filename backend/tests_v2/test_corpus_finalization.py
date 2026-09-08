from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bid_writer_v2.ai_runtime import AiRuntime, KNOWLEDGE_FORMAL_REVIEW_PROMPT
from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.corpus import CorpusCompletionService
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.retrieval import HybridRetrievalService
from bid_writer_v2.settings import Settings
from bid_writer_v2.storage import ObjectStorage
from bid_writer_v2.utils import content_hash


class CorpusFinalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        data = root / "app" / "data"
        self.settings = Settings(
            workspace_root=root, app_root=root / "app", raw_root=root / "raw", knowledge_root=root / "knowledge",
            delivery_root=root / "delivery", data_root=data, db_path=data / "test.sqlite3",
            upload_root=data / "uploads", cache_root=data / "cache", export_root=root / "exports", qa_root=root / "qa",
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
        patch.object(self.runtime.llm, "generate", side_effect=AssertionError("test must not call a model")).start()
        patch("requests.sessions.Session.request", side_effect=AssertionError("test must not access network")).start()
        patch("httpx.Client.request", side_effect=AssertionError("test must not access network")).start()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO source_files(absolute_path,relative_path,file_name,extension,size_bytes,sha256,family_key,status) VALUES ('fixture.dwg','fixture.dwg','fixture.dwg','.dwg',1,'fixture','fixture','metadata_only')"
            )
        self.run_id = self.corpus.create_run()["id"]
        self.dispatches: list[tuple[int, str]] = []

    def dispatch(self, run_id: int, delay: int, desired: int, stage: str) -> None:
        self.dispatches.append((run_id, stage))
        self.job(stage=stage)

    def job(self, *, stage: str = "ai", status: str = "pending", error: str = "") -> int:
        count = len(self.db.rows("SELECT id FROM app_jobs"))
        with self.db.connect() as conn:
            return int(conn.execute(
                "INSERT INTO app_jobs(job_key,job_type,target_type,target_id,payload_json,status,error_code,error_message) VALUES (?,'knowledge.corpus.tick','corpus_run',?,?,?,?,?)",
                (f"fixture-{count}", f"{self.run_id}:{stage}", json.dumps({"run_id": self.run_id, "stage": stage}), status, "fixture_error" if error else "", error),
            ).lastrowid)

    def old_index(self) -> int:
        return int(self.retrieval.build_index()["id"])

    def active_index_id(self) -> int:
        return int(self.db.row("SELECT id FROM retrieval_indexes WHERE status='active'")["id"])

    def report_json(self) -> dict:
        return json.loads((self.settings.qa_root / "knowledge" / "knowledge_completion.json").read_text(encoding="utf-8"))

    def published(self) -> dict:
        content = "施工前复核图纸和现场条件，完成技术交底；施工中执行检查并记录偏差，整改后复验闭环。"
        with self.db.connect() as conn:
            source_id = int(conn.execute(
                "INSERT INTO source_files(absolute_path,relative_path,file_name,extension,size_bytes,sha256,family_key,status) VALUES ('content.txt','content.txt','content.txt','.txt',100,'content','content','processed')"
            ).lastrowid)
            document_id = int(conn.execute(
                "INSERT INTO standard_documents(source_id,title,markdown_path,parser,char_count,text_fingerprint) VALUES (?,'管理措施','fixture.md','fixture',100,'content')", (source_id,),
            ).lastrowid)
            section_id = int(conn.execute(
                "INSERT INTO document_sections(document_id,order_no,level,heading,content,content_fingerprint) VALUES (?,1,1,'管理措施',?,?)", (document_id, content, content_hash(content)),
            ).lastrowid)
            unit_id = int(conn.execute(
                "INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,risk_level,content_fingerprint) VALUES ('fixture-unit','management_measure','管理措施',?,?,'medium',?)", (content, content, content_hash(content)),
            ).lastrowid)
            conn.execute("INSERT INTO knowledge_unit_sources(unit_id,section_id,source_id,excerpt) VALUES (?,?,?,?)", (unit_id, section_id, source_id, content))
            version_id = int(conn.execute(
                "INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,1,?,?,'approved')", (unit_id, content, content_hash(content)),
            ).lastrowid)
        self.knowledge.publish_unit(unit_id, version_id, "fixture AI")
        return self.corpus._published_audit_rows()[0]

    def test_terminal_sources_schedule_one_finalizer(self) -> None:
        self.corpus.dispatch = self.dispatch
        self.corpus._dispatch_next(self.run_id)
        self.corpus._dispatch_next(self.run_id)
        self.assertEqual(self.dispatches, [(self.run_id, "__finalize__")])

    def test_running_sources_and_inactive_runs_do_not_schedule_finalizer(self) -> None:
        self.corpus.dispatch = self.dispatch
        with self.db.connect() as conn:
            conn.execute("UPDATE corpus_run_items SET status='running',stage='ai' WHERE run_id=?", (self.run_id,))
        self.corpus._dispatch_next(self.run_id)
        self.assertFalse(self.dispatches)
        with self.db.connect() as conn:
            conn.execute("UPDATE corpus_run_items SET status='terminal',stage='complete' WHERE run_id=?", (self.run_id,))
        for status in ("paused", "completed", "cancelled"):
            self.corpus._set_run(self.run_id, status, status, "fixture")
            self.corpus._dispatch_next(self.run_id)
        self.assertFalse(self.dispatches)

    def test_last_failed_job_pauses_on_reconcile_until_explicit_resume(self) -> None:
        self.corpus.dispatch = self.dispatch
        job_id = self.job(status="failed", error="model review failed: invalid JSON")
        self.corpus._dispatch_next(self.run_id)
        state = self.corpus.get_run(self.run_id)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["checkpoint"]["finalization"]["error"]["job_id"], job_id)
        self.assertFalse(self.dispatches)
        self.assertIn("invalid JSON", self.report_json()["run"]["pause_reason"])
        self.corpus.resume(self.run_id)
        self.corpus._dispatch_next(self.run_id)
        self.assertEqual(self.dispatches, [(self.run_id, "__finalize__")])

    def test_resume_does_not_reopen_completed_or_cancelled_runs(self) -> None:
        self.corpus.dispatch = self.dispatch
        for status in ("completed", "cancelled"):
            self.corpus._set_run(self.run_id, status, status, "fixture")
            self.assertEqual(self.corpus.resume(self.run_id)["status"], status)
        self.assertFalse(self.dispatches)

    def test_publication_audit_error_is_durable_and_keeps_previous_index(self) -> None:
        old_id = self.old_index()
        with patch.object(self.corpus, "_audit_active_publications", side_effect=RuntimeError("model review failed: invalid JSON")), patch.object(self.retrieval, "build_index") as build:
            state = self.corpus._finalize_run(self.run_id)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["stage"], "publication_audit")
        self.assertIn("invalid JSON", state["checkpoint"]["finalization"]["error"]["message"])
        self.assertIn("invalid JSON", self.report_json()["extra"]["error"]["message"])
        self.assertEqual(self.active_index_id(), old_id)
        build.assert_not_called()

    def test_index_error_is_reported_at_index_phase(self) -> None:
        old_id = self.old_index()
        with patch.object(self.retrieval, "build_index", side_effect=RuntimeError("embedding service offline")):
            state = self.corpus._finalize_run(self.run_id)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["stage"], "index")
        self.assertEqual(self.active_index_id(), old_id)
        self.assertEqual(self.report_json()["extra"]["error"]["phase"], "index")

    def test_failed_evaluation_keeps_old_index_and_retry_reuses_candidate(self) -> None:
        old_id = self.old_index()
        with patch.object(self.retrieval, "build_index", wraps=self.retrieval.build_index) as build, patch.object(self.corpus, "_build_and_run_evaluation", side_effect=[{"passed": False, "failed_thresholds": {"recall_at_k": {"actual": 0.5, "required": 0.9}}}, {"passed": True}]):
            failed = self.corpus._finalize_run(self.run_id)
            self.assertEqual(failed["status"], "paused")
            self.assertEqual(failed["stage"], "evaluation")
            candidate_id = failed["checkpoint"]["finalization"]["candidate_index_id"]
            self.assertEqual(self.active_index_id(), old_id)
            self.corpus.resume(self.run_id)
            completed = self.corpus._finalize_run(self.run_id)
            self.assertEqual(build.call_count, 1)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.active_index_id(), candidate_id)
        self.assertEqual(self.report_json()["run"]["status"], "completed")
        self.assertEqual(self.corpus._refresh(self.run_id)["progress"], 100)

    def test_pause_during_evaluation_prevents_activation(self) -> None:
        old_id = self.old_index()

        def evaluate(*args, **kwargs):
            self.corpus.pause(self.run_id, "operator pause")
            return {"passed": True}

        with patch.object(self.corpus, "_build_and_run_evaluation", side_effect=evaluate), patch.object(self.retrieval, "activate_index", wraps=self.retrieval.activate_index) as activate:
            result = self.corpus._finalize_run(self.run_id)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["pause_reason"], "operator pause")
        self.assertEqual(self.active_index_id(), old_id)
        activate.assert_not_called()

    def test_cancellation_stops_before_index_work(self) -> None:
        requested = False

        def progress(stage, value, message, details):
            nonlocal requested
            if stage == "publication_audit":
                requested = True

        with patch.object(self.retrieval, "build_index") as build:
            result = self.corpus._finalize_run(self.run_id, progress, lambda: requested)
        self.assertEqual(result["status"], "cancelled")
        build.assert_not_called()

    def test_report_failure_does_not_declare_completed(self) -> None:
        with patch.object(self.corpus, "_build_and_run_evaluation", return_value={"passed": True}), patch.object(self.corpus, "write_reports", side_effect=OSError("fixture report disk error")):
            result = self.corpus._finalize_run(self.run_id)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["stage"], "reports")
        self.assertIsNone(result["completed_at"])
        self.assertIn("report disk error", result["checkpoint"]["finalization"]["report_error"]["message"])

    def test_cancellation_unwinds_evaluation_transaction_before_updating_run(self) -> None:
        def evaluate(*args, **kwargs):
            with self.db.connect() as conn:
                conn.execute("UPDATE corpus_run_items SET error_message='uncommitted fixture' WHERE run_id=?", (self.run_id,))
                self.corpus._check_finalization(self.run_id, lambda: True)

        with patch.object(self.corpus, "_build_and_run_evaluation", side_effect=evaluate):
            result = self.corpus._finalize_run(self.run_id)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.db.row("SELECT error_message FROM corpus_run_items WHERE run_id=?", (self.run_id,))["error_message"], "")

    def test_two_service_instances_cannot_finalize_same_run_concurrently(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        outcomes: list[dict] = []
        other = CorpusCompletionService(self.db, self.knowledge, Mock(), self.retrieval, self.runtime)

        def audit(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("fixture wait exceeded")
            return {"scanned": 0}

        with patch.object(self.corpus, "_audit_active_publications", side_effect=audit), patch.object(self.corpus, "_build_and_run_evaluation", return_value={"passed": True}), patch.object(self.retrieval, "build_index", wraps=self.retrieval.build_index) as build:
            worker = threading.Thread(target=lambda: outcomes.append(self.corpus._finalize_run(self.run_id)))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(other._finalize_run(self.run_id)["status"], "running")
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(build.call_count, 1)
        self.assertEqual(outcomes[0]["status"], "completed")

    def test_postgres_session_lock_is_released_even_on_error(self) -> None:
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.return_value.fetchone.return_value = {"locked": True}
        fake_db = Mock(database_url="postgresql://synthetic.invalid/isolated", backend="postgresql")
        fake_db.connect.return_value = connection
        self.corpus.db = fake_db
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with self.corpus._run_mutex(123456, "finalize") as acquired:
                self.assertTrue(acquired)
                raise RuntimeError("fixture")
        sql = [call.args[0] for call in connection.execute.call_args_list]
        self.assertIn("pg_try_advisory_lock", sql[0])
        self.assertIn("pg_advisory_unlock", sql[-1])

    def test_passed_revalidation_is_reused_only_for_same_publication_and_content(self) -> None:
        row = self.published()
        review = {"decision": "pass", "confidence": 0.96, "issues": []}
        with patch.object(self.corpus, "_ai_review", return_value=review) as model:
            self.corpus._audit_active_publications(self.run_id)
            self.assertEqual(self.corpus._audit_active_publications(self.run_id)["reused"], 1)
            self.assertEqual(model.call_count, 1)
            updated = row["content"] + "验收记录按批次归档。"
            with self.db.connect() as conn:
                conn.execute("UPDATE knowledge_versions SET content=?,content_hash=? WHERE id=?", (updated, content_hash(updated), row["version_id"]))
                conn.execute("UPDATE knowledge_publications SET content_hash=? WHERE id=?", (content_hash(updated), row["id"]))
            self.corpus._audit_active_publications(self.run_id)
            self.assertEqual(model.call_count, 2)

    def test_republished_version_does_not_inherit_old_revalidation(self) -> None:
        row = self.published()
        review = {"decision": "pass", "confidence": 0.96, "issues": []}
        with patch.object(self.corpus, "_ai_review", return_value=review) as model:
            self.corpus._audit_active_publications(self.run_id)
            with self.db.connect() as conn:
                version_id = int(conn.execute("INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,2,?,?,'approved')", (row["unit_id"], row["content"], row["content_hash"])).lastrowid)
            self.knowledge.publish_unit(row["unit_id"], version_id, "fixture AI")
            self.corpus._audit_active_publications(self.run_id)
            self.assertEqual(model.call_count, 2)

    def test_legacy_revalidation_reuses_exact_ai_input_but_rejects_source_change(self) -> None:
        row = self.published()
        ai_input = {"payload": {"candidate_id": row["id"], "content_hash": row["content_hash"]}, "rendered_prompt": self.corpus._published_review_prompt(row)}
        with self.db.connect() as conn:
            ai_id = int(conn.execute(
                "INSERT INTO ai_runs(task_type,prompt_key,prompt_version,prompt_hash,input_hash,cache_key,model,base_url,wire_api,status,input_json) VALUES ('published_knowledge_revalidation','knowledge.formal-review','1',?,'input','cache','fixture','fixture','responses','succeeded',?)",
                (KNOWLEDGE_FORMAL_REVIEW_PROMPT.prompt_hash, json.dumps(ai_input, ensure_ascii=False)),
            ).lastrowid)
        self.corpus._decision(self.run_id, {"unit_id": row["unit_id"]}, "published_revalidation", "pass", 0.96, [], ai_id)
        with patch.object(self.corpus, "_ai_review", return_value={"decision": "pass", "confidence": 0.96, "issues": []}) as model:
            self.assertEqual(self.corpus._audit_active_publications(self.run_id)["reused"], 1)
            model.assert_not_called()
            with self.db.connect() as conn:
                conn.execute("UPDATE document_sections SET content=content || '来源补充说明。' WHERE id=?", (row["section_id"],))
            self.corpus._audit_active_publications(self.run_id)
            self.assertEqual(model.call_count, 1)


if __name__ == "__main__":
    unittest.main()
