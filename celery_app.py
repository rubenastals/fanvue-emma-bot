"""
Celery application.

Runs the heavy pipeline (DeepSeek calls, DB writes, Fanvue sends) off the
web request thread, and applies the human-like reply delay via task
scheduling (countdown) instead of blocking the webhook.

Run a worker:
    celery -A celery_app.celery_app worker --loglevel=info

Run the beat scheduler (for periodic re-engagement):
    celery -A celery_app.celery_app beat --loglevel=info
"""
from celery import Celery

from config import config

celery_app = Celery(
    "emma",
    broker=config.CELERY_BROKER_URL,
    backend=config.CELERY_RESULT_BACKEND,
    include=["tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Periodic re-engagement scan.
celery_app.conf.beat_schedule = {
    "reengagement-scan": {
        "task": "tasks.run_reengagement",
        "schedule": float(config.REENGAGEMENT_INTERVAL_SECONDS),
    }
}
