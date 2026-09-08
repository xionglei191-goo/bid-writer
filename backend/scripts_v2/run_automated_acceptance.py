from __future__ import annotations

import argparse
import json
from typing import Any

from bid_writer_v2.app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the non-human retrieval acceptance checks.")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--skip-ai-review", action="store_true")
    parser.add_argument("--allow-below-target", action="store_true")
    args = parser.parse_args()

    evaluation = app.state.evaluation
    datasets = evaluation.list_datasets()
    dataset_name = args.dataset or (datasets[0]["dataset_name"] if datasets else "")
    if not dataset_name:
        raise SystemExit("No retrieval evaluation dataset exists")

    ai_review: dict[str, Any] | None = None
    proposed = evaluation.list_cases(dataset_name, status="proposed", source_type="silver")
    if proposed and not args.skip_ai_review:
        ai_review = evaluation.review_silver_cases_ai(dataset_name)

    negative_repair = evaluation.repair_confusing_negatives(dataset_name)

    approved = evaluation.list_cases(dataset_name, status="approved", source_type="silver")
    if not approved:
        raise SystemExit("No approved silver cases are available after AI review")
    run = evaluation.run(dataset_name, "silver", 10)
    audit = app.state.audit.verify_chain()
    metrics = run["metrics"]
    passed = bool(
        audit["valid"]
        and metrics.get("recall_at_k") is not None
        and metrics["recall_at_k"] >= 0.80
        and metrics.get("ndcg_at_k") is not None
        and metrics["ndcg_at_k"] >= 0.75
        and (metrics.get("negative_count") == 0 or (metrics.get("negative_rejection_rate") or 0) >= 0.80)
        and (
            (metrics.get("recall_lift") or 0) > 0
            or (metrics.get("mrr_lift") or 0) > 0
            or (metrics.get("negative_rejection_lift") or 0) > 0
        )
    )
    report = {
        "dataset_name": dataset_name,
        "ai_review": ai_review,
        "negative_repair": negative_repair,
        "evaluation_run_id": run["run_id"],
        "metrics": metrics,
        "targets": {"recall_at_10": 0.80, "ndcg_at_10": 0.75, "negative_rejection_rate": 0.80, "baseline_lift": "> 0"},
        "audit": {"valid": audit["valid"], "events": audit["events"], "branches": audit.get("branches", 0)},
        "passed": passed,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not passed and not args.allow_below_target:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
