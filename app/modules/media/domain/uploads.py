from datetime import datetime
from enum import StrEnum
from typing import Protocol


class UploadStatus(StrEnum):
    """Life of a signed image: `pending` until attached, `discarded` once nothing uses it."""

    PENDING = "pending"
    ATTACHED = "attached"
    DISCARDED = "discarded"


class CleanupRepository(Protocol):
    """Port of the cleanup job. Unlike every business query it spans all tenants: it is a platform job."""

    async def claim_due(self, pending_before: datetime, limit: int) -> list[str]:
        """Locks and returns up to `limit` public ids to delete: discarded ones and pending ones
        created before `pending_before`. Rows locked by another worker are skipped."""
        ...

    async def forget(self, public_id: str) -> None:
        """Removes the record once the image is gone from the storage."""
        ...
