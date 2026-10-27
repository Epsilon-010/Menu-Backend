import uuid

import pytest

from app.modules.catalog.application.item_images import RemoveItemImage, RequestImageUpload, SetItemImage
from app.modules.catalog.application.manage_categories import (
    CreateCategory,
    DeleteCategory,
    ListCatalog,
    ReorderCategories,
    UpdateCategory,
)
from app.modules.catalog.application.manage_items import (
    CreateItem,
    DeleteItem,
    ItemChanges,
    ItemDraft,
    ReorderItems,
    UpdateItem,
)
from app.modules.catalog.domain.catalog import Category, Item
from app.modules.catalog.domain.errors import (
    CategoryNameNotAvailable,
    CategoryNotEmpty,
    CategoryNotFound,
    InvalidCatalogData,
    ItemNotFound,
)
from app.shared.domain.images import MAX_IMAGE_BYTES, ImageStorageUnavailable, InvalidImage
from tests.unit.fakes import FakeImageStorage, FakeUnitOfWork, InMemoryCategoryRepository, InMemoryItemRepository

pytestmark = pytest.mark.anyio

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


class World:
    def __init__(self) -> None:
        self.categories = InMemoryCategoryRepository()
        self.items = InMemoryItemRepository(self.categories)
        self.images = FakeImageStorage()
        self.uow = FakeUnitOfWork()

    async def category(self, name: str = "Tacos", tenant_id: uuid.UUID = TENANT_A) -> Category:
        return await CreateCategory(self.categories, self.uow).execute(tenant_id, name)

    async def item(
        self, category: Category, name: str = "Pastor", price_cents: int = 2500, tenant_id: uuid.UUID = TENANT_A
    ) -> Item:
        draft = ItemDraft(category_id=category.id, name=name, description="", price_cents=price_cents)
        return await CreateItem(self.categories, self.items, self.uow).execute(tenant_id, draft)

    def update_item(self) -> UpdateItem:
        return UpdateItem(self.categories, self.items, self.uow)

    def set_image(self) -> SetItemImage:
        return SetItemImage(self.items, self.images, self.uow)

    async def uploaded_image(self, tenant_id: uuid.UUID = TENANT_A, image_format: str = "jpg", size: int = 1_000) -> str:
        public_id = (await RequestImageUpload(self.images).execute(tenant_id)).public_id
        self.images.upload(public_id, image_format, size)
        return public_id


@pytest.fixture
def world() -> World:
    return World()


# --- Categories --------------------------------------------------------------------------------


async def test_new_categories_are_trimmed_visible_and_go_last(world: World) -> None:
    first = await world.category(" Tacos ")
    second = await world.category("Bebidas")

    assert (first.name, first.position, first.is_visible, first.tenant_id) == ("Tacos", 0, True, TENANT_A)
    assert second.position == 1
    assert world.uow.commits == 2


async def test_category_names_are_unique_per_tenant_ignoring_case(world: World) -> None:
    await world.category("Tacos")

    with pytest.raises(CategoryNameNotAvailable):
        await world.category(" TACOS")
    other = await world.category("Tacos", TENANT_B)

    assert other.position == 0


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
async def test_rejects_invalid_category_names(world: World, name: str) -> None:
    with pytest.raises(InvalidCatalogData):
        await world.category(name)

    assert world.categories.categories == {}


async def test_renames_and_hides_a_category(world: World) -> None:
    category = await world.category("Tacos")
    await world.category("Bebidas")
    use_case = UpdateCategory(world.categories, world.uow)

    with pytest.raises(CategoryNameNotAvailable):
        await use_case.execute(TENANT_A, category.id, name="bebidas")
    updated = await use_case.execute(TENANT_A, category.id, name="TACOS", is_visible=False)

    assert (updated.name, updated.is_visible) == ("TACOS", False)
    assert world.categories.categories[category.id] == updated


async def test_reorders_categories_with_the_full_list(world: World) -> None:
    tacos = await world.category("Tacos")
    drinks = await world.category("Bebidas")
    desserts = await world.category("Postres")

    await ReorderCategories(world.categories, world.uow).execute(TENANT_A, [desserts.id, tacos.id, drinks.id])

    listed = await ListCatalog(world.categories, world.items).execute(TENANT_A)
    assert [entry.category.name for entry in listed] == ["Postres", "Tacos", "Bebidas"]


@pytest.mark.parametrize("case", ["missing", "duplicated", "foreign"])
async def test_a_partial_or_foreign_category_order_is_rejected(world: World, case: str) -> None:
    tacos = await world.category("Tacos")
    drinks = await world.category("Bebidas")
    foreign = await world.category("Otra", TENANT_B)
    commits = world.uow.commits
    order = {
        "missing": [drinks.id],
        "duplicated": [drinks.id, tacos.id, tacos.id],
        "foreign": [drinks.id, tacos.id, foreign.id],
    }[case]

    with pytest.raises(InvalidCatalogData):
        await ReorderCategories(world.categories, world.uow).execute(TENANT_A, order)

    assert [c.name for c in await world.categories.list(TENANT_A)] == ["Tacos", "Bebidas"]
    assert world.uow.commits == commits


