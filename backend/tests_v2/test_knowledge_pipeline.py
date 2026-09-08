from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from docx import Document

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.pipeline import KnowledgePipelineService, RetryableAiAdjudicationError
from bid_writer_v2.knowledge.service import KnowledgeService

from test_v2_workflow import build_settings, create_source_docx


class PipelineLlm:
    def __init__(self) -> None:
        self.calls = 0

    def settings(self) -> dict:
        return {"configured": True, "base_url": "http://model.test/v1", "model": "pipeline-test", "wire_api": "responses"}

    def generate(self, instructions: str, prompt: str, max_output_tokens: int = 8000) -> dict:
        self.calls += 1
        document_ids = [int(value) for value in re.findall(r"\[DOCUMENT:(\d+)\]", prompt)]
        if "知识工程师" in instructions:
            section_id = int(re.search(r"\[SECTION:(\d+)\]", prompt).group(1))
            payload = {
                "candidates": [
                    {
                        "source_section_id": section_id,
                        "title": "施工准备与过程闭环控制",
                        "unit_type": "management_measure",
                        "content": "施工前完成技术交底、图纸会审和作业条件确认，施工过程中实施检查，发现偏差后整改并形成闭环记录。",
                        "summary": "施工准备、过程检查和整改闭环的通用管理方法。",
                        "tags": ["施工准备", "过程检查", "闭环"],
                        "applicability": "房屋建筑工程施工管理",
                        "risk_level": "低",
                        "source_quote": "施工前完成技术交底、图纸会审、现场复核和作业条件确认。",
                    },
                    {
                        "source_section_id": section_id,
                        "title": "无法定位的候选知识",
                        "unit_type": "quality_control",
                        "content": "所有检查工作完成后均应形成记录，并由相关责任人确认后归档，作为后续验收依据。",
                        "summary": "检查记录和验收归档要求。",
                        "tags": ["检查记录"],
                        "applicability": "工程质量管理",
                        "risk_level": "low",
                        "source_quote": "这段文字并不存在于来源章节中，因此必须进入异常待办。",
                    },
                    {
                        "source_section_id": section_id,
                        "title": "需要人工复核的高风险候选",
                        "unit_type": "management_measure",
                        "content": "施工前完成技术交底、图纸会审和现场复核，过程检查发现偏差后及时整改并形成闭环记录。",
                        "summary": "施工准备和整改闭环管理要求。",
                        "tags": ["施工准备", "风险复核"],
                        "applicability": "适用范围需要技术负责人确认",
                        "risk_level": "高",
                        "source_quote": "施工前完成技术交底、图纸会审、现场复核和作业条件确认。",
                    },
                ],
            }
            if document_ids:
                payload["source_dispositions"] = [
                    {
                        "document_id": document_id,
                        "decision": "reusable" if index == 0 else "not_reusable",
                        "confidence": 0.98,
                        "reason": "来源包含可复用施工管理内容。" if index == 0 else "仅为项目专属补充内容，不具备跨项目复用条件。",
                        "evidence_quote": "施工前完成技术交底、图纸会审、现场复核和作业条件确认。" if index == 0 else "",
                    }
                    for index, document_id in enumerate(document_ids)
                ]
        else:
            payload = {
                "reviews": [
                    {"candidate_index": 0, "decision": "通过", "confidence": 0.96, "issues": [], "corrected_content": ""},
                    {"candidate_index": 1, "decision": "pass", "confidence": 0.95, "issues": [], "corrected_content": ""},
                    {"candidate_index": 2, "decision": "pass", "confidence": 0.94, "issues": [{"severity": "中", "description": "适用范围需要确认"}], "corrected_content": ""},
                ],
            }
            if document_ids:
                payload["source_dispositions"] = [
                    {
                        "document_id": document_id,
                        "decision": "reusable" if index == 0 else "not_reusable",
                        "confidence": 0.98,
                        "reason": "独立复核确认来源含通用管理措施。" if index == 0 else "独立复核确认仅含项目专属内容。",
                        "evidence_quote": "施工前完成技术交底、图纸会审、现场复核和作业条件确认。" if index == 0 else "",
                    }
                    for index, document_id in enumerate(document_ids)
                ]
        return {
            **self.settings(),
            "content": json.dumps(payload, ensure_ascii=False),
            "error": "",
            "latency_ms": 5,
            "attempts": 1,
            "input_tokens": 100,
            "output_tokens": 50,
        }

    @staticmethod
    def json_payload(text: str) -> dict:
        return json.loads(text)


class KnowledgePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = build_settings(self.root)
        self.settings.ensure_directories()
        self.db = Database(self.settings.db_path)
        self.db.migrate()
        self.llm = PipelineLlm()
        self.runtime = AiRuntime(self.db, self.llm)
        self.knowledge = KnowledgeService(self.db, self.settings, self.llm, self.runtime)
        self.pipeline = KnowledgePipelineService(self.db, self.knowledge, self.runtime)
        create_source_docx(self.settings.raw_root / "学校" / "教学楼技术标.docx")
        self.knowledge.scan_sources()
        jobs = self.knowledge.create_jobs(limit=10)
        processed = self.knowledge.run_job(jobs["job_ids"][0])
        self.document_id = processed["document_id"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_extracts_reviews_routes_exceptions_and_accepts_ready_candidates(self) -> None:
        result = self.pipeline.process_document(self.document_id, max_candidates=6)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(self.llm.calls, 2)

        candidates = self.pipeline.list_candidates()
        ready = next(item for item in candidates if item["status"] == "ready")
        blocked = next(item for item in candidates if any(finding["code"] == "quote_mismatch" for finding in item["rule_findings"]))
        self.assertFalse(ready["rule_findings"])
        self.assertIn("quote_mismatch", {item["code"] for item in blocked["rule_findings"]})
        tasks = self.pipeline.list_tasks()
        self.assertTrue(any(item["candidate_id"] == blocked["id"] and item["severity"] == "high" for item in tasks))
        self.assertTrue(any(item["issue_code"] == "candidate_risk" for item in tasks))

        accepted = self.pipeline.accept_ready("测试技术负责人")
        self.assertEqual(accepted["accepted"], 1)
        promoted = self.pipeline.get_candidate(ready["id"])
        self.assertEqual(promoted["status"], "accepted")
        unit = self.knowledge.get_unit(promoted["unit_id"])
        self.assertEqual(unit["status"], "review_required")
        self.assertEqual(unit["versions"][0]["origin"], "ai_extract")

        replayed = self.pipeline.process_document(self.document_id, max_candidates=6)
        self.assertTrue(replayed["reused"])
        self.assertEqual(self.llm.calls, 2)

    def test_short_document_batch_preserves_real_provenance(self) -> None:
        second_path = self.settings.raw_root / "hospital" / "second.docx"
        create_source_docx(second_path)
        second_docx = Document(second_path)
        second_docx.add_paragraph("第二份短文档的独立来源内容，用于验证批处理仍保持真实来源关系。")
        second_docx.save(second_path)
        self.knowledge.scan_sources()
        source = self.db.row("SELECT id FROM source_files WHERE absolute_path=?", (str(second_path.resolve()),))
        jobs = self.knowledge.create_jobs([int(source["id"])], 1)
        processed = self.knowledge.run_job(jobs["job_ids"][0])
        second_document_id = int(processed["document_id"])
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE standard_documents SET text_fingerprint=? WHERE id=?",
                ("second-document-fingerprint", second_document_id),
            )
        first_section = int(self.db.row(
            "SELECT id FROM document_sections WHERE document_id=? ORDER BY id LIMIT 1", (self.document_id,)
        )["id"])
        second_section = int(self.db.row(
            "SELECT id FROM document_sections WHERE document_id=? ORDER BY id LIMIT 1", (second_document_id,)
        )["id"])

        result = self.pipeline.process_document_batch(
            [(self.document_id, [first_section]), (second_document_id, [second_section])],
            max_candidates=6,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["batched_documents"], 2)
        self.assertEqual(self.llm.calls, 2)
        candidate = self.db.row(
            "SELECT document_id,source_id,source_section_id FROM knowledge_ai_candidates WHERE pipeline_run_id=? ORDER BY id LIMIT 1",
            (result["id"],),
        )
        expected = self.db.row(
            "SELECT d.id AS document_id,d.source_id FROM document_sections s JOIN standard_documents d ON d.id=s.document_id WHERE s.id=?",
            (first_section,),
        )
        self.assertEqual(candidate["source_section_id"], first_section)
        self.assertEqual(candidate["document_id"], expected["document_id"])
        self.assertEqual(candidate["source_id"], expected["source_id"])
        dispositions = self.db.rows(
            "SELECT document_id,decision_stage,decision,confidence,actor_type,ai_run_id FROM knowledge_source_dispositions WHERE pipeline_run_id=? ORDER BY document_id,decision_stage",
            (result["id"],),
        )
        self.assertEqual(len(dispositions), 4)
        self.assertTrue(all(item["actor_type"] == "ai" and item["ai_run_id"] for item in dispositions))
        second_decisions = [item for item in dispositions if int(item["document_id"]) == second_document_id]
        self.assertEqual({item["decision"] for item in second_decisions}, {"not_reusable"})
        self.assertTrue(all(float(item["confidence"]) >= 0.95 for item in second_decisions))

    def test_discontinuous_exact_quote_lines_are_valid_anchors(self) -> None:
        findings = self.pipeline._rule_findings(
            {
                "content": "施工前完成图纸会审，施工后形成验收记录。",
                "source_quote": "施工前完成图纸会审。\n施工后形成验收记录。",
            },
            {"content": "施工前完成图纸会审。\n中间还有其他原文。\n施工后形成验收记录。"},
            True,
        )
        self.assertNotIn("quote_mismatch", {item["code"] for item in findings})

    def test_layout_whitespace_does_not_break_quote_anchor(self) -> None:
        findings = self.pipeline._rule_findings(
            {
                "content": "施工机械设备进场时进行性能验收，并实施跟班维护。",
                "source_quote": "设备进场验收：施工机械设备进场时进行性能验收；施工中维护：实施跟班维护。",
            },
            {"content": "设备进场验收：施工机械设备进场时进行性能验收；\n施工中维护：实施跟班维 护。"},
            True,
        )
        self.assertNotIn("quote_mismatch", {item["code"] for item in findings})

    def test_failed_auto_publish_adjudication_keeps_candidates_retryable(self) -> None:
        result = self.pipeline.process_document(self.document_id, max_candidates=6)
        ready = next(item for item in self.pipeline.list_candidates() if item["status"] == "ready")
        original_execute = self.runtime.execute
        self.runtime.execute = lambda *_args, **_kwargs: {
            "run_id": None,
            "payload": None,
            "error": "model unavailable",
        }
        try:
            with self.assertRaises(RetryableAiAdjudicationError):
                self.pipeline.auto_publish_low_risk(result["id"])
        finally:
            self.runtime.execute = original_execute
        candidate = self.pipeline.get_candidate(ready["id"])
        self.assertEqual(candidate["status"], "ready")
        self.assertFalse(any(item["issue_code"] == "adjudication_failed" for item in self.pipeline.list_tasks()))

    def test_auto_publish_retry_is_idempotent(self) -> None:
        result = self.pipeline.process_document(self.document_id, max_candidates=6)
        first = self.pipeline.auto_publish_low_risk(result["id"])
        calls_after_first = self.llm.calls
        second = self.pipeline.auto_publish_low_risk(result["id"])

        self.assertEqual(second["batch_id"], first["batch_id"])
        self.assertEqual(self.llm.calls, calls_after_first)
        candidate = next(item for item in self.pipeline.list_candidates() if item["auto_publish_batch_id"] == first["batch_id"])
        publications = self.db.rows(
            "SELECT id FROM knowledge_publications WHERE unit_id=? AND status='published'",
            (candidate["unit_id"],),
        )
        samples = self.db.rows(
            "SELECT id FROM knowledge_exception_tasks WHERE candidate_id=? AND issue_code='auto_publish_sample' AND status='open'",
            (candidate["id"],),
        )
        self.assertEqual(len(publications), 1)
        self.assertEqual(len(samples), 1)

    def test_postgres_backend_skips_sqlite_fts_updates(self) -> None:
        class RejectingConnection:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("PostgreSQL path must not execute SQLite FTS SQL")

        service = object.__new__(KnowledgeService)
        service.db = Database(
            self.settings.db_path,
            database_url="postgresql+psycopg://example:example@localhost/example",
        )
        service._delete_sqlite_fts(RejectingConnection(), 1)
        service._replace_sqlite_fts(RejectingConnection(), 1, {})


if __name__ == "__main__":
    unittest.main()
