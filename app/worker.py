"""Celery worker entry point: `celery -A app.worker worker --beat`.

Tasks are plain Celery (sync) functions that run our async use cases with `asyncio.run`, in the
worker process with its own event loop and its own database engine.
"""

import asyncio
import logging
from datetime import timedelta

from app.modules.media.application.clean_up_images import CleanUpImages
from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.shared.domain.images import ImageStorage
from app.shared.infrastructure.celery_app import CLEAN_UP_IMAGES_TASK, create_celery
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, create_engine, create_session_factory
from app.shared.infrastructure.images import build_image_storage
from app.shared.infrastructure.security import SystemClock

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
# Upper bound per run, so one run never monopolizes the worker; the next run continues.
MAX_BATCHES = 20

celery_app = create_celery(get_settings())


async def clean_up_images_now(storage: ImageStorage | None = None) -> int:
    """Runs cleanup batches until nothing is due (or a batch fails). Returns how many images were deleted.

    `storage` defaults to the configured one; tests pass a fake so they never call Cloudinary.
    """
    settings = get_settings()
    engine = create_engine(settings.database_url)
    storage = storage or build_image_storage(settings)
    deleted = 0
    try:
        for _ in range(MAX_BATCHES):
            async with create_session_factory(engine)() as session:
                result = await CleanUpImages(
                    SqlAlchemyImageUploads(session),
                    storage,
                    SystemClock(),
                    SqlAlchemyUnitOfWork(session),
                    pending_ttl=timedelta(minutes=settings.image_pending_ttl_minutes),
                    batch_size=BATCH_SIZE,
                ).execute()
            deleted += result.deleted
            if result.failed or result.deleted < BATCH_SIZE:
                break
    finally:
        await engine.dispose()
    return deleted


@celery_app.task(name=CLEAN_UP_IMAGES_TASK)
def clean_up_images() -> int:
    deleted = asyncio.run(clean_up_images_now())
    logger.info("Image cleanup deleted %s images", deleted)
    return deleted
