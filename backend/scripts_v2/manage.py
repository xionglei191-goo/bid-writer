"""Command line entry point for the V2 local system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="bid-writer V2 management commands")
    parser.add_argument("command", choices=["scan", "queue-all", "work", "cluster", "metrics"])
    parser.add_argument("--limit", type=int, default=100)
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
    else:
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
