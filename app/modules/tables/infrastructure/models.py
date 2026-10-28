import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class TableModel(UUIDPrimaryKey, Base):
    __tablename__ = "tables"
    __table_args__ = (
        # Names are unique inside a tenant, ignoring case.
        Index("uq_tables_tenant_id_lower_name", "tenant_id", text("lower(name)"), unique=True),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    # Unique across tenants: the device login receives only the code, the tenant comes from the table.
    code: Mapped[str] = mapped_column(String(6), unique=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    # Goes up on every change that must sign the account out; see the entity.
    session_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # Random part of the table's QR link, unique across tenants like the code; see the entity.
    qr_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
