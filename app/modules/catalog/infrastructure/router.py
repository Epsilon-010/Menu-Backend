import uuid
from collections.abc import AsyncIterator, Awaitable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.item_images import RemoveItemImage, RequestImageUpload, SetItemImage
from app.modules.catalog.application.manage_categories import (
    CategoryWithItems,
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
from app.modules.catalog.domain.catalog import MAX_PRICE_CENTS, Category, Item
from app.modules.catalog.domain.errors import (
    CatalogIdTaken,
    CategoryNameNotAvailable,
    CategoryNotEmpty,
    CategoryNotFound,
    InvalidCatalogData,
    ItemNotFound,
)
from app.modules.catalog.infrastructure.menu_router import menu_cache
from app.modules.catalog.infrastructure.repository import SqlAlchemyCategoryRepository, SqlAlchemyItemRepository
from app.modules.media.infrastructure.jobs import image_cleanup_scheduler, image_registry
from app.shared.domain.images import (
    MAX_IMAGE_BYTES,
    ImageCleanupScheduler,
    ImageStorage,
    ImageStorageUnavailable,
    ImageVariant,
    InvalidImage,
)
from app.shared.domain.principal import Principal
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import CurrentPrincipal, require_role
from app.shared.infrastructure.http.problems import problem

async def _invalidate_menu_after_writes(principal: CurrentPrincipal, request: Request) -> AsyncIterator[None]:
    """Runs after every catalog route has committed: any write may change what tables see."""
    yield
    if request.method not in ("GET", "HEAD"):
        await menu_cache(request).invalidate(principal.tenant_id)


router = APIRouter(prefix="/catalog", tags=["catalog"], dependencies=[Depends(_invalidate_menu_after_writes)])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_role("admin"))]
T = TypeVar("T")


def get_image_storage(request: Request) -> ImageStorage:
    storage: ImageStorage = request.app.state.image_storage
    return storage


ImagesDep = Annotated[ImageStorage, Depends(get_image_storage)]
CleanupDep = Annotated[ImageCleanupScheduler, Depends(image_cleanup_scheduler)]


# --- Schemas (unknown fields are rejected; prices are strict integers: no floats, no strings) ---


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryIn(_In):
    # Optional client-chosen id: sending the same create again returns the same category.
    id: uuid.UUID | None = None
    name: str = Field(max_length=200)


class CategoryUpdate(_In):
    name: str | None = Field(default=None, max_length=200)
    is_visible: bool | None = None


class ItemIn(_In):
    # Optional client-chosen id: sending the same create again returns the same item.
    id: uuid.UUID | None = None
    category_id: uuid.UUID
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    price_cents: int = Field(strict=True, ge=0, le=MAX_PRICE_CENTS)


class ItemUpdate(_In):
    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    price_cents: int | None = Field(default=None, strict=True, ge=0, le=MAX_PRICE_CENTS)
    is_available: bool | None = None


class OrderIn(_In):
    ids: list[uuid.UUID] = Field(max_length=1000)


class ImageIn(_In):
    public_id: str = Field(max_length=300)


class ImageOut(BaseModel):
    public_id: str
    thumbnail_url: str | None
    card_url: str | None


class ItemOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str
    price_cents: int
    position: int
    is_available: bool
    image: ImageOut | None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    is_visible: bool


class CategoryWithItemsOut(CategoryOut):
    items: list[ItemOut]


class UploadSignatureOut(BaseModel):
    """Fields the browser posts to `upload_url` with the file (all but `upload_url` and `max_bytes`)."""

    upload_url: str
    api_key: str
    timestamp: int
    signature: str
    public_id: str
    allowed_formats: list[str]
    overwrite: bool
    max_bytes: int


def _item_out(item: Item, images: ImageStorage) -> ItemOut:
    image = None
    if item.image_public_id is not None:
        image = ImageOut(
            public_id=item.image_public_id,
            thumbnail_url=images.url(item.image_public_id, ImageVariant.THUMBNAIL),
            card_url=images.url(item.image_public_id, ImageVariant.CARD),
        )
    return ItemOut(
        id=item.id,
        category_id=item.category_id,
        name=item.name,
        description=item.description,
        price_cents=item.price_cents,
        position=item.position,
        is_available=item.is_available,
        image=image,
    )


