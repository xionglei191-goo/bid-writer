from __future__ import annotations

import json
import math
from typing import Any

from .ai_runtime import AiRuntime, SILVER_QUERY_PROMPT, SILVER_REVIEW_PROMPT
from .audit import AuditService
from .database import Database
from .knowledge.service import KnowledgeService
from .utils import content_hash, normalize_text, parse_json


class RetrievalEvaluationService:
    def __init__(self, db: Database, knowledge: KnowledgeService, ai_runtime: AiRuntime, audit: AuditService | None = None) -> None:
        self.db = db
        self.knowledge = knowledge
        self.ai_runtime = ai_runtime
        self.audit = audit

    def generate_silver_cases(
        self,
        unit_id: int,
        count: int = 8,
        dataset_name: str = "default",
        *,
        generation_round: int = 1,
        required_query_kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        count = max(4, min(int(count), 12))
        generation_round = max(1, min(int(generation_round), 3))
        required_query_kinds = sorted(
            {
                str(value)
                for value in (required_query_kinds or [])
                if str(value) in {"direct", "synonym", "tender_clause", "confusing_negative"}
            }
        )
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT u.id,u.title,u.industry,u.unit_type,v.content,p.id AS publication_id,p.content_hash
                FROM knowledge_units u
                JOIN knowledge_publications p ON p.unit_id=u.id AND p.status='published'
                JOIN knowledge_versions v ON v.id=p.version_id
                WHERE u.id=? ORDER BY p.publication_version DESC LIMIT 1
                """,
                (unit_id,),
            ).fetchone()
        if not row:
            raise ValueError("只能从当前已发布知识生成评测样本")
        unit = dict(row)
        prompt = SILVER_QUERY_PROMPT.render(
            count=str(count),
            title=unit["title"],
            industry=unit["industry"] or "通用",
            unit_type=unit["unit_type"],
            content=unit["content"][:12000],
        )
        if generation_round > 1 or required_query_kinds:
            prompt += (
                f"\n\n这是自动补齐第{generation_round}轮。请生成与之前不同的问法；"
                f"本轮必须覆盖：{','.join(required_query_kinds) or 'direct,synonym'}。"
            )
        result = self.ai_runtime.execute(
            SILVER_QUERY_PROMPT,
            prompt,
            {
                "dataset_name": dataset_name,
                "count": count,
                "unit_id": unit_id,
                "publication_id": unit["publication_id"],
                "publication_content_hash": unit["content_hash"],
                "content": unit["content"][:12000],
                "generation_round": generation_round,
                "required_query_kinds": required_query_kinds,
            },
            task_type="silver_query_generation",
            target_type="knowledge_unit",
            target_id=unit_id,
            max_output_tokens=4000,
        )
        payload = result.get("payload")
        if not payload:
            raise ValueError(result.get("error") or "白银评测问题生成失败")
        created = 0
        case_ids: list[int] = []
        with self.db.connect() as conn:
            for item in payload["cases"][:count]:
                query = normalize_text(item["query"])
                expected = [unit_id] if item["expected_match"] else []
                excluded = [] if item["expected_match"] else [unit_id]
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO retrieval_eval_cases(
                        dataset_name,source_type,query,query_kind,industry,unit_type,expected_unit_ids_json,
                        excluded_unit_ids_json,source_unit_id,status,generated_by_run_id
                    ) VALUES (?,'silver',?,?,?,?,?,?,?,'proposed',?)
                    """,
                    (
                        dataset_name,
                        query,
                        item["query_kind"],
                        unit["industry"] or "",
                        unit["unit_type"],
                        json.dumps(expected),
                        json.dumps(excluded),
                        unit_id,
                        result["run_id"],
                    ),
                )
                if cursor.rowcount:
                    created += 1
                    case_ids.append(int(cursor.lastrowid))
        return {
            "dataset_name": dataset_name,
            "unit_id": unit_id,
            "created": created,
            "case_ids": case_ids,
            "generation_round": generation_round,
            "ai_run_id": result["run_id"],
            "cached": bool(result.get("cached")),
        }

    def list_cases(self, dataset_name: str = "default", status: str = "", source_type: str = "") -> list[dict[str, Any]]:
        clauses = ["dataset_name=?"]
        params: list[Any] = [dataset_name]
        if status:
            clauses.append("status=?")
            params.append(status)
        if source_type:
            clauses.append("source_type=?")
            params.append(source_type)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM retrieval_eval_cases WHERE {' AND '.join(clauses)} ORDER BY id DESC",
                params,
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["expected_unit_ids"] = parse_json(item.pop("expected_unit_ids_json"), [])
            item["excluded_unit_ids"] = parse_json(item.pop("excluded_unit_ids_json"), [])
            item["ai_review_issues"] = parse_json(item.pop("ai_review_issues_json", "[]"), [])
        return items

    def list_datasets(self) -> list[dict[str, Any]]:
        rows = self.db.rows(
            """
            SELECT dataset_name,COUNT(*) AS case_count,
                SUM(CASE WHEN status='proposed' THEN 1 ELSE 0 END) AS proposed_count,
                SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved_count,
                SUM(CASE WHEN source_type='gold' AND status='approved' THEN 1 ELSE 0 END) AS gold_count,
                MAX(created_at) AS updated_at
            FROM retrieval_eval_cases GROUP BY dataset_name ORDER BY MAX(id) DESC
            """
        )
        for row in rows:
            latest = self.db.row(
                "SELECT id,top_k,metrics_json,created_at FROM retrieval_eval_runs WHERE dataset_name=? ORDER BY id DESC LIMIT 1",
                (row["dataset_name"],),
            )
            row["latest_run"] = None
            if latest:
                latest["metrics"] = parse_json(latest.pop("metrics_json"), {})
                row["latest_run"] = latest
        return rows

    def review_silver_cases_ai(self, dataset_name: str, case_ids: list[int] | None = None) -> dict[str, Any]:
        cases = self.list_cases(dataset_name=dataset_name, status="proposed", source_type="silver")
        selected_ids = {int(value) for value in (case_ids or [])}
        if selected_ids:
            cases = [item for item in cases if int(item["id"]) in selected_ids]
        if not cases:
            raise ValueError("没有可进行 AI 复核的白银候选")
        cases = cases[:100]
        unit_ids = sorted({int(item["source_unit_id"]) for item in cases if item.get("source_unit_id")})
        placeholders = ",".join("?" for _ in unit_ids)
        units = self.db.rows(
            f"""
            SELECT u.id,u.title,u.industry,u.unit_type,v.content
            FROM knowledge_units u
            JOIN knowledge_publications p ON p.unit_id=u.id AND p.status='published'
            JOIN knowledge_versions v ON v.id=p.version_id
            WHERE u.id IN ({placeholders}) ORDER BY u.id
            """,
            unit_ids,
        )
        unit_map = {int(item["id"]): item for item in units}
        material = []
        for case in cases:
            unit = unit_map.get(int(case.get("source_unit_id") or 0), {})
            material.append(
                {
                    "case_id": int(case["id"]),
                    "query": case["query"],
                    "query_kind": case["query_kind"],
                    "expected_match": bool(case["expected_unit_ids"]),
                    "knowledge": {
                        "unit_id": unit.get("id"),
                        "title": unit.get("title", ""),
                        "industry": unit.get("industry", ""),
                        "unit_type": unit.get("unit_type", ""),
                        "content": str(unit.get("content", ""))[:8000],
                    },
                }
            )
        result = self.ai_runtime.execute(
            SILVER_REVIEW_PROMPT,
            SILVER_REVIEW_PROMPT.render(review_material=json.dumps(material, ensure_ascii=False, indent=2)),
            {"dataset_name": dataset_name, "cases": material},
            task_type="silver_query_review",
            target_type="retrieval_dataset",
            max_output_tokens=8000,
            use_cache=False,
        )
        payload = result.get("payload")
        if not payload:
            raise ValueError(result.get("error") or "白银问题 AI 复核失败")
        reviews = {int(item["case_id"]): item for item in payload["reviews"]}
        counts = {"approved": 0, "rejected": 0, "needs_review": 0}
        with self.db.connect() as conn:
            for case in cases:
                case_id = int(case["id"])
                review = reviews.get(case_id) or {"decision": "escalate", "confidence": 0, "issues": []}
                decision = str(review["decision"])
                confidence = float(review["confidence"])
                issues = review.get("issues") or []
                blocking = any(item.get("severity") in {"medium", "high"} for item in issues)
                if decision == "pass" and confidence >= 0.92 and not blocking:
                    status = "approved"
                    ai_status = "passed"
                    counts["approved"] += 1
                elif decision == "reject" and confidence >= 0.92:
                    status = "rejected"
                    ai_status = "rejected"
                    counts["rejected"] += 1
                else:
                    status = "proposed"
                    ai_status = "needs_review"
                    counts["needs_review"] += 1
                conn.execute(
                    """
                    UPDATE retrieval_eval_cases SET status=?,ai_review_status=?,ai_review_decision=?,
                        ai_review_confidence=?,ai_review_issues_json=?,ai_review_run_id=?,
                        reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (
                        status,
                        ai_status,
                        decision,
                        confidence,
                        json.dumps(issues, ensure_ascii=False),
                        result["run_id"],
                        "AI独立复核" if status != "proposed" else "",
                        case_id,
                    ),
                )
        if self.audit:
            self.audit.record(
                "evaluation.silver.ai_review",
                "retrieval_dataset",
                dataset_name,
                details={**counts, "case_count": len(cases), "ai_run_id": result["run_id"]},
            )
        return {"dataset_name": dataset_name, "case_count": len(cases), "ai_run_id": result["run_id"], **counts}

    def batch_review_cases(self, case_ids: list[int], action: str, reviewer: str) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(int(value) for value in case_ids))[:500]
        if not unique_ids:
            raise ValueError("请选择至少一条评测问题")
        results = [self.review_case(case_id, action, reviewer) for case_id in unique_ids]
        if self.audit:
            self.audit.record(
                "evaluation.cases.batch_review",
                "retrieval_case",
                ",".join(str(value) for value in unique_ids),
                actor_name=reviewer.strip(),
                details={"action": action, "count": len(results)},
            )
        return {"action": action, "processed": len(results), "case_ids": unique_ids}

    def repair_confusing_negatives(self, dataset_name: str, search_fn=None) -> dict[str, Any]:
        negatives = self.list_cases(dataset_name, status="approved", source_type="silver")
        negatives = [item for item in negatives if item["query_kind"] == "confusing_negative"]
        rejected_ids: list[int] = []
        for case in negatives:
            retrieved_ids = {int(item["unit_id"]) for item in (search_fn or self.knowledge.search)(case["query"], "", "", 10)}
            if retrieved_ids.intersection(int(value) for value in case["excluded_unit_ids"]):
                rejected_ids.append(int(case["id"]))
        if rejected_ids:
            placeholders = ",".join("?" for _ in rejected_ids)
            with self.db.connect() as conn:
                conn.execute(
                    f"""
                    UPDATE retrieval_eval_cases SET status='rejected',ai_review_status='rejected',
                        ai_review_decision='retrieval_probe_failed',ai_review_confidence=1,
                        ai_review_issues_json=?,
                        reviewed_by='确定性检索探针',reviewed_at=CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})
                    """,
                    (
                        json.dumps(
                            [{"code": "excluded_unit_retrieved", "severity": "high", "message": "检索探针命中了应排除知识"}],
                            ensure_ascii=False,
                        ),
                        *rejected_ids,
                    ),
                )

        approved = self.list_cases(dataset_name, status="approved", source_type="silver")
        positives = [item for item in approved if item["expected_unit_ids"]]
        valid_negative_units = {
            int(item["source_unit_id"])
            for item in approved
            if item["query_kind"] == "confusing_negative" and item.get("source_unit_id")
        }
        source_units = sorted({int(item["source_unit_id"]) for item in positives if item.get("source_unit_id")})
        created = 0
        with self.db.connect() as conn:
            for unit_id in source_units:
                if unit_id in valid_negative_units:
                    continue
                donors = [item for item in positives if int(item.get("source_unit_id") or 0) != unit_id]
                for donor in donors:
                    query = f"相关专业对照：{donor['query']}"
                    retrieved_ids = {int(item["unit_id"]) for item in (search_fn or self.knowledge.search)(query, "", "", 10)}
                    if unit_id in retrieved_ids:
                        continue
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO retrieval_eval_cases(
                            dataset_name,source_type,query,query_kind,industry,unit_type,
                            expected_unit_ids_json,excluded_unit_ids_json,source_unit_id,status,
                            reviewed_by,reviewed_at,ai_review_status,ai_review_decision,ai_review_confidence,
                            ai_review_issues_json
                        ) VALUES (?,'silver',?,'confusing_negative','','','[]',?,?,'approved',
                            '确定性跨知识构造',CURRENT_TIMESTAMP,'passed','cross_unit_negative',1,'[]')
                        """,
                        (dataset_name, query, json.dumps([unit_id]), unit_id),
                    )
                    if cursor.rowcount:
                        created += 1
                        break
        if self.audit and (rejected_ids or created):
            self.audit.record(
                "evaluation.negatives.repair",
                "retrieval_dataset",
                dataset_name,
                details={"rejected_case_ids": rejected_ids, "created": created},
            )
        return {"dataset_name": dataset_name, "rejected": len(rejected_ids), "created": created}

    def review_case(self, case_id: int, action: str, reviewer: str) -> dict[str, Any]:
        if action not in {"approve", "reject", "promote_gold"}:
            raise ValueError("action必须为approve、reject或promote_gold")
        if not reviewer.strip():
            raise ValueError("审核人不能为空")
        status = "rejected" if action == "reject" else "approved"
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM retrieval_eval_cases WHERE id=?", (case_id,)).fetchone()
            if not row:
                raise KeyError("评测样本不存在")
            source_type = "gold" if action == "promote_gold" else row["source_type"]
            conn.execute(
                """
                UPDATE retrieval_eval_cases SET status=?,source_type=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, source_type, reviewer.strip(), case_id),
            )
        return {"case_id": case_id, "status": status, "source_type": source_type, "reviewed_by": reviewer.strip()}

    def run(self, dataset_name: str = "default", source_type: str = "silver", top_k: int = 10, search_fn=None) -> dict[str, Any]:
        top_k = max(1, min(int(top_k), 50))
        cases = self.list_cases(dataset_name=dataset_name, status="approved", source_type=source_type)
        if not cases:
            raise ValueError("没有已批准的评测样本")
        results: list[dict[str, Any]] = []
        positive_hits = 0
        reciprocal_rank_total = 0.0
        ndcg_total = 0.0
        baseline_hits = 0
        baseline_reciprocal_rank_total = 0.0
        positive_count = 0
        negative_passes = 0
        baseline_negative_passes = 0
        negative_count = 0
        for case in cases:
            matches = (search_fn or self.knowledge.search)(case["query"], case["industry"], case["unit_type"], top_k)
            hybrid_callback = getattr(self.knowledge, "hybrid_search", None)
            try:
                self.knowledge.hybrid_search = None
                baseline_matches = self.knowledge.search(case["query"], case["industry"], case["unit_type"], top_k)
            finally:
                self.knowledge.hybrid_search = hybrid_callback
            retrieved_ids = [int(item["unit_id"]) for item in matches]
            baseline_ids = [int(item["unit_id"]) for item in baseline_matches]
            expected = {int(value) for value in case["expected_unit_ids"]}
            excluded = {int(value) for value in case["excluded_unit_ids"]}
            if expected:
                positive_count += 1
                ranks = [index + 1 for index, value in enumerate(retrieved_ids) if value in expected]
                hit = bool(ranks)
                positive_hits += int(hit)
                reciprocal_rank_total += 1.0 / min(ranks) if ranks else 0.0
                dcg = sum(1.0 / math.log2(index + 2) for index, value in enumerate(retrieved_ids) if value in expected)
                ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(expected), top_k)))
                ndcg_total += dcg / ideal if ideal else 0.0
                baseline_ranks = [index + 1 for index, value in enumerate(baseline_ids) if value in expected]
                baseline_hits += int(bool(baseline_ranks))
                baseline_reciprocal_rank_total += 1.0 / min(baseline_ranks) if baseline_ranks else 0.0
                passed = hit
            else:
                negative_count += 1
                passed = not bool(excluded.intersection(retrieved_ids))
                negative_passes += int(passed)
                baseline_negative_passes += int(not bool(excluded.intersection(baseline_ids)))
            results.append(
                {
                    "case_id": case["id"],
                    "query": case["query"],
                    "query_kind": case["query_kind"],
                    "retrieved_unit_ids": retrieved_ids,
                    "baseline_unit_ids": baseline_ids,
                    "passed": passed,
                }
            )
        metrics = {
            "case_count": len(cases),
            "positive_count": positive_count,
            "negative_count": negative_count,
            "recall_at_k": round(positive_hits / positive_count, 4) if positive_count else None,
            "mrr": round(reciprocal_rank_total / positive_count, 4) if positive_count else None,
            "ndcg_at_k": round(ndcg_total / positive_count, 4) if positive_count else None,
            "baseline_recall_at_k": round(baseline_hits / positive_count, 4) if positive_count else None,
            "baseline_mrr": round(baseline_reciprocal_rank_total / positive_count, 4) if positive_count else None,
            "negative_rejection_rate": round(negative_passes / negative_count, 4) if negative_count else None,
            "baseline_negative_rejection_rate": round(baseline_negative_passes / negative_count, 4) if negative_count else None,
            "pass_rate": round(sum(1 for item in results if item["passed"]) / len(results), 4),
        }
        if positive_count:
            metrics["recall_lift"] = round(float(metrics["recall_at_k"]) - float(metrics["baseline_recall_at_k"]), 4)
            metrics["mrr_lift"] = round(float(metrics["mrr"]) - float(metrics["baseline_mrr"]), 4)
        if negative_count:
            metrics["negative_rejection_lift"] = round(
                float(metrics["negative_rejection_rate"]) - float(metrics["baseline_negative_rejection_rate"]), 4
            )
        snapshot = self._publication_snapshot_hash()
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO retrieval_eval_runs(
                    dataset_name,source_type,top_k,case_count,publication_snapshot_hash,metrics_json,results_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (dataset_name, source_type, top_k, len(cases), snapshot, json.dumps(metrics), json.dumps(results, ensure_ascii=False)),
            )
            run_id = int(cursor.lastrowid)
        return {"run_id": run_id, "dataset_name": dataset_name, "source_type": source_type, "top_k": top_k, "metrics": metrics, "results": results}

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM retrieval_eval_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["metrics"] = parse_json(item.pop("metrics_json"), {})
            item.pop("results_json", None)
        return items

    def _publication_snapshot_hash(self) -> str:
        rows = self.db.rows("SELECT id,unit_id,content_hash FROM knowledge_publications WHERE status='published' ORDER BY id")
        return content_hash(json.dumps(rows, sort_keys=True))
