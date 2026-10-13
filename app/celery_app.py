"""Celery application instance and configuration."""

from celery import Celery

from app.config import settings

celery_app = Celery("webhookforge")

celery_app.conf.update(
    broker_url=settings.broker_url,
    result_backend=settings.result_backend,

    # CRITICAL: Delay acknowledgement until task completes.
    # This enables at-least-once delivery even on worker crash.
    # Tradeoff: a crashed worker may re-deliver a task that already ran.
    # The delivery_attempts UNIQUE constraint handles duplicates.
    task_acks_late=True,

    # CRITICAL: If a worker crashes mid-task (not just an exception),
    # this ensures the task is re-queued rather than silently dropped.
    task_reject_on_worker_lost=True,

    # Prevent runaway tasks from blocking the queue
    task_soft_time_limit=30,  # seconds; raises SoftTimeLimitExceeded
    task_time_limit=60,       # hard kill after 60 seconds

    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,
)

# Discover task modules. Imported lazily so that importing app.celery_app
# (e.g. from the API for health checks) does not pull in task dependencies
# before they are registered by the worker.
celery_app.autodiscover_tasks(["app"])
