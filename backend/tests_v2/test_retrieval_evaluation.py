from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.audit import AuditService
from bid_writer_v2.database import Database
from bid_writer_v2.evaluation import RetrievalEvaluationService
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.llm import LlmClient

from test_v2_workflow import build_settings, create_source_docx


class SilverCaseLlm:
    def __init__(self) -> None:
        self.calls = 0

    def settings(self) -> dict:
        return {"configured": True, "base_url": "http://model.test/v1", "model": "silver-test", "wire_api": "responses"}

    def generate(self, instructions: str, prompt: str, max_output_tokens: int = 8000) -> dict:
        self.calls += 1
        if "case_id" in prompt:
            case_ids = [int(value) for value in __import__("re").findall(r'"case_id":\s*(\d+)', prompt)]
            payload = {
                "reviews": [
                    {
                        "case_id": case_id,
                        "decision": "reject" if index == len(case_ids) - 1 else "pass",
                        "confidence": 0.97,
                        "issues": [] if index < len(case_ids) - 1 else [
                            {"code": "invalid_negative", "severity": "high", "message": "负样本边界不可靠"}
                        ],
                    }
                    for index, case_id in enumerate(case_ids)
                ]
            }
        else:
            payload = {
                "cases": [
                    {"query": "混凝土施工前需要完成哪些准备？", "query_kind": "direct", "expected_match": True},
                    {"query": "浇筑作业前置条件如何核验？", "query_kind": "synonym", "expected_match": True},
                    {"query": "投标方案应如何描述混凝土过程检查？", "query_kind": "tender_clause", "expected_match": True},
                    {"query": "消防水泵联动控制有哪些要求？", "query_kind": "confusing_negative", "expected_match": False},
                ]
            }
        return {
            **self.settings(),
            "content": json.dumps(payload, ensure_ascii=False),
            "error": "",
            "latency_ms": 10,
            "attempts": 1,
            "input_tokens": 100,
            "output_tokens": 80,
        }

    json_payload = staticmethod(LlmClient.json_payload)


class RetrievalEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = build_settings(self.root)
        self.settings.ensure_directories()
        self.db = Database(self.settings.db_path)
        self.db.migrate()
        self.knowledge = KnowledgeService(self.db, self.settings)
        create_source_docx(self.settings.raw_root / "005、学校类" / "学校教学楼技术标.docx")
        self.unit_id = self._publish_first_unit()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _publish_first_unit(self) -> int:
        self.knowledge.scan_sources()
        jobs = self.knowledge.create_jobs(limit=10)
        self.knowledge.run_job(jobs["job_ids"][0])
        unit = self.knowledge.list_units(limit=20)[0]
        detail = self.knowledge.get_unit(unit["id"])
        version = detail["versions"][0]
        self.knowledge.review_unit(unit["id"], version["id"], "approve", "测试审核人")
        self.knowledge.publish_unit(unit["id"], version["id"], "测试发布人")
        return int(unit["id"])

    def test_generates_reviews_and_promotes_silver_cases(self) -> None:
        llm = SilverCaseLlm()
        runtime = AiRuntime(self.db, llm)  # type: ignore[arg-type]
        evaluation = RetrievalEvaluationService(self.db, self.knowledge, runtime)
        generated = evaluation.generate_silver_cases(self.unit_id, count=4)
        self.assertEqual(generated["created"], 4)
        self.assertEqual(llm.calls, 1)
        cases = evaluation.list_cases()
        self.assertTrue(all(item["status"] == "proposed" for item in cases))

        promoted = evaluation.review_case(cases[0]["id"], "promote_gold", "总工")
        self.assertEqual(promoted["source_type"], "gold")
        self.assertEqual(promoted["status"], "approved")
        gold = evaluation.list_cases(status="approved", source_type="gold")
        self.assertEqual(len(gold), 1)

    def test_independent_ai_review_approves_and_rejects_silver_cases(self) -> None:
        llm = SilverCaseLlm()
        runtime = AiRuntime(self.db, llm)  # type: ignore[arg-type]
        audit = AuditService(self.db)
        evaluation = RetrievalEvaluationService(self.db, self.knowledge, runtime, audit)
        evaluation.generate_silver_cases(self.unit_id, count=4, dataset_name="ai-review")
        result = evaluation.review_silver_cases_ai("ai-review")

        self.assertEqual(result["approved"], 3)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["needs_review"], 0)
        cases = evaluation.list_cases("ai-review")
        self.assertEqual(sum(item["ai_review_status"] == "passed" for item in cases), 3)
        self.assertEqual(sum(item["ai_review_status"] == "rejected" for item in cases), 1)
        self.assertEqual(evaluation.list_datasets()[0]["dataset_name"], "ai-review")
        self.assertTrue(audit.verify_chain()["valid"])

    def test_generation_round_bypasses_cache_for_automatic_coverage_repair(self) -> None:
        llm = SilverCaseLlm()
        runtime = AiRuntime(self.db, llm)  # type: ignore[arg-type]
        evaluation = RetrievalEvaluationService(self.db, self.knowledge, runtime)
        first = evaluation.generate_silver_cases(self.unit_id, count=4, dataset_name="repair")
        second = evaluation.generate_silver_cases(
            self.unit_id,
            count=4,
            dataset_name="repair",
            generation_round=2,
            required_query_kinds=["synonym"],
        )

        self.assertEqual(first["generation_round"], 1)
        self.assertEqual(second["generation_round"], 2)
        self.assertEqual(llm.calls, 2)
        self.assertEqual(len(first["case_ids"]), 4)

    def test_calculates_recall_mrr_and_negative_rejection(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_eval_cases(
                    dataset_name,source_type,query,query_kind,industry,unit_type,
                    expected_unit_ids_json,excluded_unit_ids_json,source_unit_id,status,reviewed_by
                ) VALUES ('default','silver',?,'direct','','',?,'[]',?,'approved','测试')
                """,
                ("施工工艺", json.dumps([self.unit_id]), self.unit_id),
            )
            conn.execute(
                """
                INSERT INTO retrieval_eval_cases(
                    dataset_name,source_type,query,query_kind,industry,unit_type,
                    expected_unit_ids_json,excluded_unit_ids_json,source_unit_id,status,reviewed_by
                ) VALUES ('default','silver',?,'confusing_negative','','','[]',?,?, 'approved','测试')
                """,
                ("消防水泵联动控制要求", json.dumps([self.unit_id]), self.unit_id),
            )
        evaluation = RetrievalEvaluationService(self.db, self.knowledge, AiRuntime(self.db))
        result = evaluation.run(top_k=10)
        self.assertEqual(result["metrics"]["recall_at_k"], 1.0)
        self.assertEqual(result["metrics"]["mrr"], 1.0)
        self.assertEqual(result["metrics"]["negative_rejection_rate"], 1.0)
        self.assertEqual(evaluation.list_runs()[0]["case_count"], 2)

    def test_failed_negative_probe_is_rejected(self) -> None:
        title = self.knowledge.get_unit(self.unit_id)["title"]
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_eval_cases(
                    dataset_name,source_type,query,query_kind,expected_unit_ids_json,
                    excluded_unit_ids_json,source_unit_id,status,reviewed_by
                ) VALUES ('probe','silver',?,'confusing_negative','[]',?,?,'approved','AI独立复核')
                """,
                (title, json.dumps([self.unit_id]), self.unit_id),
            )
        evaluation = RetrievalEvaluationService(self.db, self.knowledge, AiRuntime(self.db))
        result = evaluation.repair_confusing_negatives("probe")
        self.assertEqual(result["rejected"], 1)
        case = evaluation.list_cases("probe")[0]
        self.assertEqual(case["status"], "rejected")
        self.assertEqual(case["ai_review_decision"], "retrieval_probe_failed")


if __name__ == "__main__":
    unittest.main()
