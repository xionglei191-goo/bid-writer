from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from bid_writer.acceptance import run_acceptance, write_acceptance_report
from bid_writer.db import connect, init_db
from bid_writer.exporter import export_docx, export_package
from bid_writer.settings import EXPORT_DIR


def main() -> int:
    tender_id = 190
    conn = connect()
    init_db(conn)
    internal_docx = export_docx(tender_id, conn=conn)
    internal_package = export_package(tender_id, conn=conn)
    reports = write_acceptance_report(tender_id, EXPORT_DIR / "acceptance", conn=conn)
    acceptance = run_acceptance(
        tender_id,
        conclusion="自动基线验收：内部审查包已生成，正式交付仍以硬门禁和人工终审为准。",
        exports={"internal_docx": internal_docx["path"], "internal_package": internal_package["path"], **reports},
        conn=conn,
    )
    print(
        json.dumps(
            {
                "internal_docx": internal_docx["path"],
                "internal_package": internal_package["path"],
                "acceptance_reports": reports,
                "quality_score": acceptance["quality_score"],
                "ready": acceptance["ready"],
                "blockers": acceptance["blockers"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
