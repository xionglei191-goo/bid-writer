from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from bid_writer_v2.database import Database
from bid_writer_v2.production.service import ProductionService
from bid_writer_v2.utils import content_hash


class ConfirmationConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="confirmation-concurrency-")
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "fixture.sqlite3")
        self.db.migrate()
        self.production = ProductionService(self.db, Mock(), Mock(), llm=Mock(), storage=Mock(), audit=Mock())
        self.older = "施工前组织现场复核与图纸会审，安排技术交底并形成过程记录。"
        self.newer = "施工期间组织现场条件复核，对发现的偏差安排复查并保存处理记录。"
        with self.db.connect() as conn:
            self.project_id = int(conn.execute(
                "INSERT INTO projects(name,region,profile_json) VALUES ('医院门诊综合楼施工组织设计','原地区',?)",
                (json.dumps({"bidder_name": "华建建设工程有限公司"}, ensure_ascii=False),),
            ).lastrowid)
            self.section_id = int(conn.execute(
                "INSERT INTO project_sections(project_id,order_no,title) VALUES (?,1,'施工部署')", (self.project_id,),
            ).lastrowid)
            self.draft_id = int(conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,content_hash,evidence_status) VALUES (?,?,?,?,'not_applicable')",
                (self.project_id, self.section_id, self.older, content_hash(self.older)),
            ).lastrowid)
        self.production.evidence.refresh_project_evidence(self.project_id)

    def finalize(self) -> str:
        self.production.confirm_draft(self.draft_id, "陈工", target_hash=content_hash(self.older))
        project_hash = self.production.preview_project(self.project_id)["project_hash"]
        confirmed = self.production.confirm_final_review(self.project_id, project_hash, "陈工", True, True)
        self.assertTrue(confirmed["confirmation"]["valid"])
        return project_hash

    @contextmanager
    def intercept_read(self, prefix: str, callback):
        original_connect = self.db.connect
        seen = []

        @contextmanager
        def connect():
            with original_connect() as connection:
                class ConnectionProxy:
                    def __getattr__(self, name):
                        return getattr(connection, name)

                    def execute(self, sql, params=()):
                        cursor = connection.execute(sql, params)
                        if sql.startswith(prefix) and not seen:
                            def fetchone():
                                row = cursor.fetchone()
                                seen.append(True)
                                callback()
                                return row
                            return Mock(fetchone=fetchone)
                        return cursor
                yield ConnectionProxy()

        with patch.object(self.db, "connect", side_effect=connect):
            yield seen

    def assert_competing_write_blocked(self, sql: str, params=()) -> None:
        with closing(sqlite3.connect(self.db.path, timeout=0)) as competing:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                competing.execute(sql, params)

    def test_chapter_review_locks_read_through_approval_then_later_edit_invalidates_it(self) -> None:
        old_project_hash = self.finalize()
        def concurrent_edit():
            self.assert_competing_write_blocked(
                "UPDATE project_drafts SET content=?,content_hash=?,status='draft' WHERE id=?",
                (self.newer, content_hash(self.newer), self.draft_id),
            )
        with self.intercept_read("SELECT * FROM project_drafts WHERE id=", concurrent_edit) as seen:
            approved = self.production.confirm_draft(self.draft_id, "李工", target_hash=content_hash(self.older))
        self.assertTrue(seen)
        self.assertEqual(approved["target_hash"], content_hash(self.older))
        self.production.update_draft(self.draft_id, self.newer)
        draft = self.db.row("SELECT content,content_hash,status FROM project_drafts WHERE id=?", (self.draft_id,))
        self.assertEqual(draft, {"content": self.newer, "content_hash": content_hash(self.newer), "status": "draft"})
        preview = self.production.preview_project(self.project_id)
        self.assertNotEqual(preview["project_hash"], old_project_hash)
        self.assertFalse(preview["confirmation"]["valid"])
        with self.assertRaisesRegex(ValueError, "章节内容已变化"):
            self.production.confirm_draft(self.draft_id, "李工", target_hash=content_hash(self.older))
        self.assertEqual(self.db.row("SELECT content_hash FROM project_drafts WHERE id=?", (self.draft_id,))["content_hash"], content_hash(self.newer))

    def test_chapter_review_uses_saved_body_even_when_cached_hash_is_old(self) -> None:
        self.finalize()
        with self.db.connect() as conn:
            conn.execute("UPDATE project_drafts SET content=?,status='draft' WHERE id=?", (self.newer, self.draft_id))
        before = self.db.rows("SELECT * FROM draft_review_decisions")
        with self.assertRaisesRegex(ValueError, "章节内容已变化"):
            self.production.confirm_draft(self.draft_id, "李工", target_hash=content_hash(self.older))
        self.assertEqual(self.db.rows("SELECT * FROM draft_review_decisions"), before)
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])
        result = self.production.confirm_draft(self.draft_id, "李工", target_hash=content_hash(self.newer))
        self.assertEqual(result["target_hash"], content_hash(self.newer))
        self.assertEqual(self.db.row("SELECT content_hash FROM project_drafts WHERE id=?", (self.draft_id,))["content_hash"], content_hash(self.newer))
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])

    def test_final_review_locks_project_read_through_version_check_and_write(self) -> None:
        old_hash = self.production.preview_project(self.project_id)["project_hash"]
        def concurrent_region_edit():
            self.assert_competing_write_blocked("UPDATE projects SET region='新地区' WHERE id=?", (self.project_id,))
        with self.intercept_read("SELECT * FROM projects WHERE id=", concurrent_region_edit) as seen:
            result = self.production.confirm_final_review(self.project_id, old_hash, "陈工", True, True)
        self.assertTrue(seen)
        self.assertTrue(result["confirmation"]["valid"])
        self.production.update_project(self.project_id, {"region": "新地区"})
        before = self.db.row("SELECT region,profile_json FROM projects WHERE id=?", (self.project_id,))
        with self.assertRaisesRegex(ValueError, "项目内容已变化"):
            self.production.confirm_final_review(self.project_id, old_hash, "李工", True, True)
        self.assertEqual(self.db.row("SELECT region,profile_json FROM projects WHERE id=?", (self.project_id,)), before)
        self.assertEqual(before["region"], "新地区")
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])

    def test_final_review_locks_draft_body_until_whole_project_approval_is_saved(self) -> None:
        old_hash = self.production.preview_project(self.project_id)["project_hash"]
        def concurrent_body_edit():
            self.assert_competing_write_blocked(
                "UPDATE project_drafts SET content=?,content_hash=? WHERE id=?",
                (self.newer, content_hash(self.newer), self.draft_id),
            )
        with self.intercept_read("SELECT * FROM project_drafts WHERE section_id=", concurrent_body_edit) as seen:
            approved = self.production.confirm_final_review(self.project_id, old_hash, "陈工", True, True)
        self.assertTrue(seen)
        self.assertEqual(approved["project_hash"], old_hash)
        self.assertTrue(approved["confirmation"]["valid"])

    def test_project_merge_reads_after_lock_and_preserves_another_completed_update(self) -> None:
        original_lock = self.production._lock_project_for_update
        injected = []
        def competing_update_before_lock(conn, project_id):
            if not injected:
                injected.append(True)
                with closing(sqlite3.connect(self.db.path, timeout=0)) as competing:
                    competing.execute("UPDATE projects SET region='新地区' WHERE id=?", (project_id,))
                    competing.commit()
            original_lock(conn, project_id)
        with patch.object(self.production, "_lock_project_for_update", side_effect=competing_update_before_lock):
            result = self.production.update_project(self.project_id, {"profile": {"special_notes": "保留已完成的资料更新"}})
        self.assertEqual(result["region"], "新地区")
        self.assertEqual(result["profile"]["special_notes"], "保留已完成的资料更新")

    def test_final_review_rejects_update_that_completed_before_project_lock(self) -> None:
        old_hash = self.production.preview_project(self.project_id)["project_hash"]
        original_lock = self.production._lock_project_for_update
        def update_before_lock(conn, project_id):
            with closing(sqlite3.connect(self.db.path, timeout=0)) as competing:
                competing.execute("UPDATE projects SET region='新地区' WHERE id=?", (project_id,))
                competing.commit()
            original_lock(conn, project_id)
        with patch.object(self.production, "_lock_project_for_update", side_effect=update_before_lock):
            with self.assertRaisesRegex(ValueError, "项目内容已变化"):
                self.production.confirm_final_review(self.project_id, old_hash, "陈工", True, True)
        current = self.production.get_project(self.project_id)
        self.assertEqual(current["region"], "新地区")
        self.assertNotIn("delivery_confirmation", current["profile"])


if __name__ == "__main__":
    unittest.main()
