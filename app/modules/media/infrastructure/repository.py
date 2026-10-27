import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.domain.uploads import DueImage, UploadStatus
from app.modules.media.infrastructure.models import ImageUploadModel


class SqlAlchemyImageUploads:
    """Implements the shared `ImageRegistry` port (tenant-scoped) and the media `CleanupRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, tenant_id: uuid.UUID, public_id: str) -> None:
        self._session.add(ImageUploadModel(tenant_id=tenant_id, public_id=public_id, status=UploadStatus.PENDING))
        await self._session.flush()

    async def attach(self, tenant_id: uuid.UUID, public_id: str) -> bool:
        # Conditional on `pending`: two concurrent attaches of the same id cannot both win.
        result = await self._session.execute(
            update(ImageUploadModel)
            .where(
                ImageUploadModel.tenant_id == tenant_id,
                ImageUploadModel.public_id == public_id,
                ImageUploadModel.status == UploadStatus.PENDING,
            )
            .values(status=UploadStatus.ATTACHED)
        )
        return bool(getattr(result, "rowcount", 0))

    async def discard(self, tenant_id: uuid.UUID, public_id: str) -> None:
        await self._session.execute(
            update(ImageUploadModel)
            .where(
                ImageUploadModel.tenant_id == tenant_id,
                ImageUploadModel.public_id == public_id,
                ImageUploadModel.status != UploadStatus.DISCARDED,
            )
            .values(status=UploadStatus.DISCARDED, discarded_at=func.now())
        )

    async def reject(self, tenant_id: uuid.UUID, public_id: str) -> None:
        await self._session.execute(
            update(ImageUploadModel)
            .where(
                ImageUploadModel.tenant_id == tenant_id,
                ImageUploadModel.public_id == public_id,
                ImageUploadModel.status == UploadStatus.PENDING,
            )
            .values(status=UploadStatus.DISCARDED, discarded_at=func.now())
        )

    async def claim_due(self, now: datetime, pending_before: datetime, limit: int) -> list[DueImage]:
        # The only cross-tenant query of the module: the cleanup is a platform job.
        rows = await self._session.execute(
            select(ImageUploadModel.public_id, ImageUploadModel.attempts)
            .where(
                or_(
                    ImageUploadModel.status == UploadStatus.DISCARDED,
                    (ImageUploadModel.status == UploadStatus.PENDING) & (ImageUploadModel.created_at < pending_before),
                ),
                or_(ImageUploadModel.next_attempt_at.is_(None), ImageUploadModel.next_attempt_at <= now),
            )
            .order_by(func.coalesce(ImageUploadModel.next_attempt_at, ImageUploadModel.created_at))
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [DueImage(public_id=public_id, attempts=attempts) for public_id, attempts in rows]

    async def forget(self, public_id: str) -> None:
        await self._session.execute(delete(ImageUploadModel).where(ImageUploadModel.public_id == public_id))

    async def postpone(self, public_id: str, until: datetime) -> None:
        await self._session.execute(
            update(ImageUploadModel)
            .where(ImageUploadModel.public_id == public_id)
            .values(attempts=ImageUploadModel.attempts + 1, next_attempt_at=until)
        )