async def test_only_empty_categories_can_be_deleted(world: World) -> None:
    tacos = await world.category("Tacos")
    drinks = await world.category("Bebidas")
    await world.item(tacos)
    use_case = DeleteCategory(world.categories, world.uow)

    with pytest.raises(CategoryNotEmpty):
        await use_case.execute(TENANT_A, tacos.id)
    await use_case.execute(TENANT_A, drinks.id)

    assert list(world.categories.categories) == [tacos.id]


async def test_lists_the_tenant_catalog_with_items_in_order(world: World) -> None:
    tacos = await world.category("Tacos")
    drinks = await world.category("Bebidas")
    await world.item(tacos, "Pastor")
    await world.item(tacos, "Suadero")
    await world.item(drinks, "Horchata")
    await world.category("Ajena", TENANT_B)

    listed = await ListCatalog(world.categories, world.items).execute(TENANT_A)

    assert [(e.category.name, [i.name for i in e.items]) for e in listed] == [
        ("Tacos", ["Pastor", "Suadero"]),
        ("Bebidas", ["Horchata"]),
    ]


async def test_another_tenant_category_is_not_found(world: World) -> None:
    foreign = await world.category("Tacos", TENANT_B)

    with pytest.raises(CategoryNotFound):
        await UpdateCategory(world.categories, world.uow).execute(TENANT_A, foreign.id, is_visible=False)
    with pytest.raises(CategoryNotFound):
        await DeleteCategory(world.categories, world.uow).execute(TENANT_A, foreign.id)
    with pytest.raises(CategoryNotFound):
        await world.item(foreign)

    assert world.categories.categories[foreign.id] == foreign


# --- Items -------------------------------------------------------------------------------------


async def test_creates_an_available_item_last_in_its_category(world: World) -> None:
    tacos = await world.category()
    draft = ItemDraft(category_id=tacos.id, name=" Pastor ", description=" Con piña ", price_cents=2500)

    first = await CreateItem(world.categories, world.items, world.uow).execute(TENANT_A, draft)
    second = await world.item(tacos, "Suadero")

    assert (first.name, first.description, first.price_cents) == ("Pastor", "Con piña", 2500)
    assert (first.is_available, first.image_public_id, first.position) == (True, None, 0)
    assert second.position == 1


@pytest.mark.parametrize(
    ("name", "description", "price_cents"),
    [("", "", 100), ("x" * 81, "", 100), ("Ok", "x" * 501, 100), ("Ok", "", -1), ("Ok", "", 10_000_001)],
)
async def test_rejects_invalid_items(world: World, name: str, description: str, price_cents: int) -> None:
    tacos = await world.category()
    draft = ItemDraft(category_id=tacos.id, name=name, description=description, price_cents=price_cents)

    with pytest.raises(InvalidCatalogData):
        await CreateItem(world.categories, world.items, world.uow).execute(TENANT_A, draft)

    assert world.items.items == {}


async def test_edits_hides_and_moves_an_item_to_the_end_of_another_category(world: World) -> None:
    tacos = await world.category("Tacos")
    specials = await world.category("Especiales")
    await world.item(specials, "Campechano")
    item = await world.item(tacos)

    updated = await world.update_item().execute(
        TENANT_A,
        item.id,
        ItemChanges(name="Pastor XL", description="Grande", price_cents=3200, is_available=False, category_id=specials.id),
    )

    assert (updated.name, updated.description, updated.price_cents) == ("Pastor XL", "Grande", 3200)
    assert (updated.is_available, updated.category_id, updated.position) == (False, specials.id, 1)
    assert world.items.items[item.id] == updated


async def test_an_item_cannot_move_to_another_tenant_category(world: World) -> None:
    item = await world.item(await world.category())
    foreign = await world.category("Ajena", TENANT_B)

    with pytest.raises(CategoryNotFound):
        await world.update_item().execute(TENANT_A, item.id, ItemChanges(category_id=foreign.id))

    assert world.items.items[item.id] == item


async def test_reorders_the_items_of_one_category(world: World) -> None:
    tacos = await world.category()
    pastor = await world.item(tacos, "Pastor")
    suadero = await world.item(tacos, "Suadero")
    use_case = ReorderItems(world.categories, world.items, world.uow)

    with pytest.raises(InvalidCatalogData):
        await use_case.execute(TENANT_A, tacos.id, [suadero.id])
    await use_case.execute(TENANT_A, tacos.id, [suadero.id, pastor.id])

    assert [i.name for i in await world.items.list_in_category(TENANT_A, tacos.id)] == ["Suadero", "Pastor"]


