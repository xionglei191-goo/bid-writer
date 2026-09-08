from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from pydantic import BaseModel

from bid_writer_v2.ai_runtime import AiRuntime, PromptSpec
from bid_writer_v2.database import Database
from bid_writer_v2.llm import LlmClient


class Answer(BaseModel):
    answer: str


PROMPT = PromptSpec("test.failover", "1", "Return JSON.", "{question}", Answer)


def http_response(status: int = 200, *, content: str = '{"answer":"ok"}', stream: bool = False,
                  model: str = "served-primary") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://synthetic.invalid/model"
    if stream:
        body = "data: " + json.dumps({
            "model": model, "choices": [{"delta": {"content": content}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 6},
        }) + "\n\ndata: [DONE]\n\n"
    else:
        body = json.dumps({
            "model": model, "output_text": content,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
    response._content = body.encode("utf-8")
    response._content_consumed = True
    return response


class FailoverFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.env = {
            "OPENAI_API_KEY": "synthetic-primary-key",
            "OPENAI_BASE_URL": "https://primary.invalid/v1",
            "OPENAI_MODEL": "primary-alias",
            "OPENAI_WIRE_API": "responses",
            "OPENAI_FALLBACK_API_KEY": "synthetic-backup-key",
            "OPENAI_FALLBACK_BASE_URL": "https://backup.invalid/v1",
            "OPENAI_FALLBACK_MODEL": "backup-alias",
            "OPENAI_FALLBACK_WIRE_API": "chat_completions",
        }
        self.addCleanup(patch.stopall)
        patch("bid_writer_v2.llm.environment_value", side_effect=lambda name, default="": self.env.get(name, default)).start()
        self.post = patch("bid_writer_v2.llm.requests.post").start()
        self.sleep = patch("bid_writer_v2.llm.time.sleep").start()
        self.client = LlmClient()

    def run_fallback_success(self) -> dict:
        self.post.side_effect = [
            http_response(429),
            http_response(stream=True, model="served-backup"),
        ]
        return self.client.generate("Return JSON.", "question")


class LlmFailoverTest(FailoverFixture):
    def test_primary_success_preserves_served_model_without_contacting_backup(self) -> None:
        self.post.return_value = http_response()
        result = self.client.generate("Return JSON.", "question")
        self.assertEqual(result["model"], "served-primary")
        self.assertEqual(result["base_url"], self.env["OPENAI_BASE_URL"])
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["input_tokens"], 10)
        self.assertEqual(self.post.call_count, 1)

    def test_rate_limited_primary_uses_separate_backup_key_and_combines_costs(self) -> None:
        with patch("bid_writer_v2.llm.time.time", side_effect=[0, 1, 2, 3]):
            result = self.run_fallback_success()
        self.assertEqual(result["model"], "served-backup")
        self.assertEqual(result["base_url"], self.env["OPENAI_FALLBACK_BASE_URL"])
        self.assertEqual(result["wire_api"], "chat_completions")
        self.assertTrue(result["fallback_used"])
        self.assertIn("429", result["primary_error"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["latency_ms"], 2000)
        self.assertEqual(result["input_tokens"], 12)
        self.assertEqual(result["output_tokens"], 6)
        calls = self.post.call_args_list
        self.assertEqual(calls[0].args[0], "https://primary.invalid/v1/responses")
        self.assertEqual(calls[1].args[0], "https://backup.invalid/v1/chat/completions")
        self.assertEqual(calls[0].kwargs["headers"]["Authorization"], "Bearer synthetic-primary-key")
        self.assertEqual(calls[1].kwargs["headers"]["Authorization"], "Bearer synthetic-backup-key")
        self.sleep.assert_not_called()

    def test_two_failed_routes_keep_both_errors_and_all_attempts(self) -> None:
        self.post.side_effect = [requests.Timeout("primary timeout")] * 4 + [requests.ConnectionError("backup offline")] * 4
        result = self.client.generate("Return JSON.", "question")
        self.assertFalse(result["content"])
        self.assertTrue(result["fallback_used"])
        self.assertIn("primary timeout", result["primary_error"])
        self.assertIn("backup offline", result["error"])
        self.assertEqual(result["model"], "backup-alias")
        self.assertEqual(result["attempts"], 8)
        self.assertEqual(self.post.call_count, 8)
        self.assertEqual(self.sleep.call_count, 6)

    def test_missing_backup_credentials_keeps_primary_rate_limit_retries(self) -> None:
        self.env["OPENAI_FALLBACK_API_KEY"] = ""
        self.post.return_value = http_response(429)
        result = self.client.generate("Return JSON.", "question")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["attempts"], 4)
        self.assertEqual(self.post.call_count, 4)
        self.assertEqual(self.sleep.call_count, 3)
        self.assertIsNone(self.client.settings()["fallback_route"])

    def test_disabling_llm_prevents_primary_and_backup_requests(self) -> None:
        self.env["BID_WRITER_DISABLE_LLM"] = "1"
        result = self.client.generate("Return JSON.", "question")
        self.assertFalse(result["configured"])
        self.assertFalse(result["content"])
        self.post.assert_not_called()

    def test_nonrecoverable_http_error_does_not_send_prompt_to_backup(self) -> None:
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.post.reset_mock()
                self.post.return_value = http_response(status)
                result = self.client.generate("Return JSON.", "question")
                self.assertFalse(result["fallback_used"])
                self.assertEqual(result["attempts"], 1)
                self.assertEqual(self.post.call_count, 1)

    def test_codex_transient_failure_can_use_configured_backup(self) -> None:
        self.env["OPENAI_WIRE_API"] = "codex"
        self.post.side_effect = [requests.Timeout("primary timeout")] * 4 + [http_response(stream=True, model="served-backup")]
        with patch.object(self.client, "_codex_auth", return_value=("synthetic-token", "", "test")):
            result = self.client.generate("Return JSON.", "question")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["model"], "served-backup")
        self.assertEqual(result["attempts"], 5)


class RuntimeFailoverAuditTest(FailoverFixture):
    def setUp(self) -> None:
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "isolated.sqlite3")
        self.db.migrate()
        self.runtime = AiRuntime(self.db, self.client)

    def execute(self, **kwargs: object) -> dict:
        return self.runtime.execute(PROMPT, "question", {"fixture": "only"}, task_type="failover_test", **kwargs)

    def fallback_success(self) -> dict:
        self.post.side_effect = [http_response(429), http_response(stream=True, model="served-backup")]
        return self.execute()

    def test_primary_run_keeps_requested_and_served_model_distinct(self) -> None:
        self.post.return_value = http_response()
        result = self.execute()
        row = self.runtime.list_runs()[0]
        self.assertEqual(row["id"], result["run_id"])
        self.assertEqual(row["model"], "primary-alias")
        self.assertEqual(row["effective_model"], "served-primary")
        self.assertEqual(row["effective_base_url"], "https://primary.invalid/v1")
        self.assertEqual(row["fallback_used"], 0)

    def test_cached_backup_result_keeps_original_provenance_without_new_usage(self) -> None:
        first = self.fallback_success()
        cached = self.execute()
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["cached_from_run_id"], first["run_id"])
        self.assertEqual(cached["model"], "served-backup")
        self.assertEqual(cached["base_url"], "https://backup.invalid/v1")
        self.assertEqual(cached["wire_api"], "chat_completions")
        self.assertTrue(cached["fallback_used"])
        self.assertEqual(cached["primary_error"], first["primary_error"])
        self.assertEqual(self.post.call_count, 2)
        row = self.runtime.list_runs()[0]
        self.assertEqual(row["model"], "primary-alias")
        self.assertEqual(row["effective_model"], "served-backup")
        self.assertEqual(row["fallback_used"], 1)
        self.assertEqual(row["primary_error"], first["primary_error"])
        self.assertEqual(row["attempts"], 0)
        self.assertEqual(row["input_tokens"], 0)
        self.assertEqual(row["output_tokens"], 0)
        self.assertEqual(self.runtime.metrics()["input_tokens"], 12)

    def test_failed_backup_run_audits_last_attempted_route_and_primary_error(self) -> None:
        self.post.side_effect = [requests.Timeout("primary timeout")] * 4 + [requests.ConnectionError("backup offline")] * 4
        result = self.execute()
        row = self.runtime.list_runs()[0]
        self.assertIsNone(result["payload"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["effective_model"], "backup-alias")
        self.assertEqual(row["fallback_used"], 1)
        self.assertIn("primary timeout", row["primary_error"])
        self.assertIn("backup offline", row["error_message"])
        self.assertEqual(row["attempts"], 8)

    def test_backup_model_change_invalidates_cached_output(self) -> None:
        self.fallback_success()
        self.env["OPENAI_FALLBACK_MODEL"] = "different-backup"
        self.post.side_effect = None
        self.post.return_value = http_response()
        result = self.execute()
        self.assertFalse(result["cached"])
        self.assertEqual(self.post.call_count, 3)

    def test_disabling_backup_does_not_reuse_its_cached_output(self) -> None:
        self.fallback_success()
        self.env["OPENAI_FALLBACK_API_KEY"] = ""
        self.post.side_effect = None
        self.post.return_value = http_response()
        result = self.execute()
        self.assertFalse(result["cached"])
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["model"], "served-primary")

    def test_rotating_credentials_reuses_cache_and_never_persists_keys(self) -> None:
        self.fallback_success()
        self.env["OPENAI_FALLBACK_API_KEY"] = "rotated-synthetic-key"
        result = self.execute()
        self.assertTrue(result["cached"])
        material = json.dumps(self.db.rows("SELECT * FROM ai_runs")) + json.dumps(self.client.settings())
        for key in ("synthetic-primary-key", "synthetic-backup-key", "rotated-synthetic-key"):
            self.assertNotIn(key, material)

    def test_schema_retry_preserves_final_backup_provenance_and_total_attempts(self) -> None:
        self.post.side_effect = [
            http_response(content="invalid JSON"), http_response(429),
            http_response(stream=True, model="served-backup"),
        ]
        result = self.execute()
        row = self.runtime.list_runs()[0]
        self.assertEqual(result["payload"], {"answer": "ok"})
        self.assertEqual(row["effective_model"], "served-backup")
        self.assertEqual(row["fallback_used"], 1)
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(row["input_tokens"], 22)

    def test_failed_schema_retry_still_counts_the_second_model_call(self) -> None:
        self.post.side_effect = [http_response(content="invalid JSON"), http_response(401)]
        result = self.execute()
        row = self.runtime.list_runs()[0]
        self.assertIsNone(result["payload"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["effective_model"], "served-primary")


class FailoverMigrationTest(unittest.TestCase):
    def test_sqlite_upgrade_preserves_old_runs_and_is_repeatable(self) -> None:
        source = Path(__file__).parents[1] / "bid_writer_v2" / "migrations"
        with tempfile.TemporaryDirectory() as root:
            migrations = Path(root) / "prior_migrations"
            migrations.mkdir()
            for file in source.glob("*.sql"):
                if file.name < "017_ai_failover_audit.sql":
                    shutil.copyfile(file, migrations / file.name)
            db = Database(Path(root) / "migration.sqlite3", migrations_root=migrations)
            db.migrate()
            with db.connect() as conn:
                conn.execute("INSERT INTO ai_runs(task_type,prompt_key,prompt_version,prompt_hash,input_hash,cache_key,model,base_url,wire_api,status,input_json) VALUES ('legacy','p','1','h','i','c','old-model','old-route','responses','succeeded','{}')")
            db.migrations_root = source
            self.assertEqual(db.migrate(), ["017_ai_failover_audit.sql"])
            row = db.row("SELECT * FROM ai_runs")
            self.assertEqual(row["model"], "old-model")
            self.assertIsNone(row["effective_model"])
            self.assertEqual(row["fallback_used"], 0)
            self.assertEqual(row["primary_error"], "")
            self.assertEqual(db.migrate(), [])

    def test_postgres_revision_is_reachable_and_renders_upgrade_without_connecting(self) -> None:
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        output = io.StringIO()
        config = Config(output_buffer=output)
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        config.set_main_option("sqlalchemy.url", "postgresql://offline.invalid/unused")
        script = ScriptDirectory.from_config(config)
        self.assertIn("20260905_05", {revision.revision for revision in script.walk_revisions()})
        with patch("sqlalchemy.engine_from_config", side_effect=AssertionError("offline test must not connect")):
            command.upgrade(config, "20260813_04:20260905_05", sql=True)
        sql = output.getvalue()
        self.assertIn("ALTER TABLE ai_runs ADD COLUMN effective_model TEXT", sql)
        self.assertIn("fallback_used BIGINT NOT NULL DEFAULT 0", sql)
        self.assertIn("CREATE INDEX idx_ai_runs_effective_model", sql)
        self.assertNotIn("DROP TABLE", sql)


if __name__ == "__main__":
    unittest.main()
