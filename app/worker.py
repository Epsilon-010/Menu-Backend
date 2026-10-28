"""Celery worker entry point: `celery -A app.worker worker --beat`.

Tasks are plain Celery (sync) functions that run our async use cases with `asyncio.run`, in the
worker process with its own event loop and its own database engine.
"""

import asyncio
import logging
from datetime import timedelta

from app.modules.auth.application.purge_refresh_tokens import BATCH_SIZE as PURGE_BATCH_SIZE
from app.modules.auth.application.purge_refresh_tokens import PurgeExpiredRefreshTokens
from app.modules.auth.infrastructure.refresh_tokens import SqlAlchemyRefreshTokenRepository
from app.modules.media.application.clean_up_images import CleanUpImages
from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.shared.domain.images import ImageStorage
from app.shared.infrastructure.celery_app import CLEAN_UP_IMAGES_TASK, PURGE_REFRESH_TOKENS_TASK, create_celery
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
    """Runs cleanup batches until nothing is due (at most MAX_BATCHES). Returns how many images were deleted.

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
            # Circuit breaker: a batch where nothing could be deleted means the storage is down; stop
            # instead of hammering it (failed images are already postponed and the next run retries).
            if result.failed and not result.deleted:
                break
            # Failed images are postponed, so a full batch with some failures still means more may be due.
            if result.deleted + result.failed < BATCH_SIZE:
                break
    finally:
        await engine.dispose()
    return deleted


async def purge_refresh_tokens_now() -> int:
    """Deletes refresh tokens expired for more than a day, in batches. Returns how many."""
    engine = create_engine(get_settings().database_url)
    purged = 0
    try:
        for _ in range(MAX_BATCHES):
            async with create_session_factory(engine)() as session:
                batch = await PurgeExpiredRefreshTokens(
                    SqlAlchemyRefreshTokenRepository(session),
                    SystemClock(),
                    SqlAlchemyUnitOfWork(session),
                    grace=timedelta(days=1),
                ).execute()
            purged += batch
            if batch < PURGE_BATCH_SIZE:
                break
    finally:
        await engine.dispose()
    return purged


@celery_app.task(name=PURGE_REFRESH_TOKENS_TASK)
def purge_refresh_tokens() -> int:
    purged = asyncio.run(purge_refresh_tokens_now())
    logger.info("Refresh token purge deleted %s tokens", purged)
    return purged


@celery_app.task(name=CLEAN_UP_IMAGES_TASK)
def clean_up_images() -> int:
    deleted = asyncio.run(clean_up_images_now())
    logger.info("Image cleanup deleted %s images", deleted)
    return deleted
