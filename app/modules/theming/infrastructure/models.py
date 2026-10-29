import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class ThemeModel(UUIDPrimaryKey, Base):
    """One per tenant: the draft the admin edits and the published document the tables see (JSON, validated
    by the domain before it is written)."""

    __tablename__ = "themes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
