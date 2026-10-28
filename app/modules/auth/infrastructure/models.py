import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class RefreshTokenModel(UUIDPrimaryKey, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # A session belongs to exactly one staff member, table device or QR guest.
        CheckConstraint("num_nonnulls(user_id, table_id, guest_id) = 1", name="owner"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tables.id", ondelete="CASCADE"), index=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("table_guests.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    # SHA-256 hex digest of the opaque value; the plain token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Indexed for the periodic purge of expired tokens.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The owner's session version when issued; older than the owner's current one means rejected.
    session_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