def _category_out(category: Category) -> CategoryOut:
    return CategoryOut(id=category.id, name=category.name, position=category.position, is_visible=category.is_visible)


async def _run(call: Awaitable[T]) -> T | JSONResponse:
    """Maps the catalog's expected errors to RFC 9457 problems."""
    try:
        return await call
    except (InvalidCatalogData, InvalidImage) as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except CategoryNameNotAvailable:
        return problem(status.HTTP_409_CONFLICT, "Category name already in use")
    except CatalogIdTaken:
        return problem(status.HTTP_409_CONFLICT, "That id is already used by something else")
    except CategoryNotEmpty:
        return problem(status.HTTP_409_CONFLICT, "Category still has items")
    except CategoryNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Category not found")
    except ItemNotFound:
        return problem(status.HTTP_404_NOT_FOUND, "Item not found")
    except ImageStorageUnavailable as error:
        return problem(status.HTTP_503_SERVICE_UNAVAILABLE, str(error) or "Image storage is not available")


# --- Wiring ------------------------------------------------------------------------------------


def _categories(session: AsyncSession) -> SqlAlchemyCategoryRepository:
    return SqlAlchemyCategoryRepository(session)


def _items(session: AsyncSession) -> SqlAlchemyItemRepository:
    return SqlAlchemyItemRepository(session)


def get_list_catalog(session: SessionDep) -> ListCatalog:
    return ListCatalog(_categories(session), _items(session))


def get_create_category(session: SessionDep) -> CreateCategory:
    return CreateCategory(_categories(session), SqlAlchemyUnitOfWork(session))


def get_update_category(session: SessionDep) -> UpdateCategory:
    return UpdateCategory(_categories(session), SqlAlchemyUnitOfWork(session))


def get_delete_category(session: SessionDep) -> DeleteCategory:
    return DeleteCategory(_categories(session), SqlAlchemyUnitOfWork(session))


def get_reorder_categories(session: SessionDep) -> ReorderCategories:
    return ReorderCategories(_categories(session), SqlAlchemyUnitOfWork(session))


def get_create_item(session: SessionDep) -> CreateItem:
    return CreateItem(_categories(session), _items(session), SqlAlchemyUnitOfWork(session))


def get_update_item(session: SessionDep) -> UpdateItem:
    return UpdateItem(_categories(session), _items(session), SqlAlchemyUnitOfWork(session))


def get_delete_item(session: SessionDep, cleanup: CleanupDep) -> DeleteItem:
    return DeleteItem(_items(session), image_registry(session), SqlAlchemyUnitOfWork(session), cleanup)


def get_reorder_items(session: SessionDep) -> ReorderItems:
    return ReorderItems(_categories(session), _items(session), SqlAlchemyUnitOfWork(session))


def get_request_image_upload(session: SessionDep, images: ImagesDep) -> RequestImageUpload:
    return RequestImageUpload(images, image_registry(session), SqlAlchemyUnitOfWork(session))


def get_set_item_image(session: SessionDep, images: ImagesDep, cleanup: CleanupDep) -> SetItemImage:
    return SetItemImage(_items(session), images, image_registry(session), SqlAlchemyUnitOfWork(session), cleanup)


def get_remove_item_image(session: SessionDep, cleanup: CleanupDep) -> RemoveItemImage:
    return RemoveItemImage(_items(session), image_registry(session), SqlAlchemyUnitOfWork(session), cleanup)


# --- Routes (admin only; the tenant always comes from the token) -------------------------------


