import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.database import Base, UUIDPrimaryKey


class CategoryModel(UUIDPrimaryKey, Base):
    __tablename__ = "categories"
    __table_args__ = (
        # Names are unique inside a tenant, ignoring case.
        Index("uq_categories_tenant_id_lower_name", "tenant_id", text("lower(name)"), unique=True),
        # Target of the items' composite foreign key: an item and its category share the tenant.
        UniqueConstraint("id", "tenant_id", name="uq_categories_id_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    is_visible: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItemModel(UUIDPrimaryKey, Base):
    __tablename__ = "items"
    __table_args__ = (
        # NO ACTION: a category with items cannot be deleted, even by two concurrent requests. Not
        # RESTRICT, which is checked before the tenant's cascade has removed the items.
        ForeignKeyConstraint(
            ["category_id", "tenant_id"],
            ["categories.id", "categories.tenant_id"],
            name="fk_items_category_id_tenant_id_categories",
        ),
        Index("ix_items_category_id_tenant_id", "category_id", "tenant_id"),
        CheckConstraint("price_cents >= 0", name="price_cents_not_negative"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), server_default="")
    # Integer cents, never float.
    price_cents: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=true())
    # Storage public id (tenants/{tenant_id}/items/...), never a URL.
    image_public_id: Mapped[str | None] = mapped_column(String(255))
    # Badge ids from the domain's fixed list, in its order (validated there).
    badges: Mapped[list[str]] = mapped_column(ARRAY(String(20)), server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModifierGroupModel(UUIDPrimaryKey, Base):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        # Target of the composite foreign keys below: options and item links share the group's tenant.
        UniqueConstraint("id", "tenant_id", name="uq_modifier_groups_id_tenant_id"),
        CheckConstraint("0 <= min_select AND min_select <= max_select AND max_select >= 1", name="selection_limits"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    min_select: Mapped[int] = mapped_column(Integer)
    max_select: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModifierOptionModel(UUIDPrimaryKey, Base):
    __tablename__ = "modifier_options"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "tenant_id"],
            ["modifier_groups.id", "modifier_groups.tenant_id"],
            ondelete="CASCADE",
            name="fk_modifier_options_group_id_tenant_id_modifier_groups",
        ),
        Index("ix_modifier_options_group_id_tenant_id", "group_id", "tenant_id"),
        CheckConstraint("price_cents >= 0", name="price_cents_not_negative"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(80))
    # Integer cents added to the item's price, never float.
    price_cents: Mapped[int] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=true())
    position: Mapped[int] = mapped_column(Integer)


class ItemModifierGroupModel(UUIDPrimaryKey, Base):
    """Which groups of the library an item uses, in its order; deleting either side removes the link."""

    __tablename__ = "item_modifier_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "tenant_id"],
            ["modifier_groups.id", "modifier_groups.tenant_id"],
            ondelete="CASCADE",
            name="fk_item_modifier_groups_group_id_tenant_id_modifier_groups",
        ),
        UniqueConstraint("item_id", "group_id", name="uq_item_modifier_groups_item_id_group_id"),
        Index("ix_item_modifier_groups_group_id_tenant_id", "group_id", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id", ondelete="CASCADE"))
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
