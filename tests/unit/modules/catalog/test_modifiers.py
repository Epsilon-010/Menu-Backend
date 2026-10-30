import uuid

import pytest

from app.modules.catalog.application.manage_categories import CreateCategory
from app.modules.catalog.application.manage_items import CreateItem, ItemChanges, ItemDraft, UpdateItem
from app.modules.catalog.application.manage_modifiers import (
    CreateModifierGroup,
    DeleteModifierGroup,
    ListModifierGroups,
    ModifierGroupChanges,
    ModifierGroupDraft,
    UpdateModifierGroup,
)
from app.modules.catalog.application.menu import GetMenu, GetOrderableItems
from app.modules.catalog.domain.catalog import MAX_PRICE_CENTS
from app.modules.catalog.domain.errors import CatalogIdTaken, InvalidCatalogData, ModifierGroupNotFound
from app.modules.catalog.domain.modifiers import ModifierGroup, OptionDraft
from tests.unit.fakes import (
    FakeUnitOfWork,
    InMemoryCategoryRepository,
    InMemoryItemRepository,
    InMemoryModifierGroupRepository,
)

pytestmark = pytest.mark.anyio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()

SIZES = [OptionDraft("Small", 0), OptionDraft("Large", 1500)]


def group(
    name: str = "Size", min_select: int = 1, max_select: int = 1, options: list[OptionDraft] | None = None
) -> ModifierGroup:
    return ModifierGroup.create(TENANT_A, name, min_select, max_select, SIZES if options is None else options)


# --- Domain -----------------------------------------------------------------------------------


def test_a_group_keeps_its_options_in_order() -> None:
    created = group(name="  Size ")

    assert created.name == "Size"
    assert [(o.name, o.price_cents, o.is_available) for o in created.options] == [
        ("Small", 0, True),
        ("Large", 1500, True),
    ]


@pytest.mark.parametrize(
    ("min_select", "max_select"),
    [(-1, 1), (2, 1), (0, 0), (1, 3)],  # negative, min over max, max zero, max over the 2 options
)
def test_selection_limits_must_fit_the_options(min_select: int, max_select: int) -> None:
    with pytest.raises(InvalidCatalogData, match="Invalid selection limits"):
        group(min_select=min_select, max_select=max_select)


def test_option_names_are_unique_in_a_group_ignoring_case() -> None:
    with pytest.raises(InvalidCatalogData, match="Option names must be unique in a group"):
        group(options=[OptionDraft("Cheese", 0), OptionDraft(" cheese", 500)], max_select=2)


@pytest.mark.parametrize("options", [[], [OptionDraft(f"Option {n}", 0) for n in range(31)]])
def test_a_group_has_1_to_30_options(options: list[OptionDraft]) -> None:
    with pytest.raises(InvalidCatalogData, match="1 to 30 options"):
        group(options=options, min_select=0)


@pytest.mark.parametrize("price", [-1, MAX_PRICE_CENTS + 1])
def test_option_prices_are_zero_or_more_cents(price: int) -> None:
    with pytest.raises(InvalidCatalogData, match="Price"):
        group(options=[OptionDraft("Large", price)])


def test_group_and_option_names_have_1_to_80_characters() -> None:
    with pytest.raises(InvalidCatalogData, match="Group name"):
        group(name=" ")
    with pytest.raises(InvalidCatalogData, match="Option name"):
        group(options=[OptionDraft("x" * 81, 0)])


def test_editing_the_options_keeps_the_ids_of_the_listed_ones() -> None:
    created = group()
    small, large = created.options

    edited = created.with_changes(
        options=[OptionDraft("Large", 2000, id=large.id), OptionDraft("Medium", 800)]
    )

    assert [o.name for o in edited.options] == ["Large", "Medium"]
    assert edited.options[0].id == large.id
    assert edited.options[1].id not in {small.id, large.id}


