from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .audit import AuditService
from .database import Database
from .settings import Settings
from .utils import public_payload


JobHandler = Callable[[dict[str, Any], Callable[[str, int, str, dict[str, Any] | None], None], Callable[[], bool]], dict[str, Any]]


class JobService:
    def __init__(self, db: Database, settings: Settings, audit: AuditService) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        self.handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    def enqueue(
        self,
        job_type: str,
        target_type: str,
        target_id: str | int,
        payload: dict[str, Any] | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        if job_type not in self.handlers:
            raise ValueError(f"未注册的任务类型: {job_type}")
        job_key = uuid4().hex
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO app_jobs(job_key,job_type,target_type,target_id,payload_json,created_by)
                VALUES (?,?,?,?,?,?)
                """,
                (job_key, job_type, target_type, str(target_id), json.dumps(payload or {}, ensure_ascii=False), created_by),
            )
            job_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO job_events(job_id,stage,progress,message) VALUES (?,'queued',0,'任务已进入队列')",
                (job_id,),
            )
        self.audit.record("job.enqueue", "job", job_id, actor_user_id=created_by, details={"job_type": job_type, "target": target_type})
        if self.settings.background_jobs_enabled and self.settings.redis_url:
            from .worker import run_app_job

            run_app_job.send(job_id)
        return self.get(job_id)

    def progress(self, job_id: int, stage: str, progress: int, message: str = "", details: dict[str, Any] | None = None) -> None:
        progress = max(0, min(100, int(progress)))
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE app_jobs SET stage=?,progress=?,checkpoint_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (stage, progress, json.dumps(details or {}, ensure_ascii=False), job_id),
            )
            conn.execute(
                "INSERT INTO job_events(job_id,stage,progress,message,details_json) VALUES (?,?,?,?,?)",
                (job_id, stage, progress, message[:1000], json.dumps(details or {}, ensure_ascii=False)),
            )

    def run(self, job_id: int) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in {"pending", "retrying"}:
            return job
        handler = self.handlers.get(str(job["job_type"]))
        if not handler:
            return self._fail(job_id, "handler_missing", "任务处理器未注册")
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE app_jobs SET status='running',stage='starting',attempt_count=attempt_count+1,
                    started_at=COALESCE(started_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (job_id,),
            )
        self.progress(job_id, "starting", 1, "任务开始执行")
        payload = json.loads(job.get("payload_json") or "{}")

        def report(stage: str, value: int, message: str = "", details: dict[str, Any] | None = None) -> None:
            self.progress(job_id, stage, value, message, details)

        def cancelled() -> bool:
            row = self.db.row("SELECT cancel_requested FROM app_jobs WHERE id=?", (job_id,))
            return bool(row and row["cancel_requested"])

        try:
            result = handler(payload, report, cancelled)
            if cancelled():
                with self.db.connect() as conn:
                    conn.execute(
                        "UPDATE app_jobs SET status='cancelled',stage='cancelled',finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (job_id,),
                    )
                self.progress(job_id, "cancelled", 100, "任务已取消")
            else:
                with self.db.connect() as conn:
                    conn.execute(
                        """
                        UPDATE app_jobs SET status='completed',stage='completed',progress=100,result_json=?,
                            finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        (json.dumps(result or {}, ensure_ascii=False), job_id),
                    )
                self.progress(job_id, "completed", 100, "任务执行完成")
            self.audit.record("job.complete", "job", job_id, details={"job_type": job["job_type"]})
        except Exception as exc:
            self._fail(job_id, type(exc).__name__.lower(), str(exc))
        return self.get(job_id)

    def _fail(self, job_id: int, code: str, message: str) -> dict[str, Any]:
        safe_message = message[:1000] or "任务执行失败"
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE app_jobs SET status='failed',stage='failed',error_code=?,error_message=?,
                    finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (code[:100], safe_message, job_id),
            )
            conn.execute(
                "INSERT INTO job_events(job_id,stage,progress,message) VALUES (?,'failed',100,?)",
                (job_id, safe_message),
            )
        self.audit.record("job.fail", "job", job_id, outcome="failed", details={"error_code": code, "message": safe_message})
        return self.get(job_id)

    def cancel(self, job_id: int) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        with self.db.connect() as conn:
            conn.execute("UPDATE app_jobs SET cancel_requested=1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        self.progress(job_id, "cancelling", int(job["progress"]), "已请求取消，当前步骤结束后停止")
        return self.get(job_id)

    def retry(self, job_id: int) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in {"failed", "cancelled"}:
            raise ValueError("只有失败或已取消任务可以重试")
        if int(job["attempt_count"]) >= int(job["max_attempts"]):
            raise ValueError("任务已达到最大重试次数")
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE app_jobs SET status='retrying',stage='queued',progress=0,cancel_requested=0,
                    error_code='',error_message='',finished_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (job_id,),
            )
        if self.settings.background_jobs_enabled and self.settings.redis_url:
            from .worker import run_app_job

            run_app_job.send(job_id)
        return self.get(job_id)

    def get(self, job_id: int) -> dict[str, Any]:
        row = self.db.row("SELECT * FROM app_jobs WHERE id=?", (job_id,))
        if not row:
            raise KeyError("任务不存在")
        row["payload"] = json.loads(row.get("payload_json") or "{}")
        row["result"] = public_payload(json.loads(row.get("result_json") or "{}"))
        row["checkpoint"] = json.loads(row.get("checkpoint_json") or "{}")
        row["events"] = self.events(job_id, 50)
        return row

    def list(self, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        if status:
            return self.db.rows("SELECT * FROM app_jobs WHERE status=? ORDER BY id DESC LIMIT ?", (status, max(1, min(limit, 500))))
        return self.db.rows("SELECT * FROM app_jobs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))

    def events(self, job_id: int, limit: int = 200, after_id: int = 0) -> list[dict[str, Any]]:
        return self.db.rows(
            "SELECT * FROM job_events WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
            (job_id, after_id, max(1, min(limit, 1000))),
        )

    def metrics(self) -> dict[str, int]:
        rows = self.db.rows("SELECT status,COUNT(*) AS count FROM app_jobs GROUP BY status")
        return {str(row["status"]): int(row["count"]) for row in rows}
