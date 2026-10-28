import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class ImageUploadModel(UUIDPrimaryKey, Base):
    """Every image the backend signed, so none is ever left untracked in the storage."""

    __tablename__ = "image_uploads"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'attached', 'discarded')", name="status_valid"),
        # The cleanup job scans by status and age.
        Index("ix_image_uploads_status_created_at", "status", "created_at"),
    )

    # RESTRICT: deleting a tenant must first hand its images to the cleanup, never drop their records.
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), index=True)
    # Unique across tenants: it already contains the tenant folder (tenants/{tenant_id}/...).
    public_id: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Failed deletes so far, and when the cleanup may try again (doubling delay, see clean_up_images).
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
