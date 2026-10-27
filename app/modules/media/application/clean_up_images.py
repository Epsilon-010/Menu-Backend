"""Background cleanup of images nothing uses any more (runs in the Celery worker, never in a request)."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.modules.media.domain.uploads import CleanupRepository
from app.shared.domain.images import ImageStorage
from app.shared.domain.ports import Clock, UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupResult:
    deleted: int
    failed: int


class CleanUpImages:
    """Deletes discarded images and pending uploads older than `pending_ttl` from the storage.

    Each batch is claimed with row locks, so two workers never handle the same image. A failed
    delete keeps its record: the next run tries again.
    """

    def __init__(
        self,
        uploads: CleanupRepository,
        storage: ImageStorage,
        clock: Clock,
        uow: UnitOfWork,
        pending_ttl: timedelta,
        batch_size: int = 50,
    ) -> None:
        self._uploads = uploads
        self._storage = storage
        self._clock = clock
        self._uow = uow
        self._pending_ttl = pending_ttl
        self._batch_size = batch_size

    async def execute(self) -> CleanupResult:
        due = await self._uploads.claim_due(self._clock.now() - self._pending_ttl, self._batch_size)
        deleted = failed = 0
        for public_id in due:
            try:
                await self._storage.delete(public_id)
            except Exception:
                failed += 1
                logger.warning("Could not delete image %s; it will be retried", public_id, exc_info=True)
                continue
            await self._uploads.forget(public_id)
            deleted += 1
        # Releases the row locks; forgotten rows are gone, failed ones stay for the next run.
        await self._uow.commit()
        return CleanupResult(deleted=deleted, failed=failed)
