from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class UploadStatus(StrEnum):
    """Life of a signed image: `pending` until attached, `discarded` once nothing uses it."""

    PENDING = "pending"
    ATTACHED = "attached"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class DueImage:
    public_id: str
    # Failed delete attempts so far: the next retry waits longer each time.
    attempts: int


class CleanupRepository(Protocol):
    """Port of the cleanup job. Unlike every business query it spans all tenants: it is a platform job."""

    async def claim_due(self, now: datetime, pending_before: datetime, limit: int) -> list[DueImage]:
        """Locks and returns up to `limit` images to delete: discarded ones and pending ones created
        before `pending_before`, skipping those postponed past `now` and rows locked by another worker."""
        ...

    async def forget(self, public_id: str) -> None:
        """Removes the record once the image is gone from the storage."""
        ...

    async def postpone(self, public_id: str, until: datetime) -> None:
        """Counts a failed delete and leaves the image alone until `until`."""
        ...
