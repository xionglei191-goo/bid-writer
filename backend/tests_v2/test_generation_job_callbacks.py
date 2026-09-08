from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def isolated_environment(root: Path) -> dict[str, str]:
    # Do not inherit deployed paths, provider credentials, or registry fallback.
    values = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("BID_WRITER_", "OPENAI_", "PADDLEOCR_"))
    }
    values.update({
        "BID_WRITER_WORKSPACE": str(root), "BID_WRITER_APP_ROOT": str(root / "app"),
        "BID_WRITER_DATA": str(root / "data"), "BID_WRITER_DB": str(root / "data" / "test.sqlite3"),
        "BID_WRITER_RAW": str(root / "raw"), "BID_WRITER_KNOWLEDGE": str(root / "knowledge"),
        "BID_WRITER_DELIVERY": str(root / "delivery"), "BID_WRITER_EXPORT": str(root / "exports"),
        "BID_WRITER_QA": str(root / "qa"), "BID_WRITER_UPLOADS": str(root / "uploads"),
        "BID_WRITER_CACHE": str(root / "cache"), "BID_WRITER_DATABASE_URL": "",
        "BID_WRITER_REDIS_URL": "", "BID_WRITER_QDRANT_URL": "",
        "BID_WRITER_MINIO_ENDPOINT": "", "BID_WRITER_EMBEDDING_URL": "",
        "BID_WRITER_AUTH_ENABLED": "0", "BID_WRITER_BACKGROUND_JOBS": "0",
        "BID_WRITER_ENABLE_OPERATIONS": "0", "BID_WRITER_DISABLE_LLM": "1",
        "BID_WRITER_DISABLE_USER_ENV": "1", "OPENAI_WIRE_API": "responses",
        "BID_WRITER_OCR_URL": "http://127.0.0.1:1/disabled",
    })
    return values


# Importing app.py constructs its module-level app. Isolate that migration too,
# rather than waiting until setUp after a deployed default DB has been opened.
with tempfile.TemporaryDirectory(prefix="generation-callback-bootstrap-") as bootstrap:
    with patch.dict(os.environ, isolated_environment(Path(bootstrap)), clear=True):
        from bid_writer_v2.app import create_app
        from bid_writer_v2.settings import Settings


class GenerationJobCallbacksTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="generation-callback-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, isolated_environment(self.root), clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.app = create_app(Settings.from_env())
        self.production = self.app.state.production
        self.jobs = self.app.state.jobs
        self.db = self.app.state.db
        model = patch.object(self.app.state.ai_runtime, "execute", side_effect=AssertionError("No model calls in callback tests"))
        self.model = model.start()
        self.addCleanup(model.stop)

    def test_registered_section_handler_preserves_callback_identity_and_result(self) -> None:
        report = Mock(name="report")
        cancelled = Mock(name="cancelled", return_value=True)
        result = {"section_id": 29, "cancelled": True, "generation_status": "cancelled"}
        with patch.object(self.production, "generate_section", return_value=result) as generate:
            actual = self.jobs.handlers["production.generate_section"](
                {"project_id": "17", "section_id": "29"}, report, cancelled,
            )
        generate.assert_called_once_with(17, 29, progress=report, cancelled=cancelled)
        self.assertIs(actual, result)
        report.assert_not_called()
        self.model.assert_not_called()

    def test_running_section_job_remains_cancelled_without_completed_event(self) -> None:
        job = self.jobs.enqueue(
            "production.generate_section", "project_section", 29,
            {"project_id": 17, "section_id": 29},
        )

        def generate(project_id, section_id, *, progress, cancelled):
            self.assertEqual((project_id, section_id), (17, 29))
            self.assertFalse(cancelled())
            progress("generating", 35, "第一部分完成", {"completed_batches": 1})
            self.jobs.cancel(job["id"])
            self.assertTrue(cancelled())
            progress("cancelled", 0, "取消后未保存章节", {"completed_batches": 1})
            return {"section_id": section_id, "cancelled": True, "generation_status": "cancelled"}

        with patch.object(self.production, "generate_section", side_effect=generate) as mocked:
            completed = self.jobs.run(job["id"])
        mocked.assert_called_once()
        self.assertEqual(completed["status"], "cancelled")
        self.assertEqual(completed["stage"], "cancelled")
        stages = [event["stage"] for event in completed["events"]]
        self.assertIn("generating", stages)
        self.assertIn("cancelled", stages)
        self.assertNotIn("completed", stages)
        self.assertEqual(self.db.row("SELECT COUNT(*) AS n FROM project_drafts")["n"], 0)
        self.model.assert_not_called()

    def test_pre_cancelled_job_exits_real_section_service_before_project_or_model(self) -> None:
        job = self.jobs.enqueue(
            "production.generate_section", "project_section", 29,
            {"project_id": 17, "section_id": 29},
        )
        self.jobs.cancel(job["id"])
        with patch.object(self.production, "get_project", side_effect=AssertionError("Cancelled job must not load a project")) as project:
            completed = self.jobs.run(job["id"])
        self.assertEqual(completed["status"], "cancelled")
        self.assertEqual(completed["stage"], "cancelled")
        self.assertNotIn("completed", [event["stage"] for event in completed["events"]])
        self.assertEqual(self.db.row("SELECT COUNT(*) AS n FROM generation_runs")["n"], 0)
        self.assertEqual(self.db.row("SELECT COUNT(*) AS n FROM project_drafts")["n"], 0)
        project.assert_not_called()
        self.model.assert_not_called()

    def test_generate_all_passes_cancel_callback_and_stops_on_cancelled_child(self) -> None:
        project = {"sections": [{"id": 29}, {"id": 30}, {"id": 31}]}
        report = Mock(name="report")
        cancelled = Mock(name="cancelled", return_value=False)
        child = {"section_id": 29, "cancelled": True, "generation_status": "cancelled"}

        def generate(project_id, section_id, *, progress, cancelled):
            self.assertEqual((project_id, section_id), (17, 29))
            self.assertIs(cancelled, cancel_callback)
            progress("cancelled", 0, "未保存当前章节", {"section_id": section_id})
            return child

        cancel_callback = cancelled
        with patch.object(self.production, "get_project", return_value=project), \
                patch.object(self.production, "coverage_matrix", return_value={"unmapped_high": []}), \
                patch.object(self.production, "generate_section", side_effect=generate) as mocked:
            result = self.production.generate_all(17, progress=report, cancelled=cancelled)
        mocked.assert_called_once()
        self.assertEqual(result["results"], [child])
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(report.call_args.args[0], "cancelled")
        self.assertNotIn("completed", [call.args[0] for call in report.call_args_list])
        self.model.assert_not_called()

    def test_generate_all_cancellation_between_chapters_preserves_only_finished_result(self) -> None:
        project = {"sections": [{"id": 29}, {"id": 30}, {"id": 31}]}
        report = Mock(name="report")
        state = {"cancelled": False}

        def cancelled():
            return state["cancelled"]

        def generate(project_id, section_id, *, progress, cancelled):
            self.assertIs(cancelled, cancel_callback)
            self.assertFalse(cancelled())
            state["cancelled"] = True
            return {"section_id": section_id, "draft_id": 41, "fallback_batches": 0}

        cancel_callback = cancelled
        with patch.object(self.production, "get_project", return_value=project), \
                patch.object(self.production, "coverage_matrix", return_value={"unmapped_high": []}), \
                patch.object(self.production, "generate_section", side_effect=generate) as mocked:
            result = self.production.generate_all(17, progress=report, cancelled=cancelled)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args, (17, 29))
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["generated"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual([item["section_id"] for item in result["results"]], [29])
        self.assertEqual(report.call_args.args[0], "cancelled")
        self.model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
