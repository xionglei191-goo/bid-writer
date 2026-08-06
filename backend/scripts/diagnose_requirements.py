from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from bid_writer.db import connect, init_db
from bid_writer.response_matrix import build_response_matrix


def main() -> int:
    tender_id = int(sys.argv[1]) if len(sys.argv) > 1 else 190
    conn = connect()
    init_db(conn)
    report = build_response_matrix(tender_id, conn=conn)
    compact = {
        "summary": report["summary"],
        "requirements": [
            {
                "id": item["id"],
                "scope": item["response_scope"],
                "kind": item["kind"],
                "priority": item["priority"],
                "status": item["response_status"],
                "score_weight": item["score_weight"],
                "content": item["content"],
                "planned_sections": [row["section_title"] for row in item["planned_sections"]],
                "evidence_score": (item.get("best_evidence") or {}).get("coverage_score"),
                "evidence_heading": (item.get("best_evidence") or {}).get("heading_path"),
            }
            for item in report["requirements"]
        ],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
