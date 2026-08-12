from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import CurrentMessage, Middleware


redis_url = os.environ.get("BID_WRITER_REDIS_URL", "redis://redis:6379/0")


class DurableJobRecovery(Middleware):
    def after_process_boot(self, broker) -> None:
        from .app import app as application

        db = application.state.db
        with db.connect() as conn:
            interrupted = conn.execute(
                """
                SELECT id,target_id FROM app_jobs
                WHERE status='running' AND job_type='knowledge.corpus.tick'
                """
            ).fetchall()
            for job in interrupted:
                conn.execute(
                    "UPDATE app_jobs SET status='retrying',stage='queued',error_code='worker_restart',error_message='工作进程重启后自动恢复',finished_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (job["id"],),
                )
                run_id = str(job["target_id"]).split(":", 1)[0]
                if run_id.isdigit():
                    conn.execute(
                        "UPDATE corpus_run_items SET status='retrying',next_retry_at=NULL,error_code='worker_restart',error_message='工作进程重启后自动恢复',updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND status='running'",
                        (int(run_id),),
                    )
        application.state.jobs.redispatch_unfinished()


broker = RedisBroker(url=redis_url)
broker.add_middleware(CurrentMessage())
broker.add_middleware(DurableJobRecovery())
dramatiq.set_broker(broker)


@dramatiq.actor(max_retries=0, time_limit=6 * 60 * 60 * 1000)
def run_app_job(job_id: int) -> None:
    from .app import app as application

    message = CurrentMessage.get_current_message()
    message_id = message.message_id if message else ""
    application.state.jobs.run(job_id, message_id=message_id)
