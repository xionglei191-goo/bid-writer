from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.database import Database
from bid_writer_v2.llm import LlmClient
from bid_writer_v2.production.service import ProductionService
from bid_writer_v2.settings import Settings
from bid_writer_v2.utils import content_hash


class SectionGenerationBatchesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="section-batches-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        settings = Settings(
            workspace_root=root, app_root=root / "app", raw_root=root / "raw",
            knowledge_root=root / "knowledge", delivery_root=root / "delivery",
            data_root=root / "data", db_path=root / "data" / "fixture.sqlite3",
            upload_root=root / "uploads", cache_root=root / "cache", export_root=root / "exports",
            qa_root=root / "qa", operations_enabled=False,
        )
        settings.ensure_directories()
        self.db = Database(settings.db_path)
        self.db.migrate()
        self.llm = LlmClient()
        self.addCleanup(patch.stopall)
        patch.object(self.llm, "settings", return_value={
            "configured": True, "model": "fixture-model", "base_url": "https://fixture.invalid/v1",
            "wire_api": "responses", "reasoning_effort": "", "fallback_route": None,
        }).start()
        self.generate = patch.object(self.llm, "generate", side_effect=self.reply).start()
        self.knowledge = Mock()
        self.production = ProductionService(self.db, settings, self.knowledge, self.llm, AiRuntime(self.db, self.llm))
        self.project = self.production.create_project({"name": "分包验证项目", "industry": "医院"})
        self.project_id = self.project["id"]
        self.before_call = None
        self.payload_transform = None
        self.prompts = []
        self.sources = [self.publish_fixture()]
        self.knowledge.search.return_value = self.sources

    def rows(self, table: str) -> list[dict]:
        return self.db.rows(f"SELECT * FROM {table} ORDER BY id")

    def publish_fixture(self) -> dict:
        content = "施工前组织条件检查，作业过程记录完成情况，发现偏差安排复核并保留记录。"
        digest = content_hash(content)
        with self.db.connect() as conn:
            unit_id = int(conn.execute(
                "INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,industry,status,content_fingerprint) "
                "VALUES ('fixture','construction_method','施工记录',?,?,'医院','published',?)", (content, content, digest),
            ).lastrowid)
            version_id = int(conn.execute(
                "INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,1,?,?,'approved')",
                (unit_id, content, digest),
            ).lastrowid)
            publication_id = int(conn.execute(
                "INSERT INTO knowledge_publications(unit_id,version_id,publication_version,published_by,file_path,content_hash) "
                "VALUES (?,?,1,'fixture','fixture.md',?)", (unit_id, version_id, digest),
            ).lastrowid)
        return {"unit_id": unit_id, "publication_id": publication_id, "publication_version": 1,
                "title": "施工记录", "content": content, "content_hash": digest, "sources": []}

    def section(self, count: int = 25, contents: list[str] | None = None) -> tuple[int, list[int]]:
        values = contents if contents is not None else [f"本项条款要求安排施工条件检查并记录处理情况（序列{index}）。" for index in range(count)]
        with self.db.connect() as conn:
            ids = [int(conn.execute(
                "INSERT INTO project_requirements(project_id,requirement_key,content) VALUES (?,?,?)",
                (self.project_id, f"R{index:04d}", content),
            ).lastrowid) for index, content in enumerate(values)]
            section_id = int(conn.execute(
                "INSERT INTO project_sections(project_id,order_no,title,requirement_ids_json) VALUES (?,1,'施工总体部署',?)",
                (self.project_id, json.dumps(ids)),
            ).lastrowid)
        return section_id, ids

    def reply(self, instructions: str, prompt: str, max_output_tokens: int) -> dict:
        self.prompts.append(prompt)
        if self.before_call:
            self.before_call()
        requirements = json.loads(prompt.split("本部分条款：", 1)[1].split("\n\n已审核知识：", 1)[0])
        lines = [f"{item['requirement_key']}响应：施工前组织条件检查，作业过程记录完成情况。" for item in requirements]
        payload = {
            "content": "\n\n".join(lines) if lines else "施工前组织条件检查，作业过程记录完成情况，发现偏差安排复核并保留记录。",
            "evidence": [{"requirement_id": item["id"], "text": line} for item, line in zip(requirements, lines)],
            "confirmations": [], "visual_suggestions": [],
        }
        if self.payload_transform:
            payload = self.payload_transform(payload, requirements)
        return {"content": json.dumps(payload, ensure_ascii=False), "model": "fixture-served",
                "attempts": 1, "input_tokens": 12, "output_tokens": 8, "latency_ms": 1}

    def test_137_requirements_have_distinct_audited_batches_and_one_final_draft(self) -> None:
        section_id, ids = self.section(137)
        self.before_call = lambda: self.assertEqual(self.rows("project_drafts"), [])
        with patch.object(self.production.evidence, "analyze_draft", wraps=self.production.evidence.analyze_draft) as analyze:
            result = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(result["generation_status"], "ai")
        self.assertEqual(result["ai_batches"], 12)
        self.assertEqual(result["fallback_batches"], 0)
        self.assertEqual(result["incomplete_batches"], 0)
        self.assertEqual(len(self.rows("project_drafts")), 1)
        analyze.assert_called_once()
        runs = self.rows("ai_runs")
        self.assertEqual(len(runs), 12)
        self.assertEqual(len({row["cache_key"] for row in runs}), 12)
        payloads = [json.loads(row["input_json"])["payload"] for row in runs]
        self.assertEqual([item["id"] for payload in payloads for item in payload["requirements"]], ids)
        self.assertTrue(all(len(payload["requirements"]) <= 12 for payload in payloads))
        self.assertEqual([payload["batch"]["index"] for payload in payloads], list(range(1, 13)))
        self.assertTrue(all(payload["batch"]["count"] == 12 for payload in payloads))
        self.assertEqual([row["requirement_id"] for row in self.rows("requirement_responses")], ids)
        self.assertTrue(all(call.args[2] == 8000 for call in self.generate.call_args_list))
        self.assertEqual(result["content"].count("# 施工总体部署"), 1)

    def test_identical_generation_reuses_each_batch_without_another_model_call(self) -> None:
        section_id, _ids = self.section()
        first = self.production.generate_section(self.project_id, section_id)
        second = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(self.generate.call_count, 3)
        self.assertTrue(second["cached"])
        self.assertEqual(second["content"], first["content"])
        self.assertEqual(second["version_no"], 2)
        self.assertEqual([row["status"] for row in self.rows("ai_runs")], ["succeeded"] * 3 + ["cached"] * 3)

    def test_character_budget_keeps_every_clause_including_oversized_single_clause(self) -> None:
        texts = ["甲" * 2001, "乙" * 2001, "丙" * 2001, "丁" * 6500, "戊" * 31]
        section_id, ids = self.section(contents=texts)
        self.production.generate_section(self.project_id, section_id)
        payloads = [json.loads(row["input_json"])["payload"] for row in self.rows("ai_runs")]
        self.assertEqual([item["id"] for payload in payloads for item in payload["requirements"]], ids)
        self.assertEqual([item["content"] for payload in payloads for item in payload["requirements"]], texts)
        self.assertEqual([len(payload["requirements"]) for payload in payloads], [2, 1, 1, 1])
        self.assertEqual(payloads[2]["requirements"][0]["content"], "丁" * 6500)

    def test_failed_middle_batch_retains_requirements_and_marks_partial_fallback(self) -> None:
        section_id, ids = self.section()
        def response(*args):
            if self.generate.call_count == 2:
                return {"content": "", "error": "output truncated", "attempts": 1}
            return self.reply(*args)
        self.generate.side_effect = response
        result = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(result["generation_status"], "partial_fallback")
        self.assertEqual([item["status"] for item in result["generation_batches"]], ["ai", "fallback", "ai"])
        self.assertEqual(result["fallback_batches"], 1)
        self.assertEqual(result["ai_batches"], 2)
        self.assertIn("output truncated", result["error"])
        self.assertTrue(any("第2/3部分AI编写失败" in text for text in result["confirmations"]))
        self.assertEqual([row["requirement_id"] for row in self.rows("requirement_responses")], ids)
        self.assertEqual(result["content"].count("# 施工总体部署"), 1)
        self.assertNotIn("本章结合", result["content"])
        self.assertIn("R0012：", result["content"])
        self.assertEqual(len(self.rows("project_drafts")), 1)
        self.assertEqual([row["status"] for row in self.rows("ai_runs")], ["succeeded", "failed", "succeeded"])

    def test_title_retry_preserves_industry_and_search_limits(self) -> None:
        section_id, _ids = self.section(1)
        self.knowledge.search.side_effect = [[], self.sources]
        self.production.generate_section(self.project_id, section_id)
        calls = self.knowledge.search.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].args, ("施工总体部署", "医院"))
        self.assertEqual(calls[0].args[1:], calls[1].args[1:])
        self.assertEqual(calls[0].kwargs, {"limit": 8})
        self.assertEqual(calls[0].kwargs, calls[1].kwargs)

    def test_empty_searches_block_before_any_model_or_draft(self) -> None:
        section_id, _ids = self.section(1)
        self.knowledge.search.return_value = []
        with self.assertRaisesRegex(ValueError, "没有匹配内容"):
            self.production.generate_section(self.project_id, section_id)
        self.assertEqual(self.knowledge.search.call_count, 2)
        self.generate.assert_not_called()
        self.assertEqual(self.rows("generation_runs"), [])
        self.assertEqual(self.rows("project_drafts"), [])

    def test_no_requirements_generate_one_audited_part_without_duplicate_search(self) -> None:
        section_id, _ids = self.section(0)
        result = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(result["generation_status"], "ai")
        self.assertEqual(result["ai_batches"], 1)
        self.assertEqual(self.knowledge.search.call_count, 1)
        self.assertEqual(json.loads(self.rows("ai_runs")[0]["input_json"])["payload"]["requirements"], [])

    def test_cross_batch_quote_cannot_establish_requirement_coverage(self) -> None:
        section_id, ids = self.section(13)
        second_only = "第二部分独有的复核安排，完成条件检查以后再保留记录。"
        def transform(payload, requirements):
            if requirements[0]["id"] == ids[0]:
                payload["evidence"][0]["text"] = second_only
                payload["evidence"].append({"requirement_id": ids[-1], "text": payload["evidence"][1]["text"]})
            else:
                payload["content"] += "\n\n" + second_only
            return payload
        self.payload_transform = transform
        result = self.production.generate_section(self.project_id, section_id)
        self.assertIn(second_only, result["content"])
        self.assertEqual(result["generation_status"], "incomplete")
        self.assertEqual(result["generation_batches"][0]["missing_requirement_ids"], [ids[0]])
        responses = self.rows("requirement_responses")
        self.assertNotIn(ids[0], [row["requirement_id"] for row in responses])
        self.assertEqual(sum(row["requirement_id"] == ids[-1] for row in responses), 1)

    def test_legal_ai_output_without_requirement_evidence_is_explicitly_incomplete(self) -> None:
        section_id, ids = self.section(12)
        self.payload_transform = lambda payload, _requirements: {**payload, "evidence": []}
        result = self.production.generate_section(self.project_id, section_id)
        self.assertEqual(result["generation_status"], "incomplete")
        self.assertEqual(result["incomplete_batches"], 1)
        self.assertEqual(result["generation_batches"][0]["missing_requirement_ids"], ids)
        self.assertTrue(any("12项要求缺少可核验" in text for text in result["confirmations"]))
        self.assertEqual(self.rows("requirement_responses"), [])
        self.assertEqual(self.rows("ai_runs")[0]["status"], "succeeded")
        saved = json.loads(self.rows("project_drafts")[0]["confirmations_json"])
        self.assertTrue(any("12项要求缺少可核验" in text for text in saved))

    def test_cancellation_before_start_does_not_query_or_generate(self) -> None:
        section_id, _ids = self.section()
        result = self.production.generate_section(self.project_id, section_id, cancelled=lambda: True)
        self.assertTrue(result["cancelled"])
        self.knowledge.search.assert_not_called()
        self.generate.assert_not_called()
        self.assertEqual(self.rows("generation_runs"), [])

    def test_cancellation_after_first_model_prevents_later_batches_and_persistence(self) -> None:
        section_id, _ids = self.section()
        stopped = [False]
        self.before_call = lambda: stopped.__setitem__(0, True)
        progress = Mock()
        result = self.production.generate_section(self.project_id, section_id, progress=progress, cancelled=lambda: stopped[0])
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(len(self.rows("ai_runs")), 1)
        self.assertEqual(self.rows("project_drafts"), [])
        self.assertEqual(self.rows("requirement_responses"), [])
        self.assertEqual(self.rows("generation_runs")[0]["status"], "cancelled")
        self.assertNotIn("completed", [call.args[0] for call in progress.call_args_list])

    def test_cancellation_prevents_runtime_json_repair_model_call(self) -> None:
        section_id, _ids = self.section()
        stopped = [False]
        def invalid_response(*_args):
            stopped[0] = True
            return {"content": "truncated JSON", "attempts": 1}
        self.generate.side_effect = invalid_response
        result = self.production.generate_section(self.project_id, section_id, cancelled=lambda: stopped[0])
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(self.rows("project_drafts"), [])

    def test_cancellation_at_merge_boundary_does_not_save_partial_draft(self) -> None:
        section_id, _ids = self.section()
        stopped = [False]
        def progress(stage, *_args):
            if stage == "saving":
                stopped[0] = True
        result = self.production.generate_section(self.project_id, section_id, progress=progress, cancelled=lambda: stopped[0])
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.generate.call_count, 3)
        self.assertEqual(self.rows("project_drafts"), [])
        self.assertEqual(self.rows("requirement_responses"), [])
        self.assertEqual(self.rows("generation_runs")[0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
