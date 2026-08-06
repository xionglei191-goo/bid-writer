from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
test_db = BACKEND_DIR.parent / "data" / "test_workflow_confirmation.sqlite"
for suffix in ("", "-wal", "-shm"):
    Path(str(test_db) + suffix).unlink(missing_ok=True)
os.environ["BID_WRITER_DB"] = str(test_db)

from bid_writer.db import connect, init_db
from bid_writer.workflow_confirmations import list_workflow_confirmations, set_workflow_confirmation


def main() -> int:
    conn = connect()
    init_db(conn)
    tender_id = int(
        conn.execute(
            "INSERT INTO tenders (name, industry, raw_text) VALUES (?, ?, ?)",
            ("阶段确认测试", "医院", "招标要求正文"),
        ).lastrowid
    )
    conn.execute(
        """
        INSERT INTO project_profiles (
            tender_id, project_name, project_type, structure_type, building_area,
            duration_days, quality_target, safety_target
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tender_id, "测试医院", "医疗建筑", "框架结构", "10000平方米", 300, "合格", "零事故"),
    )
    conn.execute(
        "INSERT INTO requirements (tender_id, kind, content) VALUES (?, ?, ?)",
        (tender_id, "技术要求", "编制施工组织设计"),
    )
    conn.commit()

    assert list_workflow_confirmations(tender_id, conn=conn)["items"]["parse"]["status"] == "pending"
    result = set_workflow_confirmation(tender_id, "parse", conn=conn)
    assert result["items"]["parse"]["confirmed"] is True
    conn.execute("UPDATE project_profiles SET project_type = ? WHERE tender_id = ?", ("医院改扩建", tender_id))
    conn.commit()
    assert list_workflow_confirmations(tender_id, conn=conn)["items"]["parse"]["status"] == "stale"

    conn.execute(
        "INSERT INTO bid_strategies (tender_id, positioning, win_themes) VALUES (?, ?, ?)",
        (tender_id, "医疗工程精准履约", "不停诊施工"),
    )
    plan_id = int(
        conn.execute(
            "INSERT INTO section_plans (tender_id, order_no, section_title) VALUES (?, ?, ?)",
            (tender_id, 1, "施工总体部署"),
        ).lastrowid
    )
    conn.commit()
    result = set_workflow_confirmation(tender_id, "outline", conn=conn)
    assert result["items"]["outline"]["confirmed"] is True
    draft_id = int(
        conn.execute(
            "INSERT INTO drafts (tender_id, section_title, content) VALUES (?, ?, ?)",
            (tender_id, "施工总体部署", "第一版正文"),
        ).lastrowid
    )
    conn.execute("UPDATE section_plans SET draft_id = ?, status = ? WHERE id = ?", (draft_id, "generated", plan_id))
    conn.commit()
    assert list_workflow_confirmations(tender_id, conn=conn)["items"]["outline"]["confirmed"] is True

    result = set_workflow_confirmation(tender_id, "review", conn=conn)
    assert result["items"]["review"]["confirmed"] is True
    conn.execute("UPDATE drafts SET content = ? WHERE id = ?", ("第二版正文", draft_id))
    conn.commit()
    assert list_workflow_confirmations(tender_id, conn=conn)["items"]["review"]["status"] == "stale"
    conn.close()
    print("workflow confirmations ok: pending, confirmed and stale transitions verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
