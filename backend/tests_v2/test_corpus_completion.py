from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.audit import AuditService
from bid_writer_v2.database import Database
from bid_writer_v2.evaluation import RetrievalEvaluationService
from bid_writer_v2.knowledge.corpus import CorpusCompletionService
from bid_writer_v2.knowledge.parsers import _parse_docx_xml_fallback
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

    def _source(self, name: str, extension: str, status: str = "discovered", duplicate_of: int | None = None) -> int:
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
                (str(path), name, path.name, extension, 7, content_hash(name), path.stem, "raw", duplicate_of, status),
            ).lastrowid)

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

    def test_service_fuse_schedules_automatic_recovery_probe(self) -> None:
        source_id = self._source("fuse.txt", ".txt")
        run = self.corpus.create_run()
        dispatched: list[tuple[int, int, int, str]] = []
        self.corpus.dispatch = lambda run_id, delay, desired, stage: dispatched.append((run_id, delay, desired, stage))
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE corpus_runs SET consecutive_errors=4,recent_results_json=? WHERE id=?",
                ('[{"ok": false}]', run["id"]),
            )
        self.corpus._record_result(run["id"], False, "HTTP 503")
        state = self.db.row("SELECT status,pause_reason FROM corpus_runs WHERE id=?", (run["id"],))
        self.assertEqual(state["status"], "paused")
        self.assertTrue(state["pause_reason"].startswith("外部服务错误"))
        self.assertEqual(dispatched, [(run["id"], 15 * 60 * 1000, 1, "__recovery__")])


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