async def test_another_tenant_item_is_not_found(world: World) -> None:
    foreign = await world.item(await world.category("Tacos", TENANT_B), tenant_id=TENANT_B)

    with pytest.raises(ItemNotFound):
        await world.update_item().execute(TENANT_A, foreign.id, ItemChanges(is_available=False))
    with pytest.raises(ItemNotFound):
        await DeleteItem(world.items, world.images, world.uow).execute(TENANT_A, foreign.id)
    with pytest.raises(ItemNotFound):
        await world.set_image().execute(TENANT_A, foreign.id, await world.uploaded_image())

    assert world.items.items[foreign.id] == foreign


# --- Images ------------------------------------------------------------------------------------


async def test_upload_signatures_target_a_new_public_id_in_the_tenant_folder(world: World) -> None:
    first = await RequestImageUpload(world.images).execute(TENANT_A)
    second = await RequestImageUpload(world.images).execute(TENANT_A)

    assert first.public_id.startswith(f"tenants/{TENANT_A}/items/")
    assert first.public_id != second.public_id
    assert first.allowed_formats == ("jpg", "png", "webp")


async def test_sets_replaces_and_removes_an_item_image_deleting_the_previous_one(world: World) -> None:
    item = await world.item(await world.category())
    first = await world.uploaded_image()
    second = await world.uploaded_image()

    with_image = await world.set_image().execute(TENANT_A, item.id, first)
    replaced = await world.set_image().execute(TENANT_A, item.id, second)
    assert world.images.deleted == [first]
    removed = await RemoveItemImage(world.items, world.images, world.uow).execute(TENANT_A, item.id)

    assert (with_image.image_public_id, replaced.image_public_id, removed.image_public_id) == (first, second, None)
    assert world.images.deleted == [first, second]
    assert world.items.items[item.id].image_public_id is None


async def test_rejects_images_outside_the_tenant_folder_or_not_uploaded(world: World) -> None:
    item = await world.item(await world.category())
    foreign = await world.uploaded_image(TENANT_B)
    never_uploaded = (await RequestImageUpload(world.images).execute(TENANT_A)).public_id
    tricks = [foreign, never_uploaded, f"tenants/{TENANT_A}/items", f"tenants/{TENANT_A}/items/../x", "https://x/y.jpg"]

    for public_id in tricks:
        with pytest.raises(InvalidImage):
            await world.set_image().execute(TENANT_A, item.id, public_id)

    assert world.items.items[item.id].image_public_id is None
    assert foreign in world.images.stored


@pytest.mark.parametrize(("image_format", "size"), [("gif", 1_000), ("svg", 1_000), ("jpg", MAX_IMAGE_BYTES + 1)])
async def test_rejects_and_deletes_uploads_with_a_wrong_format_or_size(
    world: World, image_format: str, size: int
) -> None:
    item = await world.item(await world.category())
    public_id = await world.uploaded_image(image_format=image_format, size=size)

    with pytest.raises(InvalidImage):
        await world.set_image().execute(TENANT_A, item.id, public_id)

    assert world.images.deleted == [public_id]
    assert world.items.items[item.id].image_public_id is None


async def test_an_image_already_used_by_another_item_is_rejected(world: World) -> None:
    category = await world.category()
    first = await world.item(category, "Pastor")
    second = await world.item(category, "Suadero")
    public_id = await world.uploaded_image()
    await world.set_image().execute(TENANT_A, first.id, public_id)

    with pytest.raises(InvalidImage):
        await world.set_image().execute(TENANT_A, second.id, public_id)
    # Saving the same image again on its own item is harmless.
    again = await world.set_image().execute(TENANT_A, first.id, public_id)

    assert world.items.items[second.id].image_public_id is None
    assert again.image_public_id == public_id
    assert world.images.deleted == []


async def test_a_failing_storage_lookup_changes_nothing(world: World) -> None:
    item = await world.item(await world.category())
    public_id = await world.uploaded_image()
    world.images.fail_lookups = True
    commits = world.uow.commits

    with pytest.raises(ImageStorageUnavailable):
        await world.set_image().execute(TENANT_A, item.id, public_id)

    assert world.items.items[item.id].image_public_id is None
    assert world.uow.commits == commits


async def test_deleting_an_item_deletes_its_image(world: World) -> None:
    item = await world.item(await world.category())
    public_id = await world.uploaded_image()
    await world.set_image().execute(TENANT_A, item.id, public_id)

    await DeleteItem(world.items, world.images, world.uow).execute(TENANT_A, item.id)

    assert world.items.items == {}
    assert world.images.deleted == [public_id]


async def test_a_failing_image_cleanup_does_not_undo_the_committed_change(world: World) -> None:
    item = await world.item(await world.category())
    await world.set_image().execute(TENANT_A, item.id, await world.uploaded_image())
    world.images.fail_deletes = True

    removed = await RemoveItemImage(world.items, world.images, world.uow).execute(TENANT_A, item.id)

    assert removed.image_public_id is None
    assert world.items.items[item.id].image_public_id is None