def test_an_option_id_of_another_group_is_unknown() -> None:
    with pytest.raises(InvalidCatalogData, match="Unknown option"):
        group().with_changes(options=[OptionDraft("Large", 0, id=uuid.uuid4())])


def test_a_required_group_needs_enough_available_options() -> None:
    sold_out = group(options=[OptionDraft("Small", 0, is_available=False), OptionDraft("Large", 0)])
    nothing_left = group(options=[OptionDraft("Small", 0, is_available=False)])
    optional = group(min_select=0, options=[OptionDraft("Small", 0, is_available=False)])

    assert sold_out.can_be_met()
    assert not nothing_left.can_be_met()
    assert optional.can_be_met()


# --- Use cases --------------------------------------------------------------------------------


class World:
    def __init__(self) -> None:
        self.categories = InMemoryCategoryRepository()
        self.items = InMemoryItemRepository(self.categories)
        self.groups = InMemoryModifierGroupRepository(self.items)
        self.uow = FakeUnitOfWork()

    def draft(self, name: str = "Size", **changes: object) -> ModifierGroupDraft:
        values: dict[str, object] = {"name": name, "min_select": 1, "max_select": 1, "options": tuple(SIZES)}
        values.update(changes)
        return ModifierGroupDraft(**values)  # type: ignore[arg-type]

    async def create(self, draft: ModifierGroupDraft | None = None, tenant_id: uuid.UUID = TENANT_A) -> ModifierGroup:
        return await CreateModifierGroup(self.groups, self.uow).execute(tenant_id, draft or self.draft())

    async def item(self, group_ids: tuple[uuid.UUID, ...] = (), tenant_id: uuid.UUID = TENANT_A) -> uuid.UUID:
        category = await CreateCategory(self.categories, self.uow).execute(tenant_id, f"Tacos {uuid.uuid4()}")
        draft = ItemDraft(
            category_id=category.id, name="Pastor", description="", price_cents=2500, modifier_group_ids=group_ids
        )
        return (await CreateItem(self.categories, self.items, self.groups, self.uow).execute(tenant_id, draft)).id

    def update_item(self) -> UpdateItem:
        return UpdateItem(self.categories, self.items, self.groups, self.uow)


@pytest.fixture
def world() -> World:
    return World()


async def test_admin_creates_and_lists_groups_by_name(world: World) -> None:
    await world.create(world.draft("Size"))
    await world.create(world.draft("extras", min_select=0, max_select=2))

    listed = await ListModifierGroups(world.groups).execute(TENANT_A)

    assert [g.name for g in listed] == ["extras", "Size"]
    assert world.uow.commits == 2


async def test_repeating_a_create_returns_the_same_group(world: World) -> None:
    group_id = uuid.uuid4()
    first = await world.create(world.draft(id=group_id))

    again = await world.create(world.draft(id=group_id))

    assert again == first
    assert len(await ListModifierGroups(world.groups).execute(TENANT_A)) == 1


async def test_a_create_id_with_other_data_or_of_another_tenant_is_taken(world: World) -> None:
    group_id = uuid.uuid4()
    await world.create(world.draft(id=group_id))

    with pytest.raises(CatalogIdTaken):
        await world.create(world.draft("Salsas", id=group_id))
    with pytest.raises(CatalogIdTaken):
        await world.create(world.draft(id=group_id), tenant_id=TENANT_B)


async def test_updating_a_group_replaces_its_options_and_limits(world: World) -> None:
    created = await world.create()
    large = created.options[1]

    updated = await UpdateModifierGroup(world.groups, world.uow).execute(
        TENANT_A,
        created.id,
        ModifierGroupChanges(name="Sizes", min_select=0, options=(OptionDraft("Large", 2000, False, id=large.id),)),
    )

    assert (updated.name, updated.min_select, updated.max_select) == ("Sizes", 0, 1)
    assert [(o.id, o.price_cents, o.is_available) for o in updated.options] == [(large.id, 2000, False)]
    assert world.groups.locked == [created.id]
    assert await world.groups.get(TENANT_A, created.id) == updated


