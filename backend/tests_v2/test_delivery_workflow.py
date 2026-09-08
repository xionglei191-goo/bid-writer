from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from bid_writer_v2.auth import AuthService
from bid_writer_v2.utils import content_hash


# app.py constructs its module-level ASGI app on import. Isolate that bootstrap
# too, not just the per-test services, so importing this test cannot migrate the
# operator's default database or connect to their deployed infrastructure.
with tempfile.TemporaryDirectory(prefix="delivery-test-bootstrap-") as bootstrap:
    bootstrap_root = Path(bootstrap)
    with patch.dict(os.environ, {
        "BID_WRITER_WORKSPACE": bootstrap, "BID_WRITER_APP_ROOT": str(bootstrap_root / "app"),
        "BID_WRITER_DATA": str(bootstrap_root / "data"), "BID_WRITER_DB": str(bootstrap_root / "data" / "bootstrap.sqlite3"),
        "BID_WRITER_RAW": str(bootstrap_root / "raw"), "BID_WRITER_KNOWLEDGE": str(bootstrap_root / "knowledge"),
        "BID_WRITER_DELIVERY": str(bootstrap_root / "delivery"), "BID_WRITER_EXPORT": str(bootstrap_root / "exports"),
        "BID_WRITER_QA": str(bootstrap_root / "qa"), "BID_WRITER_UPLOADS": str(bootstrap_root / "uploads"),
        "BID_WRITER_CACHE": str(bootstrap_root / "cache"), "BID_WRITER_DATABASE_URL": "", "BID_WRITER_REDIS_URL": "",
        "BID_WRITER_QDRANT_URL": "", "BID_WRITER_MINIO_ENDPOINT": "", "BID_WRITER_AUTH_ENABLED": "0",
        "BID_WRITER_BACKGROUND_JOBS": "0",
    }):
        from bid_writer_v2.app import create_app
        from test_v2_workflow import build_settings


class DeliveryWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = build_settings(self.root)
        self.app = create_app(self.settings)
        self.production = self.app.state.production
        self.db = self.app.state.db
        self.client = TestClient(self.app)
        self.project = self.production.create_project({"name": "医院门诊综合楼施工组织设计", "industry": "医院"})
        self.project_id = self.project["id"]
        self.content = "# 施工总体部署\n\n施工前组织现场复核与图纸会审，安排技术交底并形成过程记录。"
        with self.db.connect() as conn:
            self.section_id = int(conn.execute(
                "INSERT INTO project_sections(project_id,order_no,title) VALUES (?,1,'施工总体部署')",
                (self.project_id,),
            ).lastrowid)
            self.draft_id = int(conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,content_hash,version_no) VALUES (?,?,?,?,1)",
                (self.project_id, self.section_id, self.content, content_hash(self.content)),
            ).lastrowid)
        analysis_run = self.production.evidence.create_generation_run(
            self.project_id, self.section_id, content_hash(self.content), "fixture", "1", "1", None, [],
        )
        self.production.evidence.analyze_draft(analysis_run, self.draft_id, self.content, [])

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def finalize(self) -> dict:
        self.production.confirm_draft(self.draft_id, "陈工")
        self.production.update_project(self.project_id, {"profile": {"bidder_name": "华建建设工程有限公司"}})
        preview = self.client.get(f"/api/projects/{self.project_id}/preview").json()
        response = self.client.post(f"/api/projects/{self.project_id}/final-review", json={
            "project_hash": preview["project_hash"], "professional_reviewer": "陈工",
            "compliance_confirmed": True, "manual_finalized": True,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_review_export_download_and_formal_gate(self) -> None:
        quality = self.production.quality_gate(self.project_id)
        self.assertTrue(quality["review_ready"])
        self.assertFalse(quality["formal_ready"])
        blocked = self.client.post(f"/api/projects/{self.project_id}/export", json={"format": "docx", "mode": "formal", "background": False})
        self.assertEqual(blocked.status_code, 409)
        response = self.client.post(f"/api/projects/{self.project_id}/export", json={"format": "docx", "mode": "review", "background": False})
        self.assertEqual(response.status_code, 200, response.text)
        artifact = response.json()
        self.assertNotIn("file_path", artifact)
        self.assertTrue(artifact["object_key"].endswith(".docx"))
        downloaded = self.client.get(artifact["download_url"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("attachment", downloaded.headers["content-disposition"])
        self.assertEqual(downloaded.headers["cache-control"], "private, no-store")
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            self.assertIn("word/document.xml", archive.namelist())
        history = self.client.get(f"/api/projects/{self.project_id}/deliveries").json()
        self.assertEqual(history[0]["delivery_id"], artifact["delivery_id"])
        self.assertEqual(history[0]["mode"], "review")
        self.assertTrue(history[0]["current"])
        self.assertTrue(history[0]["available"])
        self.assertEqual(self.client.get(f"/api/projects/999/deliveries/{artifact['delivery_id']}/download").status_code, 404)

    def test_final_review_requires_current_preview_and_user_confirmations(self) -> None:
        before = self.client.get(f"/api/projects/{self.project_id}/preview").json()
        self.assertIn(self.content, before["markdown"])
        for reviewer, compliance, finalized in [("", True, True), ("陈工", False, True), ("陈工", True, False)]:
            response = self.client.post(f"/api/projects/{self.project_id}/final-review", json={
                "project_hash": before["project_hash"], "professional_reviewer": reviewer,
                "compliance_confirmed": compliance, "manual_finalized": finalized,
            })
            self.assertIn(response.status_code, (409, 422))
        self.production.update_project(self.project_id, {"region": "河南"})
        stale = self.client.post(f"/api/projects/{self.project_id}/final-review", json={
            "project_hash": before["project_hash"], "professional_reviewer": "陈工",
            "compliance_confirmed": True, "manual_finalized": True,
        })
        self.assertEqual(stale.status_code, 409)
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])
        finalized = self.finalize()
        self.assertTrue(finalized["confirmation"]["valid"])
        self.assertTrue(self.production.quality_gate(self.project_id)["formal_ready"])
        exported = self.production.export_project(self.project_id, "markdown", "formal")
        self.assertEqual(self.client.get(exported["download_url"]).status_code, 200)

    def test_edit_invalidates_chapter_and_whole_document_confirmation(self) -> None:
        before = self.finalize()
        exported = self.production.export_project(self.project_id, "markdown", "formal")
        original = self.client.get(exported["download_url"]).content
        changed_content = self.content + "\n\n施工期间安排资料整理并记录日常检查情况。"
        self.production.update_draft(self.draft_id, changed_content)
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])
        with self.assertRaisesRegex(ValueError, "章节内容已变化"):
            self.production.confirm_draft(self.draft_id, "陈工", target_hash=content_hash(self.content))
        self.production.confirm_draft(self.draft_id, "陈工")
        self.assertFalse(self.production.quality_gate(self.project_id)["formal_ready"])
        with self.assertRaisesRegex(ValueError, "项目内容已变化"):
            self.production.confirm_final_review(self.project_id, before["project_hash"], "陈工", True, True)
        history = self.production.list_deliveries(self.project_id)
        self.assertFalse(history[0]["current"])
        self.assertEqual(history[0]["status"], "invalidated")
        self.assertEqual(self.client.get(exported["download_url"]).content, original)
        self.finalize()
        self.assertTrue(self.production.quality_gate(self.project_id)["formal_ready"])

    def test_project_fact_or_reviewer_edit_invalidates_final_confirmation(self) -> None:
        self.finalize()
        self.production.update_project(self.project_id, {"profile": {"duration": "180 天"}})
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])
        self.finalize()
        self.production.update_project(self.project_id, {"profile": {"professional_reviewer": "李工"}})
        self.assertFalse(self.production.preview_project(self.project_id)["confirmation"]["valid"])

    def test_repeated_exports_are_immutable_and_tampering_is_rejected(self) -> None:
        first = self.production.export_project(self.project_id, "markdown", "review")
        second = self.production.export_project(self.project_id, "markdown", "review")
        self.assertNotEqual(first["file_path"], second["file_path"])
        self.assertNotEqual(first["manifest_hash"], second["manifest_hash"])
        Path(first["file_path"]).write_text("local path overwritten", encoding="utf-8")
        original = self.client.get(first["download_url"])
        self.assertEqual(original.status_code, 200)
        self.assertIn(self.content, original.content.decode("utf-8").replace("\r\n", "\n"))
        (self.production.storage.local_root / first["object_key"]).write_bytes(b"tampered")
        self.assertEqual(self.client.get(first["download_url"]).status_code, 409)
        self.assertEqual(self.client.get(second["download_url"]).status_code, 200)

    def test_partial_confirmation_does_not_reapprove_a_stale_whole_document(self) -> None:
        self.finalize()
        self.production.update_project(self.project_id, {"region": "河南"})
        self.production.update_project(self.project_id, {"profile": {"compliance_confirmed": True}})
        confirmation = self.production.preview_project(self.project_id)["confirmation"]
        self.assertFalse(confirmation["valid"])
        self.assertTrue(confirmation["compliance_confirmed"])
        self.assertFalse(confirmation["manual_finalized"])
        self.assertFalse(self.production.quality_gate(self.project_id)["formal_ready"])

    def test_export_refuses_changes_or_revoked_confirmation_during_rendering(self) -> None:
        write_docx = self.production._write_docx
        for change in ({"region": "河南"}, {"profile": {"manual_finalized": False}}):
            with self.subTest(change=change):
                self.finalize()

                def render_and_change(project: dict, path: Path, mode: str = "formal") -> None:
                    write_docx(project, path, mode=mode)
                    self.production.update_project(self.project_id, change)

                with patch.object(self.production, "_write_docx", side_effect=render_and_change):
                    with self.assertRaisesRegex(ValueError, "导出期间"):
                        self.production.export_project(self.project_id, "docx", "formal")
                self.assertEqual(self.production.list_deliveries(self.project_id), [])

    def test_download_never_reads_a_path_outside_the_export_root(self) -> None:
        secret = self.root / "outside.txt"
        secret.write_text("private fixture", encoding="utf-8")
        with self.db.connect() as conn:
            delivery_id = int(conn.execute(
                "INSERT INTO deliveries(project_id,format,file_path,quality_json) VALUES (?,'review_markdown',?,?)",
                (self.project_id, str(secret), json.dumps({"_delivery_file": {"file_name": secret.name, "sha256": content_hash("private fixture")}})),
            ).lastrowid)
        response = self.client.get(f"/api/projects/{self.project_id}/deliveries/{delivery_id}/download")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private fixture", response.text)

    def test_upload_window_rechecks_revoked_approval_and_keeps_history_downloadable(self) -> None:
        self.finalize()
        original = self.production.export_project(self.project_id, "markdown", "formal")
        upload = self.production.storage.put_file
        revoked = False

        def upload_and_revoke(*args, **kwargs):
            nonlocal revoked
            result = upload(*args, **kwargs)
            if not revoked:
                revoked = True
                self.production.update_project(self.project_id, {"profile": {"manual_finalized": False}})
            return result

        with patch.object(self.production.storage, "put_file", side_effect=upload_and_revoke):
            with self.assertRaisesRegex(ValueError, "导出期间质量或签审状态已变化"):
                self.production.export_project(self.project_id, "markdown", "formal")
        history = self.production.list_deliveries(self.project_id)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]["current"])
        self.assertEqual(self.client.get(original["download_url"]).status_code, 200)

    def test_upload_window_rechecks_concurrent_body_edit(self) -> None:
        self.finalize()
        upload = self.production.storage.put_file
        changed = False

        def upload_and_edit(*args, **kwargs):
            nonlocal changed
            result = upload(*args, **kwargs)
            if not changed:
                changed = True
                self.production.update_draft(self.draft_id, self.content + "\n\n每天记录现场巡查情况。")
            return result

        with patch.object(self.production.storage, "put_file", side_effect=upload_and_edit):
            with self.assertRaisesRegex(ValueError, "导出期间项目内容已变化"):
                self.production.export_project(self.project_id, "markdown", "formal")
        self.assertEqual(self.production.list_deliveries(self.project_id), [])

    def test_upload_window_rejects_reapproval_by_a_different_reviewer(self) -> None:
        self.finalize()
        prior = self.production.export_project(self.project_id, "markdown", "formal")
        upload = self.production.storage.put_file
        changed = False

        def upload_and_reapprove(*args, **kwargs):
            nonlocal changed
            result = upload(*args, **kwargs)
            if not changed:
                changed = True
                preview = self.production.preview_project(self.project_id)
                self.production.confirm_final_review(self.project_id, preview["project_hash"], "李工", True, True)
            return result

        with patch.object(self.production.storage, "put_file", side_effect=upload_and_reapprove):
            with self.assertRaisesRegex(ValueError, "导出期间质量或签审状态已变化"):
                self.production.export_project(self.project_id, "docx", "formal")
        self.assertTrue(self.production.quality_gate(self.project_id)["formal_ready"])
        history = self.production.list_deliveries(self.project_id)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]["current"])
        self.assertEqual(self.client.get(prior["download_url"]).status_code, 200)

    def test_replaced_draft_claims_do_not_block_the_current_version(self) -> None:
        self.production.update_draft(self.draft_id, self.content + "\n\n本工程保证采用特殊工艺后全部项目实现零事故。")
        self.assertGreater(self.production.evidence.metrics(self.project_id)["high_unsupported"], 0)
        with self.db.connect() as conn:
            newer_id = int(conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,content_hash,version_no) VALUES (?,?,?,?,2)",
                (self.project_id, self.section_id, self.content, content_hash(self.content)),
            ).lastrowid)
        generation = self.production.evidence.create_generation_run(self.project_id, self.section_id, content_hash(self.content), "fixture", "1", "1", None, [])
        self.production.evidence.analyze_draft(generation, newer_id, self.content, [])
        self.assertEqual(self.production.evidence.metrics(self.project_id)["high_unsupported"], 0)
        self.assertTrue(self.production.quality_gate(self.project_id)["review_ready"])

    def test_consistency_ignores_duration_spacing_and_goal_headings(self) -> None:
        project = {"sections": [
            {"draft": {"content": "工期：850 日历天。\n质量目标：**符合国家、省、市相关规范**。\n## 质量目标保证和控制措施\n日常检查。"}},
            {"draft": {"content": "总工期为850日历天。\n**质量目标**：符合国家、省、市相关规范。\n## 安全目标保证措施\n安全目标：杜绝死亡。"}},
        ]}
        self.assertFalse(any(item["key"].startswith("conflict_") for item in self.production._consistency_issues(project)))

    def test_consistency_still_flags_different_declared_targets(self) -> None:
        project = {"sections": [
            {"draft": {"content": "工期80天。质量目标：合格。安全目标：杜绝死亡。"}},
            {"draft": {"content": "工期100天。质量目标为优良。安全目标为减少事故。"}},
        ]}
        self.assertEqual({item["key"] for item in self.production._consistency_issues(project)}, {"conflict_工期", "conflict_质量目标", "conflict_安全目标"})

    def test_review_package_record_and_download_refer_to_zip(self) -> None:
        # PDF conversion itself is exercised by the existing pilot; this test
        # isolates the package/record/download contract from the external tool.
        def convert(path: Path) -> Path:
            target = path.with_suffix(".pdf")
            target.write_bytes(b"%PDF-1.4\nfixture")
            return target

        with patch.object(self.production, "_convert_pdf", side_effect=convert), patch.object(self.production, "_preflight_pdf", return_value={"pages": 1}):
            exported = self.production.export_project(self.project_id, "package", "review")
        record = self.db.row("SELECT file_path FROM deliveries WHERE id=?", (exported["delivery_id"],))
        self.assertEqual(record["file_path"], exported["file_path"])
        self.assertTrue(record["file_path"].endswith(".zip"))
        response = self.client.get(exported["download_url"])
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 4)
            self.assertIn("送审说明.md", archive.namelist())

    def test_manual_edit_rechecks_high_risk_claims_before_resigning(self) -> None:
        self.production.confirm_draft(self.draft_id, "陈工")
        self.production.update_draft(self.draft_id, self.content + "\n\n本工程保证采用特殊工艺后全部项目实现零事故。")
        with self.assertRaisesRegex(ValueError, "高风险Claim缺少证据"):
            self.production.confirm_draft(self.draft_id, "陈工")
        quality = self.production.quality_gate(self.project_id)
        self.assertFalse(quality["review_ready"])
        self.assertGreater(quality["metrics"]["claims"]["high_unsupported"], 0)

    def test_empty_project_cannot_pass_the_delivery_gate(self) -> None:
        project = self.production.create_project({"name": "新建工程"})
        self.assertFalse(self.production.quality_gate(project["id"])["review_ready"])

    def test_zero_claims_edit_with_failed_reanalysis_blocks_both_export_modes(self) -> None:
        self.production.update_draft(self.draft_id, "# 施工组织安排")
        self.assertEqual(self.production.evidence.list_claims(self.draft_id), [])
        self.finalize()
        self.assertTrue(self.production.quality_gate(self.project_id)["formal_ready"])
        changed = "# 施工组织安排\n\n本工程必须在30天内完成全部施工，混凝土强度必须达到C60。"
        with patch.object(self.production.evidence, "analyze_draft", side_effect=RuntimeError("fixture analysis failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture analysis failure"):
                self.production.update_draft(self.draft_id, changed)
        saved = self.db.row("SELECT content,evidence_status FROM project_drafts WHERE id=?", (self.draft_id,))
        self.assertEqual(saved, {"content": changed, "evidence_status": "pending"})
        self.assertEqual(self.production.evidence.list_claims(self.draft_id), [])
        quality = self.production.quality_gate(self.project_id)
        for mode in ("review", "formal"):
            with self.subTest(mode=mode):
                self.assertFalse(quality[f"{mode}_ready"])
                blocker_key = "review_blockers" if mode == "review" else "blockers"
                self.assertIn("stale_evidence", {item["key"] for item in quality[blocker_key]})
                response = self.client.post(f"/api/projects/{self.project_id}/export", json={
                    "format": "markdown", "mode": mode, "background": False,
                })
                self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM deliveries WHERE project_id=?", (self.project_id,))["count"], 0)

    def test_explicit_unfinished_evidence_states_block_without_claims(self) -> None:
        self.production.update_draft(self.draft_id, "# 施工组织安排")
        self.finalize()
        self.assertEqual(self.production.evidence.list_claims(self.draft_id), [])
        for state in ("pending", "invalidated", "failed"):
            with self.subTest(evidence_status=state):
                with self.db.connect() as conn:
                    conn.execute("UPDATE project_drafts SET evidence_status=? WHERE id=?", (state, self.draft_id))
                quality = self.production.quality_gate(self.project_id)
                self.assertFalse(quality["review_ready"])
                self.assertFalse(quality["formal_ready"])
                self.assertIn("stale_evidence", {item["key"] for item in quality["review_blockers"]})

    def test_authenticated_review_and_download_permissions(self) -> None:
        self.client.close()
        auth_settings = replace(self.settings, auth_enabled=True, session_secret="delivery-workflow-session-secret", bootstrap_password="test-bootstrap-password")
        app = create_app(auth_settings)
        auth = app.state.auth
        exported = self.production.export_project(self.project_id, "markdown", "review")
        preview = self.production.preview_project(self.project_id)
        payload = {"project_hash": preview["project_hash"], "professional_reviewer": "陈工", "compliance_confirmed": True, "manual_finalized": True}
        with TestClient(app) as anonymous:
            self.assertEqual(anonymous.get(exported["download_url"]).status_code, 401)
        for role in ("viewer", "author", "reviewer"):
            user_id = auth.create_local_user(f"delivery-{role}", role, "test-user-password", [role])
            session = auth.create_session(user_id)
            with TestClient(app) as client:
                client.cookies.set(AuthService.session_cookie, session["token"])
                client.cookies.set(AuthService.csrf_cookie, session["csrf"])
                headers = {"X-CSRF-Token": session["csrf"]}
                expected = 200 if role == "reviewer" else 403
                self.assertEqual(client.get(exported["download_url"]).status_code, expected, role)
                self.assertEqual(client.post(f"/api/projects/{self.project_id}/final-review", json=payload, headers=headers).status_code, expected, role)
                self.assertEqual(client.patch(f"/api/projects/{self.project_id}", json={"profile": {"compliance_confirmed": True, "manual_finalized": True}}, headers=headers).status_code, expected, role)


if __name__ == "__main__":
    unittest.main()
