from __future__ import annotations

import json
import re
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from bid_writer.db import connect, init_db, row_to_dict, rows_to_dicts
from bid_writer.project_profiles import get_project_profile


def main() -> int:
    conn = connect()
    init_db(conn)
    tender_id = 190
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()) or {}
    text = str(tender.get("raw_text") or "")
    patterns = ("结构", "安全目标", "安全文明", "事故", "死亡", "重伤", "文明工地", "招标人", "建设单位", "工期", "截止", "郑州大学第一附属医院")
    matches = []
    for line in text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if clean and any(term in clean for term in patterns):
            matches.append(clean[:500])
    drafts = rows_to_dicts(
        conn.execute(
            "SELECT id, section_title, generation_mode, generation_model, generation_error, LENGTH(content) AS char_count FROM drafts WHERE tender_id = ? ORDER BY id",
            (tender_id,),
        ).fetchall()
    )
    placeholders = rows_to_dicts(
        conn.execute("SELECT id, section_title, content FROM drafts WHERE tender_id = ? AND content LIKE '%【待确认%'", (tender_id,)).fetchall()
    )
    result = {
        "tender": {key: tender.get(key) for key in ("id", "name", "industry", "region", "file_path")},
        "profile": get_project_profile(tender_id, conn=conn),
        "task": row_to_dict(conn.execute("SELECT * FROM production_tasks WHERE tender_id = ?", (tender_id,)).fetchone()),
        "raw_matches": list(dict.fromkeys(matches))[:100],
        "drafts": drafts,
        "placeholder_sections": [
            {
                "id": row["id"],
                "section_title": row["section_title"],
                "placeholders": re.findall(r"【待确认[^】]*】", str(row.get("content") or "")),
            }
            for row in placeholders
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
