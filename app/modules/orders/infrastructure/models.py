import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
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
    bill_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    # Chosen options of the catalog (no foreign key, like item_id: a removed one makes the line unavailable).
    modifier_option_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))


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
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'preparing', 'ready', 'delivered', 'cancelled')", name="status"
        ),
        # The kitchen and delivery queues look dishes up by status.
        Index("ix_order_items_tenant_id_status", "tenant_id", "status"),
    )

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
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When it entered the kitchen queue: the order's send time, or when staff added it later.
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    # Copy of the chosen options when ordered: [{"option_id", "group", "name", "price_cents"}].
    modifiers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))


class OrderItemChangeModel(UUIDPrimaryKey, Base):
    """Who moved a dish from one status to another, and when."""

    __tablename__ = "order_item_changes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("order_items.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12))
    # The staff member's user id; no foreign key, so the history outlives a removed account.
    changed_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(200))


class OrderSettingsModel(Base):
    __tablename__ = "order_settings"
    __table_args__ = (CheckConstraint("late_order_minutes BETWEEN 1 AND 240", name="late_order_minutes"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    late_order_minutes: Mapped[int] = mapped_column(Integer, server_default=text("15"))


class OrderCounterModel(Base):
    __tablename__ = "order_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)