@router.get("/categories", response_model=list[CategoryWithItemsOut])
async def list_catalog(
    admin: Admin, images: ImagesDep, use_case: Annotated[ListCatalog, Depends(get_list_catalog)]
) -> list[CategoryWithItemsOut]:
    entries: list[CategoryWithItems] = await use_case.execute(admin.tenant_id)
    return [
        CategoryWithItemsOut(
            **_category_out(entry.category).model_dump(), items=[_item_out(item, images) for item in entry.items]
        )
        for entry in entries
    ]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryIn, admin: Admin, use_case: Annotated[CreateCategory, Depends(get_create_category)]
) -> CategoryOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id, body.name, body.id))
    return result if isinstance(result, JSONResponse) else _category_out(result)


# Declared before "/categories/{category_id}" routes so "order" is never read as an id.
@router.put("/categories/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_categories(
    body: OrderIn, admin: Admin, use_case: Annotated[ReorderCategories, Depends(get_reorder_categories)]
) -> Response:
    result = await _run(use_case.execute(admin.tenant_id, body.ids))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdate,
    admin: Admin,
    use_case: Annotated[UpdateCategory, Depends(get_update_category)],
) -> CategoryOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id, category_id, name=body.name, is_visible=body.is_visible))
    return result if isinstance(result, JSONResponse) else _category_out(result)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID, admin: Admin, use_case: Annotated[DeleteCategory, Depends(get_delete_category)]
) -> Response:
    result = await _run(use_case.execute(admin.tenant_id, category_id))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/categories/{category_id}/items/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_items(
    category_id: uuid.UUID,
    body: OrderIn,
    admin: Admin,
    use_case: Annotated[ReorderItems, Depends(get_reorder_items)],
) -> Response:
    result = await _run(use_case.execute(admin.tenant_id, category_id, body.ids))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: ItemIn, admin: Admin, images: ImagesDep, use_case: Annotated[CreateItem, Depends(get_create_item)]
) -> ItemOut | JSONResponse:
    draft = ItemDraft(
        category_id=body.category_id,
        name=body.name,
        description=body.description,
        price_cents=body.price_cents,
        id=body.id,
    )
    result = await _run(use_case.execute(admin.tenant_id, draft))
    return result if isinstance(result, JSONResponse) else _item_out(result, images)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    admin: Admin,
    images: ImagesDep,
    use_case: Annotated[UpdateItem, Depends(get_update_item)],
) -> ItemOut | JSONResponse:
    changes = ItemChanges(
        name=body.name,
        description=body.description,
        price_cents=body.price_cents,
        is_available=body.is_available,
        category_id=body.category_id,
    )
    result = await _run(use_case.execute(admin.tenant_id, item_id, changes))
    return result if isinstance(result, JSONResponse) else _item_out(result, images)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID, admin: Admin, use_case: Annotated[DeleteItem, Depends(get_delete_item)]
) -> Response:
    result = await _run(use_case.execute(admin.tenant_id, item_id))
    return result if isinstance(result, JSONResponse) else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/images/signature", response_model=UploadSignatureOut)
async def sign_image_upload(
    admin: Admin, use_case: Annotated[RequestImageUpload, Depends(get_request_image_upload)]
) -> UploadSignatureOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id))
    if isinstance(result, JSONResponse):
        return result
    return UploadSignatureOut(
        upload_url=result.upload_url,
        api_key=result.api_key,
        timestamp=result.timestamp,
        signature=result.signature,
        public_id=result.public_id,
        allowed_formats=list(result.allowed_formats),
        overwrite=result.overwrite,
        max_bytes=MAX_IMAGE_BYTES,
    )


@router.put("/items/{item_id}/image", response_model=ItemOut)
async def set_item_image(
    item_id: uuid.UUID,
    body: ImageIn,
    admin: Admin,
    images: ImagesDep,
    use_case: Annotated[SetItemImage, Depends(get_set_item_image)],
) -> ItemOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id, item_id, body.public_id))
    return result if isinstance(result, JSONResponse) else _item_out(result, images)


@router.delete("/items/{item_id}/image", response_model=ItemOut)
async def remove_item_image(
    item_id: uuid.UUID,
    admin: Admin,
    images: ImagesDep,
    use_case: Annotated[RemoveItemImage, Depends(get_remove_item_image)],
) -> ItemOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id, item_id))
    return result if isinstance(result, JSONResponse) else _item_out(result, images)
