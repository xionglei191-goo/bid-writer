"""Command line entry point for the V2 local system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_writer_v2.ai_runtime import AiRuntime
from bid_writer_v2.database import Database
from bid_writer_v2.evaluation import RetrievalEvaluationService
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.knowledge.pipeline import KnowledgePipelineService
from bid_writer_v2.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="bid-writer V2 management commands")
    parser.add_argument("command", choices=["scan", "queue-all", "work", "cluster", "metrics", "ai-process-document", "ai-accept-ready", "eval-silver", "eval-gold"])
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dataset", default="default")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--document-id", type=int)
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--reviewer", default="技术负责人")
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.ensure_directories()
    db = Database(settings.db_path)
    db.migrate()
    service = KnowledgeService(db, settings)
    if args.command == "scan":
        result = service.scan_sources()
    elif args.command == "queue-all":
        batches = []
        while True:
            batch = service.create_jobs(limit=500)
            batches.append(batch)
            if batch["created"] == 0:
                break
        result = {"created": sum(item["created"] for item in batches), "batches": len(batches)}
    elif args.command == "work":
        result = service.run_pending_jobs(limit=args.limit)
    elif args.command == "cluster":
        result = service.cluster_units()
    elif args.command == "metrics":
        result = service.metrics()
    elif args.command == "ai-process-document":
        if not args.document_id:
            parser.error("ai-process-document需要--document-id")
        pipeline = KnowledgePipelineService(db, service, AiRuntime(db))
        result = pipeline.process_document(args.document_id, args.max_candidates)
    elif args.command == "ai-accept-ready":
        pipeline = KnowledgePipelineService(db, service, AiRuntime(db))
        result = pipeline.accept_ready(args.reviewer, args.limit)
    elif args.command in {"eval-silver", "eval-gold"}:
        evaluation = RetrievalEvaluationService(db, service, AiRuntime(db))
        result = evaluation.run(
            dataset_name=args.dataset,
            source_type=args.command.removeprefix("eval-"),
            top_k=args.top_k,
        )
    else:
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