async def test_another_tenant_cannot_see_edit_or_delete_a_group(world: World) -> None:
    created = await world.create()

    assert await ListModifierGroups(world.groups).execute(TENANT_B) == []
    with pytest.raises(ModifierGroupNotFound):
        await UpdateModifierGroup(world.groups, world.uow).execute(TENANT_B, created.id, ModifierGroupChanges(name="x"))
    with pytest.raises(ModifierGroupNotFound):
        await DeleteModifierGroup(world.groups, world.uow).execute(TENANT_B, created.id)
    assert await world.groups.get(TENANT_A, created.id) == created


async def test_items_keep_their_groups_in_order_without_repeats(world: World) -> None:
    size = await world.create()
    extras = await world.create(world.draft("Extras", min_select=0))

    item_id = await world.item((extras.id, size.id, extras.id))

    stored = await world.items.get(TENANT_A, item_id)
    assert stored is not None and stored.modifier_group_ids == (extras.id, size.id)


async def test_an_item_cannot_use_a_missing_or_foreign_group(world: World) -> None:
    foreign = await world.create(tenant_id=TENANT_B)

    with pytest.raises(InvalidCatalogData, match="Unknown modifier group"):
        await world.item((foreign.id,))
    with pytest.raises(InvalidCatalogData, match="Unknown modifier group"):
        await world.item((uuid.uuid4(),))


async def test_an_item_has_at_most_10_groups(world: World) -> None:
    groups = [await world.create(world.draft(f"Group {n}")) for n in range(11)]

    with pytest.raises(InvalidCatalogData, match="at most 10"):
        await world.item(tuple(g.id for g in groups))


async def test_updating_an_item_changes_its_groups_only_when_asked(world: World) -> None:
    size = await world.create()
    item_id = await world.item((size.id,))

    renamed = await world.update_item().execute(TENANT_A, item_id, ItemChanges(name="Suadero"))
    cleared = await world.update_item().execute(TENANT_A, item_id, ItemChanges(modifier_group_ids=()))

    assert renamed.modifier_group_ids == (size.id,)
    assert cleared.modifier_group_ids == ()


async def test_deleting_a_group_detaches_it_from_every_item(world: World) -> None:
    size = await world.create()
    item_id = await world.item((size.id,))

    await DeleteModifierGroup(world.groups, world.uow).execute(TENANT_A, size.id)

    stored = await world.items.get(TENANT_A, item_id)
    assert stored is not None and stored.modifier_group_ids == ()
    assert await world.groups.get(TENANT_A, size.id) is None


async def test_the_menu_lists_each_item_with_its_groups(world: World) -> None:
    size = await world.create(world.draft(options=(OptionDraft("Small", 0, False), OptionDraft("Large", 1500))))
    extras = await world.create(world.draft("Extras", min_select=0))
    item_id = await world.item((extras.id, size.id))

    menu = await GetMenu(world.categories, world.items, world.groups).execute(TENANT_A)

    entry = menu[0].items[0]
    assert entry.item.id == item_id
    assert [g.name for g in entry.modifier_groups] == ["Extras", "Size"]
    # Sold-out options stay listed so tables can show them as sold out.
    assert [o.is_available for o in entry.modifier_groups[1].options] == [False, True]


async def test_an_item_whose_required_group_cannot_be_met_is_not_orderable(world: World) -> None:
    size = await world.create(world.draft(options=(OptionDraft("Small", 0, False),)))
    blocked = await world.item((size.id,))
    plain = await world.item()

    orderable = await GetOrderableItems(world.categories, world.items, world.groups).execute(TENANT_A, {blocked, plain})

    assert set(orderable) == {plain}
    assert orderable[plain].modifier_groups == ()
