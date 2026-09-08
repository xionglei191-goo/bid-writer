from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from bid_writer_v2.database import Database
from bid_writer_v2.evidence import EvidenceService
from bid_writer_v2.production.service import ProductionService
from bid_writer_v2.utils import content_hash


class EvidenceConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="evidence-concurrency-")
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        self.db.migrate()
        self.evidence = EvidenceService(self.db)
        self.production = ProductionService(self.db, Mock(), Mock(), evidence=self.evidence, storage=Mock())
        self.older = "施工前组织现场复核与图纸会审，安排技术交底并形成过程记录。"
        self.newer = "本项目混凝土强度必须达到C60，基坑开挖深度为12米，承重结构施工必须按此参数实施。"
        with self.db.connect() as conn:
            self.project_id = int(conn.execute("INSERT INTO projects(name) VALUES ('证据并发测试')").lastrowid)
            self.section_id = int(conn.execute(
                "INSERT INTO project_sections(project_id,order_no,title) VALUES (?,1,'施工部署')", (self.project_id,),
            ).lastrowid)
            self.draft_id = int(conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,content_hash) VALUES (?,?,?,?)",
                (self.project_id, self.section_id, "初始草稿", content_hash("初始草稿")),
            ).lastrowid)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def new_run(self, content: str) -> int:
        return self.evidence.create_generation_run(
            self.project_id, self.section_id, content_hash(content), "manual-edit", "1", "1", None, [],
        )

    def test_older_edit_cannot_replace_newer_high_risk_evidence(self) -> None:
        original = self.evidence.analyze_draft
        newer_claims = []

        def interleaved(run_id, draft_id, content, sources):
            if content == self.older:
                self.production.update_draft(draft_id, self.newer)
                newer_claims.extend(self.evidence.list_claims(draft_id))
            return original(run_id, draft_id, content, sources)

        with patch.object(self.evidence, "analyze_draft", side_effect=interleaved):
            result = self.production.update_draft(self.draft_id, self.older)

        draft = self.db.row("SELECT content,evidence_status FROM project_drafts WHERE id=?", (self.draft_id,))
        self.assertEqual(draft, {"content": self.newer, "evidence_status": "blocked"})
        self.assertEqual(self.evidence.list_claims(self.draft_id), newer_claims)
        self.assertGreater(self.evidence.metrics(self.project_id)["high_unsupported"], 0)
        self.assertTrue(result["analysis_stale"])
        self.assertEqual(result["evidence_status"], "stale")
        runs = self.db.rows("SELECT input_hash,status FROM generation_runs ORDER BY id")
        self.assertEqual(runs, [
            {"input_hash": content_hash(self.older), "status": "invalidated"},
            {"input_hash": content_hash(self.newer), "status": "completed"},
        ])
        with self.assertRaisesRegex(ValueError, "高风险"):
            self.production.confirm_draft(self.draft_id, "实际复核人")

    def test_stale_check_uses_current_body_even_if_stored_hash_is_outdated(self) -> None:
        self.production.update_draft(self.draft_id, self.newer)
        claims = self.evidence.list_claims(self.draft_id)
        with self.db.connect() as conn:
            conn.execute("UPDATE project_drafts SET content_hash=? WHERE id=?", (content_hash(self.older), self.draft_id))
        result = self.evidence.analyze_draft(self.new_run(self.older), self.draft_id, self.older, [])
        self.assertTrue(result["stale"])
        self.assertEqual(result["current_content_hash"], content_hash(self.newer))
        self.assertEqual(self.evidence.list_claims(self.draft_id), claims)
        self.assertEqual(self.db.row("SELECT evidence_status FROM project_drafts WHERE id=?", (self.draft_id,))["evidence_status"], "blocked")

    def test_sqlite_write_lock_prevents_edit_between_hash_read_and_claim_replacement(self) -> None:
        self.production.update_draft(self.draft_id, self.newer)
        run_id = self.new_run(self.newer)
        attempted = []
        original_connect = self.db.connect

        @contextmanager
        def hook_body_read():
            with original_connect() as connection:
                proxy = Mock(wraps=connection)

                def execute(sql, params=()):
                    cursor = connection.execute(sql, params)
                    if sql.startswith("SELECT content FROM project_drafts"):
                        def fetchone():
                            row = cursor.fetchone()
                            with closing(sqlite3.connect(self.db.path, timeout=0)) as competing:
                                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                                    competing.execute("UPDATE project_drafts SET content=? WHERE id=?", (self.older, self.draft_id))
                            attempted.append(True)
                            return row
                        return Mock(fetchone=fetchone)
                    return cursor

                proxy.execute.side_effect = execute
                yield proxy

        with patch.object(self.db, "connect", side_effect=hook_body_read):
            result = self.evidence.analyze_draft(run_id, self.draft_id, self.newer, [{"content": self.older}])
        self.assertTrue(attempted)
        self.assertFalse(result["stale"])
        self.assertEqual(result["evidence_status"], "blocked")
        self.assertEqual(self.db.row("SELECT content FROM project_drafts WHERE id=?", (self.draft_id,))["content"], self.newer)


if __name__ == "__main__":
    unittest.main()
