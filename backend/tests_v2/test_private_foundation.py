from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.audit import AuditService
from bid_writer_v2.database import Database, _postgres_sql, postgres_migration_statements
from bid_writer_v2.evidence import EvidenceService
from bid_writer_v2.jobs import JobService
from bid_writer_v2.knowledge.pipeline import CHUNK_MAX_CHARS, KnowledgePipelineService
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.retrieval import HybridRetrievalService
from bid_writer_v2.storage import ObjectStorage
from bid_writer_v2.utils import content_hash
from test_v2_workflow import build_settings


class PrivateFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = build_settings(self.root)
        self.settings.ensure_directories()
        self.db = Database(self.settings.db_path)
        self.db.migrate()
        self.audit = AuditService(self.db)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_long_document_chunks_cover_all_content_and_keep_overlap(self) -> None:
        with self.db.connect() as conn:
            source_id = int(
                conn.execute(
                    "INSERT INTO source_files(absolute_path,relative_path,file_name,extension,sha256,family_key) VALUES (?,?,?,?,?,?)",
                    (str(self.root / "long.md"), "long.md", "long.md", ".md", "a" * 64, "long"),
                ).lastrowid
            )
            document_id = int(
                conn.execute(
                    "INSERT INTO standard_documents(source_id,title,markdown_path,parser,char_count,text_fingerprint) VALUES (?,?,?,?,?,?)",
                    (source_id, "超长方案", "long.md", "markdown", 60000, "b" * 64),
                ).lastrowid
            )
            body = "施工准备完成后组织复核，确认无误后进入下一工序。\n" * 5000
            conn.execute(
                "INSERT INTO document_sections(document_id,order_no,level,heading,content,content_fingerprint) VALUES (?,1,1,?,?,?)",
                (document_id, "超长章节", body, content_hash(body)),
            )
        knowledge = KnowledgeService(self.db, self.settings)
        pipeline = KnowledgePipelineService(self.db, knowledge, AiRuntime(self.db, knowledge.llm))
        chunks = pipeline.prepare_chunks(document_id)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(item["content"]) <= CHUNK_MAX_CHARS + 100 for item in chunks))
        self.assertEqual(chunks[0]["char_start"], 0)
        self.assertEqual(chunks[-1]["char_end"], len(body.strip()))
        self.assertLess(chunks[1]["char_start"], chunks[0]["char_end"])

    def test_jobs_are_durable_and_audit_chain_detects_tampering(self) -> None:
        jobs = JobService(self.db, self.settings, self.audit)

        def handler(payload, report, cancelled):
            report("work", 50, "处理中", {"value": payload["value"]})
            self.assertFalse(cancelled())
            return {"answer": payload["value"] * 2}

        jobs.register("test.double", handler)
        job = jobs.enqueue("test.double", "fixture", 1, {"value": 21})
        completed = jobs.run(job["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["answer"], 42)
        self.assertGreaterEqual(len(completed["events"]), 3)
        self.assertTrue(self.audit.verify_chain()["valid"])
        with self.db.connect() as conn:
            conn.execute("UPDATE audit_events SET details_json='{}' WHERE id=(SELECT MIN(id) FROM audit_events)")
        self.assertFalse(self.audit.verify_chain()["valid"])

    def test_job_redispatch_is_noop_without_background_worker(self) -> None:
        jobs = JobService(self.db, self.settings, self.audit)
        jobs.register("test.noop", lambda payload, report, cancelled: payload)
        queued = jobs.enqueue("test.noop", "fixture", 1, {})
        self.assertEqual(queued["status"], "pending")
        self.assertEqual(jobs.redispatch_unfinished(), 0)

    def test_audit_verifier_accepts_cryptographically_valid_concurrent_branch(self) -> None:
        first = self.audit.record("test.first", "fixture", 1)
        self.audit.record("test.second", "fixture", 2)
        request_id = "concurrent-branch"
        actor_name = "system"
        action = "test.concurrent"
        target_type = "fixture"
        target_id = "3"
        outcome = "success"
        payload = "{}"
        event_hash = content_hash(
            "|".join(
                [first["event_hash"], request_id, actor_name, action, target_type, target_id, outcome, payload]
            )
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events(
                    request_id,actor_name,action,target_type,target_id,outcome,
                    details_json,previous_hash,event_hash
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (request_id, actor_name, action, target_type, target_id, outcome, payload, first["event_hash"], event_hash),
            )
        result = self.audit.verify_chain()
        self.assertTrue(result["valid"])
        self.assertEqual(result["branches"], 1)

    def test_hybrid_index_only_contains_published_knowledge(self) -> None:
        with self.db.connect() as conn:
            published_id = int(
                conn.execute(
                    "INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,tags_json,risk_level,status,content_fingerprint) VALUES (?,?,?,?,?,'[]','textual','published',?)",
                    ("published", "construction_method", "深基坑排水", "设置截水沟和集水井并配置备用泵。", "设置截水沟和集水井并配置备用泵。", "p" * 64),
                ).lastrowid
            )
            draft_id = int(
                conn.execute(
                    "INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,tags_json,risk_level,status,content_fingerprint) VALUES (?,?,?,?,?,'[]','textual','draft',?)",
                    ("draft", "construction_method", "秘密未发布方案", "未发布内容不得检索。", "未发布内容不得检索。", "d" * 64),
                ).lastrowid
            )
            version_id = int(
                conn.execute(
                    "INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,1,?,?,'approved')",
                    (published_id, "设置截水沟和集水井并配置备用泵。", "p" * 64),
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO knowledge_publications(unit_id,version_id,publication_version,published_by,file_path,content_hash) VALUES (?,?,1,'test','published.md',?)",
                (published_id, version_id, "p" * 64),
            )
        storage = ObjectStorage(self.db, self.settings)
        retrieval = HybridRetrievalService(self.db, self.settings, storage)
        index = retrieval.build_index()
        self.assertEqual(index["bm25_documents"], 1)
        results = retrieval.search("基坑排水备用泵")
        self.assertEqual([item["unit_id"] for item in results], [published_id])
        self.assertNotIn(draft_id, [item["unit_id"] for item in results])
        self.assertIn("bm25", results[0]["scores"])
        retrieval.embedding.rerank = lambda _query, documents: [0.01 for _item in documents]
        self.assertEqual(retrieval.search("无关专业问题"), [])

    def test_high_risk_claim_blocks_until_resolved(self) -> None:
        with self.db.connect() as conn:
            project_id = int(conn.execute("INSERT INTO projects(name) VALUES ('证据测试')").lastrowid)
            section_id = int(conn.execute("INSERT INTO project_sections(project_id,order_no,title) VALUES (?,1,'工期')", (project_id,)).lastrowid)
            draft_id = int(
                conn.execute(
                    "INSERT INTO project_drafts(project_id,section_id,content,content_hash) VALUES (?,?,?,?)",
                    (project_id, section_id, "本项目保证30天内完成全部施工。", content_hash("本项目保证30天内完成全部施工。")),
                ).lastrowid
            )
        evidence = EvidenceService(self.db)
        run_id = evidence.create_generation_run(project_id, section_id, "input", "model", "1", "1", None, [])
        report = evidence.analyze_draft(run_id, draft_id, "本项目保证30天内完成全部施工。", [{"content": "项目应合理安排施工进度。"}])
        self.assertEqual(report["evidence_status"], "blocked")
        claim = evidence.list_claims(draft_id)[0]
        resolved = evidence.resolve_claim(claim["id"], "confirm", "已与招标文件工期条款逐字核对")
        self.assertEqual(resolved["evidence_status"], "supported")

    def test_postgres_baseline_is_portable_and_excludes_sqlite_fts(self) -> None:
        root = Path(__file__).parents[1] / "bid_writer_v2" / "migrations"
        statements = postgres_migration_statements(root)
        joined = "\n".join(statements)
        self.assertNotIn("AUTOINCREMENT", joined)
        self.assertNotIn("CREATE VIRTUAL TABLE", joined)
        self.assertIn("CREATE TABLE app_jobs", joined)
        self.assertIn("BIGSERIAL PRIMARY KEY", joined)

    def test_postgres_runtime_timestamps_are_written_as_text(self) -> None:
        translated, bindings, expects_id = _postgres_sql(
            "UPDATE app_jobs SET started_at=COALESCE(started_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (7,),
        )
        self.assertIn("COALESCE(started_at,(CURRENT_TIMESTAMP)::text)", translated)
        self.assertIn("updated_at=(CURRENT_TIMESTAMP)::text", translated)
        self.assertEqual(bindings, {"p0": 7})
        self.assertFalse(expects_id)


if __name__ == "__main__":
    unittest.main()
