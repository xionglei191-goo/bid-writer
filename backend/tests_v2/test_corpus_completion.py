from __future__ import annotations

import tempfile
import unittest
import zipfile
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.audit import AuditService
from bid_writer_v2.database import Database
from bid_writer_v2.evaluation import RetrievalEvaluationService
from bid_writer_v2.knowledge.corpus import CorpusCompletionService
from bid_writer_v2.knowledge.ocr import ocr_pdf_step
from bid_writer_v2.knowledge.parsers import _parse_docx, _parse_docx_xml_fallback, _parse_legacy_doc_text
from bid_writer_v2.knowledge.pipeline import KnowledgePipelineService
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.retrieval import HybridRetrievalService
from bid_writer_v2.storage import ObjectStorage
from bid_writer_v2.utils import content_hash, normalize_text
from test_v2_workflow import build_settings


class CorpusCompletionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = build_settings(self.root)
        self.settings.ensure_directories()
        self.db = Database(self.settings.db_path)
        self.db.migrate()
        self.audit = AuditService(self.db)
        self.runtime = AiRuntime(self.db)
        self.knowledge = KnowledgeService(self.db, self.settings, ai_runtime=self.runtime)
        self.pipeline = KnowledgePipelineService(self.db, self.knowledge, self.runtime)
        self.retrieval = HybridRetrievalService(self.db, self.settings, ObjectStorage(self.db, self.settings))
        self.evaluation = RetrievalEvaluationService(self.db, self.knowledge, self.runtime, self.audit)
        self.corpus = CorpusCompletionService(
            self.db, self.knowledge, self.pipeline, self.retrieval, self.runtime, self.evaluation
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _source(
        self,
        name: str,
        extension: str,
        status: str = "discovered",
        duplicate_of: int | None = None,
        source_kind: str = "raw",
    ) -> int:
        path = self.settings.raw_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        with self.db.connect() as conn:
            return int(conn.execute(
                """
                INSERT INTO source_files(
                    absolute_path,relative_path,file_name,extension,size_bytes,sha256,family_key,
                    source_kind,duplicate_of,status
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (str(path), name, path.name, extension, 7, content_hash(name), path.stem, source_kind, duplicate_of, status),
            ).lastrowid)

    def _document(self, name: str, title: str, content: str, source_kind: str = "raw") -> int:
        source_id = self._source(name, Path(name).suffix, "processed", source_kind=source_kind)
        with self.db.connect() as conn:
            document_id = int(conn.execute(
                "INSERT INTO standard_documents(source_id,title,markdown_path,parser,char_count,text_fingerprint) VALUES (?,?,?,?,?,?)",
                (source_id, title, name + ".md", "fixture", len(content), content_hash(content)),
            ).lastrowid)
            conn.execute(
                "INSERT INTO document_sections(document_id,order_no,level,heading,content,content_fingerprint) VALUES (?,1,1,?,?,?)",
                (document_id, title, content, content_hash(content)),
            )
        return document_id

    def test_representative_sections_use_one_document_level_embedding_batch(self) -> None:
        content = "施工现场四周设置连续排水沟和集水井，并配置足量备用水泵和应急电源。"
        document_id = self._document("batched.md", "排水方案", content)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO document_sections(document_id,order_no,level,heading,content,content_fingerprint) VALUES (?,2,2,?,?,?)",
                (document_id, "排水措施", content + "同时安排专人巡查。", content_hash(content + "同时安排专人巡查。")),
            )
            conn.execute(
                "INSERT INTO document_sections(document_id,order_no,level,heading,content,content_fingerprint) VALUES (?,3,2,?,?,?)",
                (document_id, "排水检查", content + "并建立检查记录。", content_hash(content + "并建立检查记录。")),
            )
        run = self.corpus.create_run()
        self.retrieval.embedding.settings = replace(self.settings, embedding_url="http://embedding:8090")
        calls: list[list[str]] = []

        def embed(texts: list[str]) -> list[list[float]]:
            calls.append(list(texts))
            return [[1.0, 0.0] for _text in texts]

        self.retrieval.embedding.embed = embed
        representatives = self.corpus._prepare_representative_sections(run["id"], document_id)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 3)
        self.assertTrue(representatives)
        clusters = self.db.rows(
            "SELECT member_section_id FROM corpus_section_clusters WHERE run_id=?",
            (run["id"],),
        )
        self.assertEqual(len(clusters), 3)

    def test_snapshot_assigns_every_source_an_auditable_state(self) -> None:
        original = self._source("text.docx", ".docx")
        self._source("copy.docx", ".docx", "duplicate", original)
        self._source("asset.png", ".png", "asset")
        self._source("drawing.dwg", ".dwg", "metadata_only")
        self._source("broken.zip", ".zip", "failed")
        run = self.corpus.create_run()
        items = self.db.rows("SELECT item_kind,stage,status,terminal_reason FROM corpus_run_items WHERE run_id=? ORDER BY id", (run["id"],))
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]["stage"], "normalize")
        self.assertEqual(items[1]["terminal_reason"], "duplicate")
        self.assertEqual(items[2]["stage"], "governance")
        self.assertEqual(items[3]["terminal_reason"], "metadata_only_excluded")
        self.assertEqual(items[4]["terminal_reason"], "unreadable_excluded")

    def test_rescan_keeps_processed_state_when_hash_is_unchanged(self) -> None:
        source_path = self.settings.raw_root / "kept.txt"
        source_path.write_text("stable", encoding="utf-8")
        first = self.knowledge.scan_sources()
        source = self.db.row("SELECT * FROM source_files WHERE file_name='kept.txt'")
        with self.db.connect() as conn:
            conn.execute("UPDATE source_files SET status='processed' WHERE id=?", (source["id"],))
        second = self.knowledge.scan_sources()
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual((self.db.row("SELECT status FROM source_files WHERE id=?", (source["id"],)) or {})["status"], "processed")

    def test_office_lock_files_are_metadata_only(self) -> None:
        lock = self.settings.raw_root / "~$temporary.docx"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_bytes(b"office-lock")
        self.knowledge.scan_sources()
        source = self.db.row("SELECT status FROM source_files WHERE absolute_path=?", (str(lock.resolve()),))
        self.assertEqual(source["status"], "metadata_only")

    def test_number_conflicts_are_never_merged(self) -> None:
        self.assertNotEqual(
            self.corpus._number_signature("保护层厚度为20mm，执行GB 50010。"),
            self.corpus._number_signature("保护层厚度为25mm，执行GB 50010。"),
        )

    def test_review_context_is_bounded_and_keeps_quote_anchor(self) -> None:
        source = "前置无关内容" * 20000 + "需要逐字核验的来源引文" + "后置无关内容" * 20000
        candidate = {"id": 9, "source_section_id": 7, "source_quote": "需要逐字核验的来源引文"}
        context = self.corpus._review_source_context(
            [candidate],
            {7: {"heading": "来源章节", "content": source}},
        )
        self.assertIn("需要逐字核验的来源引文", context)
        self.assertIn("[CANDIDATE:9]", context)
        self.assertLess(len(context), 5000)

    def test_visual_only_document_is_closed_without_model_review(self) -> None:
        document_id = self._document(
            "drawing.md",
            "附图-施工现场平面布置图",
            "![施工现场平面布置图](/workspace/knowledge/fixtures/image_1.png)",
        )
        self.assertEqual(
            self.corpus._deterministic_non_reusable_reason(document_id),
            "visual_only_without_reusable_text",
        )

    def test_short_actionable_technical_text_is_not_excluded(self) -> None:
        content = (
            "施工前核对图纸、技术标准和现场条件，形成书面复核记录；"
            "作业完成后按验收标准逐项检查，检查合格并经批准后方可进入下一工序。"
        )
        document_id = self._document("measure.md", "施工复核与验收措施", content)
        self.assertEqual(self.corpus._deterministic_non_reusable_reason(document_id), "")

    def test_long_historical_drawing_is_archived_but_system_generated_chart_is_allowed(self) -> None:
        drawing = "塔吊 道路 围挡 加工区 材料堆场 " * 100
        historical_id = self._document("old-layout.md", "主体阶段施工平面布置图", drawing)
        generated_id = self._document(
            "generated-flow.md",
            "混凝土浇筑验收流程图",
            "施工准备、隐蔽验收、浇筑申请、旁站检查和养护记录按顺序执行。" * 30,
            source_kind="system_generated",
        )
        self.assertEqual(
            self.corpus._deterministic_non_reusable_reason(historical_id),
            "historical_visual_or_front_matter_archived",
        )
        self.assertEqual(self.corpus._deterministic_non_reusable_reason(generated_id), "")

    def test_drawing_design_explanation_is_not_archived_by_title_only(self) -> None:
        explanation = "施工平面布置应结合现场复核结果编制，明确道路、消防、临电和材料堆场，审批后实施。" * 30
        document_id = self._document("layout-explanation.md", "施工平面布置图设计说明", explanation)
        self.assertEqual(self.corpus._deterministic_non_reusable_reason(document_id), "")
        attachment_id = self._document("attachment-explanation.md", "附图编制说明", explanation)
        self.assertEqual(self.corpus._deterministic_non_reusable_reason(attachment_id), "")

    def test_single_page_historical_drawing_is_archived_without_ocr(self) -> None:
        source_id = self._source("建方 01-总平面图.pdf", ".pdf")
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            job_id = int(conn.execute(
                "INSERT INTO processing_jobs(source_id,job_type,status,current_step,checkpoint_json) VALUES (?,'normalize','waiting_ocr','ocr',?)",
                (source_id, '{"page_count": 1}'),
            ).lastrowid)
            conn.execute(
                "UPDATE corpus_run_items SET stage='ocr',status='running',processing_job_id=? WHERE run_id=? AND source_id=?",
                (job_id, run["id"], source_id),
            )
        item = self.db.row(
            "SELECT i.*,s.file_name FROM corpus_run_items i JOIN source_files s ON s.id=i.source_id WHERE i.run_id=? AND i.source_id=?",
            (run["id"], source_id),
        )
        self.knowledge.run_ocr = lambda *_args, **_kwargs: self.fail("historical drawing must not be uploaded to OCR")
        self.corpus._ocr_item(item)
        state = self.db.row("SELECT status,terminal_reason,checkpoint_json FROM corpus_run_items WHERE id=?", (item["id"],))
        job = self.db.row("SELECT status,current_step FROM processing_jobs WHERE id=?", (job_id,))
        self.assertEqual((state["status"], state["terminal_reason"]), ("terminal", "no_reusable_knowledge"))
        self.assertEqual((job["status"], job["current_step"]), ("skipped", "archived_visual"))

    def test_single_page_record_is_still_sent_to_ocr(self) -> None:
        source_id = self._source("单位工程质量竣工验收记录表.pdf", ".pdf")
        with self.db.connect() as conn:
            job_id = int(conn.execute(
                "INSERT INTO processing_jobs(source_id,job_type,status,current_step,checkpoint_json) VALUES (?,'normalize','waiting_ocr','ocr',?)",
                (source_id, '{"page_count": 1}'),
            ).lastrowid)
        self.assertFalse(self.corpus._is_historical_single_page_visual({"file_name": "单位工程质量竣工验收记录表.pdf"}, job_id))

    def test_stale_ai_and_pipeline_records_are_closed_after_restart(self) -> None:
        document_id = self._document("stale.md", "中断任务", "施工前复核条件，完成后按标准验收。")
        with self.db.connect() as conn:
            ai_run_id = int(conn.execute(
                """
                INSERT INTO ai_runs(task_type,prompt_key,prompt_version,prompt_hash,input_hash,cache_key,status,created_at)
                VALUES ('fixture','fixture','1','p','i','c','running',datetime('now','-3 hours'))
                """
            ).lastrowid)
            pipeline_run_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,extraction_ai_run_id,created_at)
                VALUES (?,?,?,'running',?,datetime('now','-3 hours'))
                """,
                (document_id, "stale-fixture", "input", ai_run_id),
            ).lastrowid)
        run = self.corpus.create_run()
        self.corpus._recover_stale_items(run["id"])
        ai_state = self.db.row("SELECT status,error_code FROM ai_runs WHERE id=?", (ai_run_id,))
        pipeline_state = self.db.row("SELECT status,error_message FROM knowledge_ai_pipeline_runs WHERE id=?", (pipeline_run_id,))
        self.assertEqual(ai_state, {"status": "failed", "error_code": "worker_restart"})
        self.assertEqual(pipeline_state["status"], "completed_with_exceptions")
        self.assertIn("后台进程中断", pipeline_state["error_message"])

    def test_future_dated_orphan_is_closed_only_after_new_request_takes_over(self) -> None:
        document_id = self._document("clock-rollback.md", "时钟回拨任务", "施工前复核条件，完成后按标准验收。")
        with self.db.connect() as conn:
            orphan_ai_id = int(conn.execute(
                """
                INSERT INTO ai_runs(
                    task_type,target_type,target_id,prompt_key,prompt_version,prompt_hash,
                    input_hash,cache_key,status,created_at
                ) VALUES ('fixture','standard_document',?,'fixture','1','p','future','future-cache',
                    'running',datetime('now','+3 hours'))
                """,
                (document_id,),
            ).lastrowid)
            orphan_pipeline_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(
                    document_id,pipeline_key,input_hash,status,extraction_ai_run_id,created_at
                ) VALUES (?,?,?,'running',?,datetime('now','+3 hours'))
                """,
                (document_id, "future-pipeline", "future", orphan_ai_id),
            ).lastrowid)
        run = self.corpus.create_run()
        self.corpus._recover_stale_items(run["id"])
        self.assertEqual((self.db.row("SELECT status FROM ai_runs WHERE id=?", (orphan_ai_id,)) or {})["status"], "running")

        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_runs(
                    task_type,target_type,target_id,prompt_key,prompt_version,prompt_hash,
                    input_hash,cache_key,status,created_at
                ) VALUES ('fixture','standard_document',?,'fixture','1','p','replacement','replacement-cache',
                    'running',CURRENT_TIMESTAMP)
                """,
                (document_id,),
            )
            conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,created_at)
                VALUES (?,?,?,'running',CURRENT_TIMESTAMP)
                """,
                (document_id, "replacement-pipeline", "replacement"),
            )
        self.corpus._recover_stale_items(run["id"])
        ai_state = self.db.row("SELECT status,error_code FROM ai_runs WHERE id=?", (orphan_ai_id,))
        pipeline_state = self.db.row("SELECT status FROM knowledge_ai_pipeline_runs WHERE id=?", (orphan_pipeline_id,))
        self.assertEqual(ai_state, {"status": "failed", "error_code": "worker_restart"})
        self.assertEqual(pipeline_state["status"], "completed_with_exceptions")

    def test_orphan_candidate_review_is_closed_after_pipeline_candidates_are_terminal(self) -> None:
        document_id = self._document("candidate-orphan.md", "候选复核中断", "施工前复核条件，完成后按标准验收。")
        with self.db.connect() as conn:
            pipeline_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,completed_at)
                VALUES (?,?,?,'completed',CURRENT_TIMESTAMP)
                """,
                (document_id, "terminal-candidate-pipeline", "input"),
            ).lastrowid)
            ai_id = int(conn.execute(
                """
                INSERT INTO ai_runs(
                    task_type,target_type,target_id,prompt_key,prompt_version,prompt_hash,
                    input_hash,cache_key,status
                ) VALUES ('knowledge_technical_revision','knowledge_candidate_batch',?,
                    'fixture','1','p','i','terminal-candidate-ai','running')
                """,
                (pipeline_id,),
            ).lastrowid)
        run = self.corpus.create_run()

        self.corpus._recover_stale_items(run["id"])

        state = self.db.row("SELECT status,error_code,error_message FROM ai_runs WHERE id=?", (ai_id,))
        self.assertEqual((state["status"], state["error_code"]), ("failed", "worker_restart"))
        self.assertIn("无可执行候选", state["error_message"])

    def test_ocr_step_processes_one_new_chunk_and_resumes_from_cache(self) -> None:
        pdf = self.settings.raw_root / "three-pages.pdf"
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=100, height=100)
        with pdf.open("wb") as handle:
            writer.write(handle)
        settings = replace(self.settings, ocr_chunk_pages=2, ocr_token_env="OCR_TEST_TOKEN")
        with patch.dict("os.environ", {"OCR_TEST_TOKEN": "fixture"}), patch(
            "bid_writer_v2.knowledge.ocr._run_job",
            side_effect=lambda _path, _token, offset, _settings: f"chunk-{offset}",
        ) as provider:
            first = ocr_pdf_step(pdf, 701, settings, max_new_chunks=1)
            second = ocr_pdf_step(pdf, 701, settings, max_new_chunks=1)
            third = ocr_pdf_step(pdf, 701, settings, max_new_chunks=1)
        self.assertFalse(first["completed"])
        self.assertEqual((first["completed_chunks"], first["total_chunks"]), (1, 2))
        self.assertTrue(second["completed"])
        self.assertEqual(second["markdown"], "chunk-0\n\nchunk-2")
        self.assertTrue(third["completed"])
        self.assertEqual(provider.call_count, 2)

    def test_uncovered_batch_source_is_requeued_for_individual_review(self) -> None:
        document_id = self._document("coverage.md", "批次覆盖补审", "施工前复核条件，完成后按标准验收。")
        source_id = int((self.db.row("SELECT source_id FROM standard_documents WHERE id=?", (document_id,)) or {})["source_id"])
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            pipeline_run_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,chunk_count,completed_at)
                VALUES (?,?,?,'completed',2,CURRENT_TIMESTAMP)
                """,
                (document_id, "coverage-repair", "input"),
            ).lastrowid)
            conn.execute(
                """
                UPDATE corpus_run_items SET stage='complete',status='terminal',terminal_reason='no_reusable_knowledge',
                    document_id=?,pipeline_run_id=?,checkpoint_json=?,completed_at=CURRENT_TIMESTAMP
                WHERE run_id=? AND source_id=?
                """,
                (document_id, pipeline_run_id, '{"batch_documents": 2}', run["id"], source_id),
            )
        self.assertEqual(self.corpus._requeue_uncovered_batch_sources(run["id"]), 1)
        item = self.db.row("SELECT * FROM corpus_run_items WHERE run_id=? AND source_id=?", (run["id"], source_id))
        self.assertEqual((item["stage"], item["status"], item["pipeline_run_id"], item["attempt_count"]), ("ai", "pending", None, 0))
        self.assertTrue(self.corpus._claim_ai_batch(item)[0]["id"] == item["id"])
        self.assertEqual(len(self.corpus._claim_ai_batch(item)), 1)

    def test_audited_batch_source_is_not_reopened_by_legacy_coverage_repair(self) -> None:
        document_id = self._document("audited.md", "已审计批次", "该资料仅含历史项目专属事实，不能形成跨项目通用知识。")
        source_id = int((self.db.row("SELECT source_id FROM standard_documents WHERE id=?", (document_id,)) or {})["source_id"])
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            pipeline_run_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,chunk_count,completed_at)
                VALUES (?,?,?,'completed',2,CURRENT_TIMESTAMP)
                """,
                (document_id, "audited-coverage", "input"),
            ).lastrowid)
            conn.execute(
                """
                UPDATE corpus_run_items SET stage='complete',status='terminal',terminal_reason='no_reusable_knowledge',
                    document_id=?,pipeline_run_id=?,checkpoint_json=?,completed_at=CURRENT_TIMESTAMP
                WHERE run_id=? AND source_id=?
                """,
                (document_id, pipeline_run_id, '{"batch_documents": 2}', run["id"], source_id),
            )
            for stage in ("extraction", "independent_review"):
                conn.execute(
                    """
                    INSERT INTO knowledge_source_dispositions(
                        pipeline_run_id,document_id,source_id,decision_stage,decision,confidence,reason,
                        actor_type,prompt_key,prompt_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (pipeline_run_id, document_id, source_id, stage, "not_reusable", 0.99,
                     "两阶段均确认只有历史项目专属事实。", "ai", "fixture", "1"),
                )
        self.assertEqual(self.corpus._requeue_uncovered_batch_sources(run["id"]), 0)
        item = self.db.row("SELECT stage,status,terminal_reason FROM corpus_run_items WHERE run_id=? AND source_id=?", (run["id"], source_id))
        self.assertEqual(item, {"stage": "complete", "status": "terminal", "terminal_reason": "no_reusable_knowledge"})

    def test_individual_repairs_do_not_fill_batch_candidate_limit(self) -> None:
        document_ids = [
            self._document(
                f"batch-limit-{index}.md",
                f"批次调度{index}",
                "施工前复核条件，完成后逐项检查并形成记录。" * 3,
            )
            for index in range(14)
        ]
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            for index, document_id in enumerate(document_ids):
                source_id = int((self.db.row("SELECT source_id FROM standard_documents WHERE id=?", (document_id,)) or {})["source_id"])
                checkpoint = '{"requires_individual_ai": true}' if 0 < index < 13 else '{}'
                conn.execute(
                    "UPDATE corpus_run_items SET stage='ai',status='pending',document_id=?,checkpoint_json=? WHERE run_id=? AND source_id=?",
                    (document_id, checkpoint, run["id"], source_id),
                )
        first = self.db.row(
            "SELECT i.* FROM corpus_run_items i WHERE i.run_id=? AND i.document_id=?",
            (run["id"], document_ids[0]),
        )
        claimed = self.corpus._claim_ai_batch(first)
        self.assertEqual({int(item["document_id"]) for item in claimed}, {document_ids[0], document_ids[-1]})

    def test_ai_source_failure_closes_as_insufficient_evidence_not_unreadable(self) -> None:
        source_id = self._source("model-failure.txt", ".txt")
        run = self.corpus.create_run()
        item = self.db.row("SELECT * FROM corpus_run_items WHERE run_id=? AND source_id=?", (run["id"], source_id))
        with self.db.connect() as conn:
            conn.execute("UPDATE corpus_run_items SET stage='ai',status='running',attempt_count=2 WHERE id=?", (item["id"],))
        item = self.db.row("SELECT * FROM corpus_run_items WHERE id=?", (item["id"],))
        self.corpus._handle_failure(item, RuntimeError("invalid candidate output"), service_error=False)
        state = self.db.row("SELECT terminal_reason,checkpoint_json FROM corpus_run_items WHERE id=?", (item["id"],))
        self.assertEqual(state["terminal_reason"], "no_reusable_knowledge")
        self.assertIn("insufficient_evidence_after_model_failures", state["checkpoint_json"])

    def test_failed_individual_pipeline_is_retried_not_closed_as_empty(self) -> None:
        document_id = self._document(
            "failed-pipeline.md",
            "施工质量复核",
            "施工前核对图纸和标准，完成后逐项检查并形成验收记录。" * 5,
        )
        source_id = int((self.db.row("SELECT source_id FROM standard_documents WHERE id=?", (document_id,)) or {})["source_id"])
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_run_items SET stage='ai',status='running',document_id=? WHERE run_id=? AND source_id=?",
                (document_id, run["id"], source_id),
            )
        item = self.db.row("SELECT * FROM corpus_run_items WHERE run_id=? AND source_id=?", (run["id"], source_id))
        self.pipeline.process_document = lambda *_args, **_kwargs: {
            "id": 999,
            "status": "failed",
            "failed_chunks": 0,
            "error_message": "AI未生成候选知识",
        }
        with self.assertRaisesRegex(RuntimeError, "status=failed"):
            self.corpus._process_ai(item)

    def test_two_stage_not_reusable_disposition_closes_only_verified_source(self) -> None:
        first_document_id = self._document(
            "batch-first.md",
            "批次第一份",
            "施工前复核图纸和现场条件，完成后逐项检查并形成验收记录。" * 4,
        )
        second_document_id = self._document(
            "batch-second.md",
            "批次第二份",
            "该文件仅含历史项目专属介绍，不能形成跨项目通用知识。" * 4,
        )
        run = self.corpus.create_run()
        source_rows = self.db.rows(
            "SELECT id,source_id FROM standard_documents WHERE id IN (?,?) ORDER BY id",
            (first_document_id, second_document_id),
        )
        with self.db.connect() as conn:
            pipeline_run_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,chunk_count,completed_at)
                VALUES (?,?,?,'completed',2,CURRENT_TIMESTAMP)
                """,
                (first_document_id, "source-disposition-fixture", "input"),
            ).lastrowid)
            for document in source_rows:
                conn.execute(
                    "UPDATE corpus_run_items SET stage='ai',status='running',document_id=? WHERE run_id=? AND source_id=?",
                    (document["id"], run["id"], document["source_id"]),
                )
            for stage in ("extraction", "independent_review"):
                conn.execute(
                    """
                    INSERT INTO knowledge_source_dispositions(
                        pipeline_run_id,document_id,source_id,decision_stage,decision,confidence,reason,
                        actor_type,prompt_key,prompt_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        pipeline_run_id,
                        second_document_id,
                        source_rows[1]["source_id"],
                        stage,
                        "not_reusable",
                        0.98,
                        "仅含项目专属介绍，未形成可复用技术措施。",
                        "ai",
                        "fixture",
                        "1",
                    ),
                )
        items = self.db.rows(
            "SELECT i.*,s.file_name FROM corpus_run_items i JOIN source_files s ON s.id=i.source_id WHERE i.run_id=? AND i.source_id IN (?,?) ORDER BY i.document_id",
            (run["id"], source_rows[0]["source_id"], source_rows[1]["source_id"]),
        )
        self.pipeline.process_document_batch = lambda *_args, **_kwargs: {"id": pipeline_run_id, "status": "completed"}
        self.corpus._final_review = lambda *_args, **_kwargs: (0, 0, 0)
        self.corpus._process_ai_batch(items)
        states = self.db.rows(
            "SELECT source_id,stage,status,terminal_reason,checkpoint_json FROM corpus_run_items WHERE run_id=? AND source_id IN (?,?) ORDER BY document_id",
            (run["id"], source_rows[0]["source_id"], source_rows[1]["source_id"]),
        )
        self.assertEqual((states[0]["stage"], states[0]["status"]), ("ai", "pending"))
        self.assertIn("requires_individual_ai", states[0]["checkpoint_json"])
        self.assertEqual((states[1]["status"], states[1]["terminal_reason"]), ("terminal", "no_reusable_knowledge"))
        self.assertIn("two_stage_ai_verified_not_reusable", states[1]["checkpoint_json"])

    def test_manual_asset_resolution_requires_explicit_approve_or_exclude(self) -> None:
        source_id = self._source("batch/table.xlsx", ".xlsx", "asset")
        run = self.corpus.create_run()
        self.corpus._legal_task(run["id"], source_id, "asset_license", "授权", "请确认")
        task = self.db.row("SELECT * FROM governance_tasks WHERE run_id=?", (run["id"],))
        with self.assertRaises(ValueError):
            self.corpus.resolve_manual_task(task["id"], "unknown", "说明", None)
        resolved = self.corpus.resolve_manual_task(task["id"], "exclude", "无法确认版权", None)
        self.assertEqual(resolved["status"], "resolved")
        self.assertTrue(resolved["resolution"].startswith("exclude:"))

    def test_zip_path_traversal_is_blocked(self) -> None:
        archive = self.settings.raw_root / "unsafe.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escape.txt", "blocked")
        with self.assertRaisesRegex(RuntimeError, "路径穿越"):
            self.knowledge._expand_archive(archive, 99, "a" * 64)

    def test_zip_bomb_ratio_is_blocked(self) -> None:
        archive = self.settings.raw_root / "bomb.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            handle.writestr("huge.txt", b"0" * 2_000_000)
        with self.assertRaisesRegex(RuntimeError, "压缩炸弹"):
            self.knowledge._expand_archive(archive, 100, "b" * 64)

    def test_normalize_text_removes_database_illegal_controls(self) -> None:
        self.assertEqual(normalize_text("前文\x00中段\x07后文\n保留"), "前文中段后文\n保留")

    def test_docx_xml_fallback_recovers_legacy_document_text(self) -> None:
        archive = self.settings.raw_root / "legacy.docx"
        archive.parent.mkdir(parents=True, exist_ok=True)
        document_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>可恢复的正文</w:t></w:r></w:p></w:body>
        </w:document>"""
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("word/document.xml", document_xml)
        self.assertEqual(_parse_docx_xml_fallback(archive), ["可恢复的正文"])

    def test_docx_grid_offset_error_uses_xml_fallback(self) -> None:
        archive = self.settings.raw_root / "broken-grid.docx"
        archive.parent.mkdir(parents=True, exist_ok=True)
        document_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>recoverable table text</w:t></w:r></w:p></w:body>
        </w:document>"""
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("word/document.xml", document_xml)
        with patch("bid_writer_v2.knowledge.parsers.Document", side_effect=ValueError("no `tc` element at grid_offset=22")):
            parsed = _parse_docx(archive, 901, self.settings)
        self.assertIn("recoverable table text", parsed.markdown)

    def test_legacy_doc_antiword_fallback_normalizes_text(self) -> None:
        source = self.settings.raw_root / "legacy.doc"
        source.write_bytes(b"fixture")
        completed = subprocess.CompletedProcess([], 0, b"reusable construction management content with checks and acceptance", b"")
        with patch("bid_writer_v2.knowledge.parsers.shutil.which", return_value="/usr/bin/antiword"), patch(
            "bid_writer_v2.knowledge.parsers.subprocess.run", return_value=completed
        ):
            parsed = _parse_legacy_doc_text(source)
        self.assertEqual(parsed.parser, "antiword")
        self.assertIn("checks and acceptance", parsed.markdown)

    def test_manual_tasks_are_grouped_by_source_batch(self) -> None:
        first = self._source("01_原始标书库/编号项目/001/图片/a.png", ".png", "asset")
        second = self._source("01_原始标书库/编号项目/001/附图/b.png", ".png", "asset")
        run = self.corpus.create_run()
        self.corpus._legal_task(run["id"], first, "asset_license", "授权", "请确认")
        self.corpus._legal_task(run["id"], second, "asset_license", "授权", "请确认")
        tasks = self.db.rows("SELECT id FROM governance_tasks WHERE run_id=?", (run["id"],))
        links = self.db.rows("SELECT source_id FROM governance_task_sources WHERE task_id=?", (tasks[0]["id"],))
        self.assertEqual(len(tasks), 1)
        self.assertEqual({row["source_id"] for row in links}, {first, second})

    def test_manual_task_list_defaults_to_latest_run(self) -> None:
        first_source = self._source("old-license.png", ".png", "asset")
        first = self.corpus.create_run()
        self.corpus._legal_task(first["id"], first_source, "asset_license", "old", "old task")
        self.corpus.cancel(first["id"])
        second = self.corpus.create_run()
        second_source = self._source("new-license.png", ".png", "asset")
        self.corpus._legal_task(second["id"], second_source, "asset_license", "new", "new task")
        tasks = self.corpus.list_manual_tasks("open")
        self.assertTrue(tasks)
        self.assertEqual({task["run_id"] for task in tasks}, {second["id"]})

    def test_service_fuse_schedules_automatic_recovery_probe(self) -> None:
        source_id = self._source("fuse.txt", ".txt")
        run = self.corpus.create_run()
        dispatched: list[tuple[int, int, int, str]] = []
        self.corpus.dispatch = lambda run_id, delay, desired, stage: dispatched.append((run_id, delay, desired, stage))
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_runs SET checkpoint_json=? WHERE id=?",
                ('{"service_health":{"ai":{"consecutive_errors":4,"recent_results":[{"ok":false}]}}}', run["id"]),
            )
        self.corpus._record_result(run["id"], False, "HTTP 503", service_stage="ai")
        state = self.db.row("SELECT status,pause_reason,checkpoint_json FROM corpus_runs WHERE id=?", (run["id"],))
        self.assertEqual(state["status"], "paused")
        self.assertTrue(state["pause_reason"].startswith("外部服务错误"))
        self.assertIn('"service_pause_stage": "ai"', state["checkpoint_json"])
        self.assertEqual(dispatched, [(run["id"], 15 * 60 * 1000, 1, "__recovery__")])

    def test_other_stage_success_does_not_dilute_ai_failure_window(self) -> None:
        self._source("stage-health.txt", ".txt")
        run = self.corpus.create_run()
        self.corpus._record_result(run["id"], False, "HTTP 429", service_stage="ai")
        self.corpus._record_result(run["id"], True, "", service_stage="ocr")
        self.corpus._record_result(run["id"], True, "")

        state = self.corpus.get_run(run["id"])
        health = state["checkpoint"]["service_health"]
        self.assertEqual(health["ai"]["consecutive_errors"], 1)
        self.assertEqual(len(health["ai"]["recent_results"]), 1)
        self.assertEqual(health["ocr"]["consecutive_errors"], 0)

    def test_failed_ai_recovery_probe_keeps_run_paused(self) -> None:
        self._source("recovery-probe.txt", ".txt")
        run = self.corpus.create_run()
        dispatched: list[tuple[int, int, int, str]] = []
        self.corpus.dispatch = lambda run_id, delay, desired, stage: dispatched.append((run_id, delay, desired, stage))
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_runs SET status='paused',pause_reason='外部服务错误达到熔断阈值: ai',checkpoint_json=?,policy_json=? WHERE id=?",
                (
                    '{"service_pause_stage":"ai"}',
                    '{"disk_min_bytes":0,"disk_min_ratio":0}',
                    run["id"],
                ),
            )
        self.runtime.llm.generate = lambda *_args, **_kwargs: {"content": "", "error": "HTTP 503"}  # type: ignore[method-assign]

        result = self.corpus.run_tick(run["id"], preferred_stage="__recovery__")

        self.assertEqual(result["status"], "paused")
        self.assertIn("恢复探针未通过", result["pause_reason"])
        self.assertEqual(dispatched, [(run["id"], 15 * 60 * 1000, 1, "__recovery__")])

    def test_ai_claim_respects_single_stage_concurrency(self) -> None:
        first = self._source("ai-running.txt", ".txt")
        second = self._source("ai-pending.txt", ".txt")
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_run_items SET stage='ai',status='running' WHERE run_id=? AND source_id=?",
                (run["id"], first),
            )
            conn.execute(
                "UPDATE corpus_run_items SET stage='ai',status='pending' WHERE run_id=? AND source_id=?",
                (run["id"], second),
            )

        self.assertIsNone(self.corpus._claim_next_item(run["id"], "ai"))
        state = self.db.row(
            "SELECT status,attempt_count FROM corpus_run_items WHERE run_id=? AND source_id=?",
            (run["id"], second),
        )
        self.assertEqual(state, {"status": "pending", "attempt_count": 0})

    def test_successful_ai_recovery_probe_releases_pre_fuse_claims(self) -> None:
        source_id = self._source("recovered-ai.txt", ".txt")
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE corpus_run_items SET stage='ai',status='running',updated_at=datetime('now','-20 minutes')
                WHERE run_id=? AND source_id=?
                """,
                (run["id"], source_id),
            )
            conn.execute(
                "UPDATE corpus_runs SET status='paused',pause_reason='外部服务错误达到熔断阈值: ai',checkpoint_json=?,policy_json=? WHERE id=?",
                (
                    '{"service_pause_stage":"ai"}',
                    '{"disk_min_bytes":0,"disk_min_ratio":0}',
                    run["id"],
                ),
            )
        self.runtime.llm.generate = lambda *_args, **_kwargs: {"content": "OK", "error": ""}  # type: ignore[method-assign]

        with patch.object(self.corpus, "_claim_next_item", return_value=None):
            result = self.corpus.run_tick(run["id"], preferred_stage="__recovery__")

        item = self.db.row(
            "SELECT status,error_code,next_retry_at FROM corpus_run_items WHERE run_id=? AND source_id=?",
            (run["id"], source_id),
        )
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["checkpoint"]["service_recovery_probe"]["status"], "passed")
        self.assertEqual(item, {"status": "retrying", "error_code": "service_recovery", "next_retry_at": None})


    def test_damaged_run_ledger_can_be_rebuilt_from_persisted_results(self) -> None:
        source_id = self._source("recovery.txt", ".txt")
        run = self.corpus.create_run()
        self.corpus._legal_task(run["id"], source_id, "credentials", "password", "user credential required")
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_run_items SET stage='complete',status='terminal',terminal_reason='duplicate' WHERE run_id=?",
                (run["id"],),
            )
        rebuilt = self.corpus.rebuild_run_from_persisted_results(run["id"])
        old = self.db.row("SELECT status,stage FROM corpus_runs WHERE id=?", (run["id"],))
        item = self.db.row("SELECT stage,status FROM corpus_run_items WHERE run_id=? AND source_id=?", (rebuilt["id"], source_id))
        tasks = self.db.rows("SELECT task_type,status FROM governance_tasks WHERE run_id=?", (rebuilt["id"],))
        self.assertEqual(old["status"], "cancelled")
        self.assertEqual(old["stage"], "operator_recovery")
        self.assertEqual((item["stage"], item["status"]), ("normalize", "pending"))
        self.assertEqual(tasks, [{"task_type": "credentials", "status": "open"}])

    def test_rebuild_preserves_two_stage_verified_exclusion(self) -> None:
        document_id = self._document("recovered-disposition.md", "已复核排除", "该资料仅含历史项目专属事实，不能形成通用知识。")
        source_id = int((self.db.row("SELECT source_id FROM standard_documents WHERE id=?", (document_id,)) or {})["source_id"])
        run = self.corpus.create_run()
        with self.db.connect() as conn:
            pipeline_run_id = int(conn.execute(
                """
                INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,status,chunk_count,completed_at)
                VALUES (?,?,?,'completed',2,CURRENT_TIMESTAMP)
                """,
                (document_id, "recovery-disposition", "input"),
            ).lastrowid)
            for stage in ("extraction", "independent_review"):
                conn.execute(
                    """
                    INSERT INTO knowledge_source_dispositions(
                        pipeline_run_id,document_id,source_id,decision_stage,decision,confidence,reason,
                        actor_type,prompt_key,prompt_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (pipeline_run_id, document_id, source_id, stage, "not_reusable", 0.99,
                     "两阶段均确认只有历史项目专属事实。", "ai", "fixture", "1"),
                )
        rebuilt = self.corpus.rebuild_run_from_persisted_results(run["id"])
        item = self.db.row(
            "SELECT stage,status,terminal_reason,pipeline_run_id,checkpoint_json FROM corpus_run_items WHERE run_id=? AND source_id=?",
            (rebuilt["id"], source_id),
        )
        self.assertEqual((item["stage"], item["status"], item["terminal_reason"]), ("complete", "terminal", "no_reusable_knowledge"))
        self.assertEqual(item["pipeline_run_id"], pipeline_run_id)
        self.assertIn("source_disposition_recovered", item["checkpoint_json"])

    def test_deployment_restart_does_not_consume_source_retry_budget(self) -> None:
        source_id = self._source("restart.txt", ".txt")
        run = self.corpus.create_run()
        item = self.db.row("SELECT * FROM corpus_run_items WHERE run_id=? AND source_id=?", (run["id"], source_id))
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_run_items SET status='running',attempt_count=3,error_code='image_rollout_23' WHERE id=?",
                (item["id"],),
            )
        item = self.db.row("SELECT * FROM corpus_run_items WHERE id=?", (item["id"],))
        self.corpus._handle_failure(item, RuntimeError("parser failed"), service_error=False)
        state = self.db.row("SELECT status,attempt_count,terminal_reason FROM corpus_run_items WHERE id=?", (item["id"],))
        self.assertEqual(state["status"], "retrying")
        self.assertEqual(state["attempt_count"], 1)
        self.assertEqual(state["terminal_reason"], "")


if __name__ == "__main__":
    unittest.main()
