from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bid_writer_v2.ai_runtime import (
    AiRuntime,
    KnowledgeCandidateReview,
    KnowledgeExtractionCandidate,
    KNOWLEDGE_EXTRACTION_PROMPT,
    KNOWLEDGE_REWRITE_PROMPT,
    PromptSpec,
)
from bid_writer_v2.database import Database
from bid_writer_v2.llm import LlmClient


class FakeLlm:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def settings(self) -> dict:
        return {
            "configured": True,
            "base_url": "http://model.test/v1",
            "model": "test-model",
            "wire_api": "responses",
        }

    def generate(self, instructions: str, prompt: str, max_output_tokens: int = 8000) -> dict:
        self.calls += 1
        return {
            **self.settings(),
            "content": json.dumps(self.payload, ensure_ascii=False),
            "error": "",
            "latency_ms": 25,
            "attempts": 1,
            "input_tokens": 120,
            "output_tokens": 60,
        }

    json_payload = staticmethod(LlmClient.json_payload)


class AiRuntimeTest(unittest.TestCase):
    def test_repairs_only_json_trailing_commas(self) -> None:
        payload = LlmClient.json_payload('{"text":"keep ,} here","items":[{"value":1,},],}')
        self.assertEqual(payload, {"text": "keep ,} here", "items": [{"value": 1}]})

    def test_normalizes_explicit_section_reference(self) -> None:
        candidate = KnowledgeExtractionCandidate.model_validate(
            {
                "source_section_id": "SECTION:14",
                "title": "施工进度动态管理",
                "unit_type": "schedule_plan",
                "content": "施工期间应定期核对实际进度与计划进度，并根据偏差及时调整后续安排。",
                "summary": "通过计划对比和偏差调整实施进度管理。",
                "tags": ["施工进度"],
                "applicability": "建设工程施工进度管理",
                "risk_level": "medium",
                "source_quote": "定期核对实际进度与计划进度，并及时调整后续安排。",
            }
        )
        self.assertEqual(candidate.source_section_id, 14)

    def test_isolates_invalid_extraction_candidate(self) -> None:
        valid = {
            "source_section_id": 14,
            "title": "施工进度动态管理",
            "unit_type": "schedule_plan",
            "content": "施工期间应定期核对实际进度与计划进度，并根据偏差及时调整后续安排。",
            "summary": "通过计划对比和偏差调整实施进度管理。",
            "tags": ["施工进度"],
            "applicability": "建设工程施工进度管理",
            "risk_level": "medium",
            "source_quote": "定期核对实际进度与计划进度，并及时调整后续安排。",
        }
        invalid = {**valid, "source_quote": "过短"}
        runtime = AiRuntime(self.db, FakeLlm({"candidates": [valid, invalid]}))  # type: ignore[arg-type]
        result = runtime.execute(
            KNOWLEDGE_EXTRACTION_PROMPT,
            "测试抽取",
            {"document_id": 1},
            task_type="knowledge_candidate_extraction",
        )
        self.assertEqual(len(result["payload"]["candidates"]), 1)
        self.assertEqual(result["validation_errors"][0]["path"], "candidates.1.source_quote")
        self.assertEqual(runtime.list_runs(limit=1)[0]["status"], "succeeded")

    def test_normalizes_review_root_severity_and_string_issue(self) -> None:
        review = KnowledgeCandidateReview.model_validate(
            {
                "candidate_index": 0,
                "decision": "revise",
                "confidence": 0.94,
                "severity": "medium",
                "issues": ["适用范围超出原文。"],
                "corrected_content": "按原文限定适用范围后形成可复用内容。",
            }
        )
        self.assertEqual(review.issues[0].severity, "medium")
        self.assertEqual(review.issues[0].message, "适用范围超出原文。")

    def test_normalizes_rejection_reason_without_allowing_auto_pass(self) -> None:
        review = KnowledgeCandidateReview.model_validate(
            {
                "candidate_index": 0,
                "decision": "reject",
                "reason": "候选内容扩大了来源适用范围，需要修改后再审。",
            }
        )
        self.assertEqual(review.confidence, 0)
        self.assertEqual(review.corrected_content, "")
        self.assertEqual(review.issues[0].severity, "medium")
        self.assertIn("扩大", review.issues[0].message)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "runtime.sqlite3")
        self.db.migrate()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def valid_payload() -> dict:
        return {
            "title": "混凝土施工通用知识",
            "content": "施工前完成条件核验，施工中实施过程检查，完成后按验收标准形成闭环记录。",
            "summary": "施工准备、过程检查和验收闭环。",
            "tags": ["混凝土", "质量控制"],
        }

    def test_records_valid_run_and_reuses_cache(self) -> None:
        llm = FakeLlm(self.valid_payload())
        runtime = AiRuntime(self.db, llm)  # type: ignore[arg-type]
        prompt = KNOWLEDGE_REWRITE_PROMPT.render(source_material="原始施工资料")
        first = runtime.execute(
            KNOWLEDGE_REWRITE_PROMPT,
            prompt,
            {"unit_id": 1, "source_material": "原始施工资料"},
            task_type="knowledge_rewrite",
            target_type="knowledge_unit",
            target_id=1,
        )
        second = runtime.execute(
            KNOWLEDGE_REWRITE_PROMPT,
            prompt,
            {"unit_id": 1, "source_material": "原始施工资料"},
            task_type="knowledge_rewrite",
            target_type="knowledge_unit",
            target_id=1,
        )

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["cached_from_run_id"], first["run_id"])
        self.assertEqual(llm.calls, 1)
        self.assertEqual(runtime.metrics(), {"total": 2, "succeeded": 1, "failed": 0, "cached": 1, "input_tokens": 120, "output_tokens": 60})
        self.assertEqual(runtime.list_prompts()[0]["prompt_key"], "knowledge.rewrite")

    def test_rejects_output_that_fails_schema(self) -> None:
        runtime = AiRuntime(self.db, FakeLlm({"title": "缺少正文"}))  # type: ignore[arg-type]
        result = runtime.execute(
            KNOWLEDGE_REWRITE_PROMPT,
            KNOWLEDGE_REWRITE_PROMPT.render(source_material="资料"),
            {"source_material": "资料"},
            task_type="knowledge_rewrite",
        )
        self.assertIsNone(result["payload"])
        self.assertTrue(result["validation_errors"])
        run = runtime.list_runs(limit=1)[0]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error_code"], "schema_validation_failed")

    def test_prompt_version_cannot_change_silently(self) -> None:
        runtime = AiRuntime(self.db, FakeLlm(self.valid_payload()))  # type: ignore[arg-type]
        prompt = KNOWLEDGE_REWRITE_PROMPT.render(source_material="资料")
        runtime.execute(KNOWLEDGE_REWRITE_PROMPT, prompt, {"source_material": "资料"}, task_type="knowledge_rewrite")
        changed = PromptSpec(
            key=KNOWLEDGE_REWRITE_PROMPT.key,
            version=KNOWLEDGE_REWRITE_PROMPT.version,
            instructions="已修改但未升级版本",
            template=KNOWLEDGE_REWRITE_PROMPT.template,
            output_model=KNOWLEDGE_REWRITE_PROMPT.output_model,
        )
        with self.assertRaisesRegex(RuntimeError, "请提升版本号"):
            runtime.execute(changed, changed.render(source_material="资料"), {"source_material": "资料"}, task_type="knowledge_rewrite")


if __name__ == "__main__":
    unittest.main()
