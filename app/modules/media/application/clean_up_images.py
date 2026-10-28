"""Background cleanup of images nothing uses any more (runs in the Celery worker, never in a request)."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.modules.media.domain.uploads import CleanupRepository
from app.shared.domain.images import ImageStorage
from app.shared.domain.ports import Clock, UnitOfWork

logger = logging.getLogger(__name__)

_FIRST_RETRY = timedelta(minutes=2)
_MAX_RETRY = timedelta(hours=6)


def retry_delay(attempts: int) -> timedelta:
    """Wait before retrying an image whose delete failed `attempts` times: doubles, capped at six hours."""
    return min(_FIRST_RETRY * 2 ** (min(attempts, 20) - 1), _MAX_RETRY)


@dataclass(frozen=True)
class CleanupResult:
    deleted: int
    failed: int


class CleanUpImages:
    """Deletes discarded images and pending uploads older than `pending_ttl` from the storage.

    Each batch is claimed with row locks, so two workers never handle the same image. A failed
    delete keeps its record and is postponed with a growing delay, so an image that keeps failing
    never takes a place in every run and never blocks the others.
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
        now = self._clock.now()
        due = await self._uploads.claim_due(now, now - self._pending_ttl, self._batch_size)
        deleted = failed = 0
        for image in due:
            try:
                await self._storage.delete(image.public_id)
            except Exception:
                failed += 1
                attempts = image.attempts + 1
                await self._uploads.postpone(image.public_id, now + retry_delay(attempts))
                logger.warning(
                    "Could not delete image %s (attempt %s); retrying later", image.public_id, attempts, exc_info=True
                )
                continue
            await self._uploads.forget(image.public_id)
            deleted += 1
        # Releases the row locks; forgotten rows are gone, failed ones wait for their retry time.
        await self._uow.commit()
        return CleanupResult(deleted=deleted, failed=failed)
