import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.modules.catalog.domain.errors import InvalidCatalogData

MAX_CATEGORY_NAME_LENGTH = 60
MAX_ITEM_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
# Prices are integer cents (never float): 0 to 100,000.00.
MAX_PRICE_CENTS = 10_000_000


def validate_category_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_CATEGORY_NAME_LENGTH:
        raise InvalidCatalogData(f"Category name must have 1 to {MAX_CATEGORY_NAME_LENGTH} characters")
    return name


def validate_item_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_ITEM_NAME_LENGTH:
        raise InvalidCatalogData(f"Item name must have 1 to {MAX_ITEM_NAME_LENGTH} characters")
    return name


def validate_description(description: str) -> str:
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise InvalidCatalogData(f"Description must have at most {MAX_DESCRIPTION_LENGTH} characters")
    return description


def validate_price(price_cents: int) -> int:
    if isinstance(price_cents, bool) or not isinstance(price_cents, int) or not 0 <= price_cents <= MAX_PRICE_CENTS:
        raise InvalidCatalogData(f"Price must be a whole number of cents from 0 to {MAX_PRICE_CENTS}")
    return price_cents


def ensure_complete_order(current_ids: Iterable[uuid.UUID], requested_ids: list[uuid.UUID]) -> None:
    """A reorder lists every current id exactly once, so nothing is lost or duplicated."""
    if len(requested_ids) != len(set(requested_ids)) or set(requested_ids) != set(current_ids):
        raise InvalidCatalogData("The order must list every element exactly once")


@dataclass(frozen=True)
class Category:
    """A section of the tenant's menu. Hidden categories stay in the admin panel only."""

    tenant_id: uuid.UUID
    name: str
    position: int
    is_visible: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(cls, tenant_id: uuid.UUID, name: str, position: int) -> "Category":
        return cls(tenant_id=tenant_id, name=validate_category_name(name), position=position)

    def with_changes(self, name: str | None = None, is_visible: bool | None = None) -> "Category":
        return replace(
            self,
            name=self.name if name is None else validate_category_name(name),
            is_visible=self.is_visible if is_visible is None else is_visible,
        )


@dataclass(frozen=True)
class Item:
    """A product of the menu, inside one category of the same tenant.

    The image is a storage public id (never a URL); unavailable items are hidden from the tables.
    """

    tenant_id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str
    price_cents: int
    position: int
    is_available: bool = True
    image_public_id: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(
        cls, tenant_id: uuid.UUID, category_id: uuid.UUID, name: str, description: str, price_cents: int, position: int
    ) -> "Item":
        return cls(
            tenant_id=tenant_id,
            category_id=category_id,
            name=validate_item_name(name),
            description=validate_description(description),
            price_cents=validate_price(price_cents),
            position=position,
        )

    def with_changes(
        self,
        name: str | None = None,
        description: str | None = None,
        price_cents: int | None = None,
        is_available: bool | None = None,
    ) -> "Item":
        return replace(
            self,
            name=self.name if name is None else validate_item_name(name),
            description=self.description if description is None else validate_description(description),
            price_cents=self.price_cents if price_cents is None else validate_price(price_cents),
            is_available=self.is_available if is_available is None else is_available,
        )


class CategoryRepository(Protocol):
    async def add(self, category: Category) -> None: ...

    async def get(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None: ...

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Category | None:
        """Case-insensitive match inside the tenant."""
        ...

    async def next_position(self, tenant_id: uuid.UUID) -> int: ...

    async def update(self, category: Category) -> None: ...

    async def delete(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> None:
        """Raises CategoryNotEmpty if the category still has items."""
        ...

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None: ...

    # Last on purpose: a method named `list` shadows the builtin in the annotations below it.
    async def list(self, tenant_id: uuid.UUID) -> list[Category]:
        """Categories of the tenant in menu order."""
        ...


class ItemRepository(Protocol):
    async def add(self, item: Item) -> None: ...

    async def get(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None: ...

    async def list_in_category(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> list[Item]: ...

    async def next_position(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> int: ...

    async def update(self, item: Item) -> None:
        """Raises CategoryNotFound if the category disappeared meanwhile (add raises it too)."""
        ...

    async def delete(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None: ...

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None: ...

    async def list(self, tenant_id: uuid.UUID) -> list[Item]:
        """Items of the tenant in menu order inside each category."""
        ...
