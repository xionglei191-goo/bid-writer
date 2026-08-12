from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker


redis_url = os.environ.get("BID_WRITER_REDIS_URL", "redis://redis:6379/0")
dramatiq.set_broker(RedisBroker(url=redis_url))


@dramatiq.actor(max_retries=0, time_limit=6 * 60 * 60 * 1000)
def run_app_job(job_id: int) -> None:
    from .app import app as application

    application.state.jobs.run(job_id)
