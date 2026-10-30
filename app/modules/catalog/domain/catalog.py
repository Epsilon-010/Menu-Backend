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
# The badges a product can show, in the order the menu shows them.
BADGES = ("new", "popular", "spicy", "vegan", "vegetarian", "gluten_free")
MAX_GROUPS_PER_ITEM = 10


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


def validate_badges(badges: Iterable[str]) -> tuple[str, ...]:
    """Each badge once, in the fixed order; anything outside the list is rejected."""
    chosen = set(badges)
    if not chosen <= set(BADGES):
        raise InvalidCatalogData(f"Badges must be some of: {', '.join(BADGES)}")
    return tuple(badge for badge in BADGES if badge in chosen)


def validate_group_ids(group_ids: Iterable[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    """The modifier groups of an item in its order; a repeated id keeps its first place."""
    unique = tuple(dict.fromkeys(group_ids))
    if len(unique) > MAX_GROUPS_PER_ITEM:
        raise InvalidCatalogData(f"An item can have at most {MAX_GROUPS_PER_ITEM} modifier groups")
    return unique


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
    def create(
        cls, tenant_id: uuid.UUID, name: str, position: int, category_id: uuid.UUID | None = None
    ) -> "Category":
        """`category_id` comes from the client to make the create idempotent; None generates one."""
        return cls(
            tenant_id=tenant_id,
            name=validate_category_name(name),
            position=position,
            id=category_id or uuid.uuid4(),
        )

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
    badges: tuple[str, ...] = ()
    # Modifier groups of the tenant's library, in the order the item shows them.
    modifier_group_ids: tuple[uuid.UUID, ...] = ()
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(
        cls,
        tenant_id: uuid.UUID,
        category_id: uuid.UUID,
        name: str,
        description: str,
        price_cents: int,
        position: int,
        item_id: uuid.UUID | None = None,
        badges: Iterable[str] = (),
        modifier_group_ids: Iterable[uuid.UUID] = (),
    ) -> "Item":
        """`item_id` comes from the client to make the create idempotent; None generates one."""
        return cls(
            tenant_id=tenant_id,
            category_id=category_id,
            name=validate_item_name(name),
            description=validate_description(description),
            price_cents=validate_price(price_cents),
            position=position,
            badges=validate_badges(badges),
            modifier_group_ids=validate_group_ids(modifier_group_ids),
            id=item_id or uuid.uuid4(),
        )

    def same_draft(
        self,
        category_id: uuid.UUID,
        name: str,
        description: str,
        price_cents: int,
        badges: Iterable[str] = (),
        modifier_group_ids: Iterable[uuid.UUID] = (),
    ) -> bool:
        """Whether a repeated create asks for exactly this item (after the same normalization)."""
        mine = (self.category_id, self.name, self.description, self.price_cents, self.badges, self.modifier_group_ids)
        return mine == (
            category_id,
            validate_item_name(name),
            validate_description(description),
            validate_price(price_cents),
            validate_badges(badges),
            validate_group_ids(modifier_group_ids),
        )

    def with_changes(
        self,
        name: str | None = None,
        description: str | None = None,
        price_cents: int | None = None,
        is_available: bool | None = None,
        badges: Iterable[str] | None = None,
        modifier_group_ids: Iterable[uuid.UUID] | None = None,
    ) -> "Item":
        return replace(
            self,
            name=self.name if name is None else validate_item_name(name),
            description=self.description if description is None else validate_description(description),
            price_cents=self.price_cents if price_cents is None else validate_price(price_cents),
            is_available=self.is_available if is_available is None else is_available,
            badges=self.badges if badges is None else validate_badges(badges),
            modifier_group_ids=(
                self.modifier_group_ids if modifier_group_ids is None else validate_group_ids(modifier_group_ids)
            ),
        )


class CategoryRepository(Protocol):
    async def add(self, category: Category) -> None: ...

    async def get(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None: ...

    async def get_for_update(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        """Same as `get`, locking the row until the transaction ends: for every read-then-write."""
        ...

    async def exists_anywhere(self, category_id: uuid.UUID) -> bool:
        """Whether the id is taken in any tenant (to answer a clash without revealing that row)."""
        ...

    async def lock_order(self, tenant_id: uuid.UUID) -> None:
        """Serializes changes to the tenant's category order until the transaction ends."""
        ...

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

    async def get_for_update(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None:
        """Same as `get`, locking the row until the transaction ends: for every read-then-write."""
        ...

    async def exists_anywhere(self, item_id: uuid.UUID) -> bool:
        """Whether the id is taken in any tenant (to answer a clash without revealing that row)."""
        ...

    async def lock_order(self, tenant_id: uuid.UUID, category_ids: list[uuid.UUID]) -> None:
        """Serializes changes to the item order of those categories until the transaction ends."""
        ...

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
