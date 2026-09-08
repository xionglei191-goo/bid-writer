from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .database import Database
from .utils import content_hash


_SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "cookie", "api_key"}


def _safe_details(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if any(part in str(key).lower() for part in _SENSITIVE_KEYS) else _safe_details(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_details(item) for item in value]
    text = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
    return text[:2000] if isinstance(text, str) else text


class AuditService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        action: str,
        target_type: str,
        target_id: str | int = "",
        *,
        actor_user_id: int | None = None,
        actor_name: str = "system",
        outcome: str = "success",
        details: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        request_id = request_id or uuid4().hex
        payload = json.dumps(_safe_details(details or {}), ensure_ascii=False, sort_keys=True)
        with self.db.connect() as conn:
            if self.db.backend == "postgresql":
                conn.execute("SELECT pg_advisory_xact_lock(?)", (1_604_202_608,))
            previous = conn.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
            previous_hash = str(previous[0]) if previous else ""
            event_hash = content_hash(
                "|".join([previous_hash, request_id, actor_name, action, target_type, str(target_id), outcome, payload])
            )
            cursor = conn.execute(
                """
                INSERT INTO audit_events(
                    request_id,actor_user_id,actor_name,action,target_type,target_id,outcome,
                    details_json,previous_hash,event_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (request_id, actor_user_id, actor_name, action, target_type, str(target_id), outcome, payload, previous_hash, event_hash),
            )
            event_id = int(cursor.lastrowid)
        return {"id": event_id, "request_id": request_id, "event_hash": event_hash}

    def list_events(self, limit: int = 200, target_type: str = "", target_id: str = "") -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_type:
            clauses.append("target_type=?")
            params.append(target_type)
        if target_id:
            clauses.append("target_id=?")
            params.append(target_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.rows(
            f"SELECT * FROM audit_events {where} ORDER BY id DESC LIMIT ?",
            [*params, max(1, min(limit, 1000))],
        )
        for row in rows:
            row["details"] = json.loads(row.pop("details_json", "{}"))
        return rows

    def verify_chain(self) -> dict[str, Any]:
        rows = list(reversed(self.db.rows("SELECT * FROM audit_events ORDER BY id DESC")))
        known_hashes = {""}
        latest_hash = ""
        branches = 0
        for row in rows:
            expected = content_hash(
                "|".join(
                    [
                        row["previous_hash"],
                        row["request_id"],
                        row["actor_name"],
                        row["action"],
                        row["target_type"],
                        row["target_id"],
                        row["outcome"],
                        row["details_json"],
                    ]
                )
            )
            if row["previous_hash"] not in known_hashes or row["event_hash"] != expected:
                return {"valid": False, "event_id": row["id"], "events": len(rows)}
            if row["previous_hash"] != latest_hash:
                branches += 1
            known_hashes.add(expected)
            latest_hash = expected
        return {"valid": True, "event_id": None, "events": len(rows), "head": latest_hash, "branches": branches}
