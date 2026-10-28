import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class BillModel(UUIDPrimaryKey, Base):
    __tablename__ = "bills"
    __table_args__ = (
        # At most one open bill per table: the database is the guarantee, the table lock the fast path.
        Index("uq_bills_open_table_id", "table_id", unique=True, postgresql_where=text("closed_at IS NULL")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tables.id", ondelete="RESTRICT"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_method: Mapped[str | None] = mapped_column(String(10))
    paid_cents: Mapped[int | None] = mapped_column(Integer)


class GuestModel(UUIDPrimaryKey, Base):
    __tablename__ = "table_guests"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tables.id", ondelete="RESTRICT"), index=True)
    bill_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bills.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(30))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CartModel(UUIDPrimaryKey, Base):
    __tablename__ = "carts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    # One cart per table, shared by its tablet and every guest.
    table_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tables.id", ondelete="CASCADE"), unique=True)
    version: Mapped[int] = mapped_column(Integer)


class CartLineModel(UUIDPrimaryKey, Base):
    __tablename__ = "cart_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tables.id", ondelete="CASCADE"), index=True)
    # No foreign key: a line whose item left the catalog stays visible as unavailable.
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    item_name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200))
    added_by: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderModel(UUIDPrimaryKey, Base):
    __tablename__ = "orders"
    __table_args__ = (Index("uq_orders_tenant_id_number", "tenant_id", "number", unique=True),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tables.id", ondelete="RESTRICT"), index=True)
    bill_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bills.id", ondelete="RESTRICT"), index=True)
    # Per-tenant display number, not the id.
    number: Mapped[int] = mapped_column(Integer)
    sent_by: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderItemModel(UUIDPrimaryKey, Base):
    __tablename__ = "order_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(120))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200))
    added_by: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12))
    position: Mapped[int] = mapped_column(Integer)


class OrderCounterModel(Base):
    __tablename__ = "order_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)
