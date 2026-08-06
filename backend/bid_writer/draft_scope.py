from __future__ import annotations

import sqlite3
from typing import Any

from .db import rows_to_dicts


def active_drafts(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    """Return plan-linked drafts plus the latest unlinked draft for uncovered titles."""
    rows = conn.execute(
        """
        SELECT DISTINCT d.*
        FROM drafts d
        JOIN section_plans sp ON sp.draft_id = d.id
        WHERE sp.tender_id = ?

        UNION ALL

        SELECT d.*
        FROM drafts d
        WHERE d.tender_id = ?
          AND d.id = (
              SELECT MAX(latest.id)
              FROM drafts latest
              WHERE latest.tender_id = d.tender_id
                AND latest.section_title = d.section_title
          )
          AND NOT EXISTS (
              SELECT 1
              FROM section_plans linked
              WHERE linked.tender_id = d.tender_id
                AND linked.section_title = d.section_title
                AND linked.draft_id IS NOT NULL
          )
        ORDER BY id
        """,
        (tender_id, tender_id),
    ).fetchall()
    return rows_to_dicts(rows)
