from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import CurrentMessage


redis_url = os.environ.get("BID_WRITER_REDIS_URL", "redis://redis:6379/0")
broker = RedisBroker(url=redis_url)
broker.add_middleware(CurrentMessage())
dramatiq.set_broker(broker)


@dramatiq.actor(max_retries=0, time_limit=6 * 60 * 60 * 1000)
def run_app_job(job_id: int) -> None:
    from .app import app as application

    message = CurrentMessage.get_current_message()
    message_id = message.message_id if message else ""
    application.state.jobs.run(job_id, message_id=message_id)
