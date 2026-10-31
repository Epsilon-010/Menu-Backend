from datetime import datetime

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.tenants.domain.tenant import DEFAULT_TIMEZONE, MAX_TIMEZONE_LENGTH
from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class TenantModel(UUIDPrimaryKey, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # IANA name; the statistics cut days in this zone.
    timezone: Mapped[str] = mapped_column(String(MAX_TIMEZONE_LENGTH), server_default=text(f"'{DEFAULT_TIMEZONE}'"))
