"""Entry points other modules use to reach media: the image registry and the cleanup scheduler.

Other modules must not build this module's repositories themselves; they call these factories
(same convention as `auth/infrastructure/session_revocation.py`).
"""

import asyncio
import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.shared.domain.images import ImageCleanupScheduler, ImageRegistry
from app.shared.infrastructure.celery_app import CLEAN_UP_IMAGES_TASK

logger = logging.getLogger(__name__)

# Seconds the request may wait for the broker before giving up (the periodic run is the safety net).
_ENQUEUE_TIMEOUT_SECONDS = 3


def image_registry(session: AsyncSession) -> ImageRegistry:
    """The registry on the caller's session, so it shares the caller's transaction."""
    return SqlAlchemyImageUploads(session)


class CeleryImageCleanupScheduler:
    """Publishes the cleanup task to RabbitMQ without blocking the event loop.

    Celery's publish is a blocking network call (and retries while the broker is down), so it runs
    in a worker thread, without retries, under a timeout. Failures are logged and swallowed: the
    images are already marked in Postgres and Celery beat cleans them up on its next run.
    """

    def __init__(self, celery_app: object) -> None:
        self._celery = celery_app

    async def request_cleanup(self) -> None:
        try:
            await asyncio.wait_for(asyncio.to_thread(self._publish), timeout=_ENQUEUE_TIMEOUT_SECONDS)
        except Exception:
            logger.warning("Could not enqueue the image cleanup; the periodic run will do it", exc_info=True)

    def _publish(self) -> None:
        self._celery.send_task(CLEAN_UP_IMAGES_TASK, retry=False)  # type: ignore[attr-defined]


def image_cleanup_scheduler(request: Request) -> ImageCleanupScheduler:
    scheduler: ImageCleanupScheduler = request.app.state.image_cleanup
    return scheduler
