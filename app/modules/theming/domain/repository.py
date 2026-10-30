import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.theming.domain.theme import Theme


@dataclass(frozen=True)
class ThemeRecord:
    """A tenant's theme: the draft the admin edits and the version the tables see (None: never published)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    draft: Theme
    published: Theme | None
    published_at: datetime | None


class ThemeRepository(Protocol):
    async def get(self, tenant_id: uuid.UUID) -> ThemeRecord | None: ...

    async def lock(self, tenant_id: uuid.UUID, initial: Theme) -> ThemeRecord:
        """The tenant's record locked for update (`SELECT ... FOR UPDATE`), created with `initial` as draft
        when it does not exist yet; two first saves at once never create two records."""
        ...

    async def update(self, record: ThemeRecord) -> None: ...


# Published versions each tenant keeps to restore; publishing one more forgets the oldest.
HISTORY_LIMIT = 20


@dataclass(frozen=True)
class ThemeVersion:
    """A theme as it was published. `number` counts the tenant's publishes (1, 2, 3...) and orders the history."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    number: int
    theme: Theme
    published_at: datetime


class ThemeHistory(Protocol):
    """Changed only while the tenant's theme record is locked (`ThemeRepository.lock`), one publish at a time."""

    async def list(self, tenant_id: uuid.UUID) -> list[ThemeVersion]:
        """Newest first."""
        ...

    async def add(self, version: ThemeVersion) -> None: ...

    async def remove(self, tenant_id: uuid.UUID, ids: set[uuid.UUID]) -> None: ...


class PublishedThemeCache(Protocol):
    """Port: cached copy of what the tables see. Best effort: it never raises."""

    async def invalidate(self, tenant_id: uuid.UUID) -> None: ...
