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


class PublishedThemeCache(Protocol):
    """Port: cached copy of what the tables see. Best effort: it never raises."""

    async def invalidate(self, tenant_id: uuid.UUID) -> None: ...
