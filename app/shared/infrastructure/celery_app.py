"""Celery application shared by the API (publishes tasks) and the worker (runs them).

RabbitMQ is the broker; results are not stored (tasks report through logs and the database).
Tasks run in the worker process, so their blocking or slow work never touches the API's event loop.
"""

from datetime import timedelta

from celery import Celery

from app.shared.infrastructure.config import Settings

CLEAN_UP_IMAGES_TASK = "media.clean_up_images"
PURGE_REFRESH_TOKENS_TASK = "auth.purge_refresh_tokens"


def create_celery(settings: Settings) -> Celery:
    app = Celery("menu", broker=settings.celery_broker_url)
    app.conf.update(
        task_ignore_result=True,
        # Fail fast when the broker is down instead of blocking a publisher for long.
        broker_connection_timeout=2,
        broker_connection_retry_on_startup=True,
        # A task is acknowledged after it finishes, so a crashed worker's task runs again; on a lost
        # broker connection the running task is cancelled and redelivered (the Celery 6 default).
        task_acks_late=True,
        worker_cancel_long_running_tasks_on_connection_loss=True,
        worker_prefetch_multiplier=1,
        # Remote control (celery inspect/control) uses transient non-exclusive queues, which
        # RabbitMQ 4 refuses ("transient_nonexcl_queues is deprecated"); the app does not use it.
        worker_enable_remote_control=False,
        timezone="UTC",
        beat_schedule={
            # Safety net: catches cleanups whose immediate request was lost.
            "clean-up-images": {
                "task": CLEAN_UP_IMAGES_TASK,
                "schedule": timedelta(seconds=settings.image_cleanup_interval_seconds),
            },
            # Expired refresh tokens are useless rows: drop them daily.
            "purge-refresh-tokens": {"task": PURGE_REFRESH_TOKENS_TASK, "schedule": timedelta(days=1)},
        },
    )
    return app
