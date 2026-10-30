import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.menu import GetMenu
from app.modules.catalog.infrastructure.menu_cache import RedisMenuCache
from app.modules.catalog.infrastructure.repository import SqlAlchemyCategoryRepository, SqlAlchemyItemRepository
from app.shared.domain.images import ImageStorage, ImageVariant
from app.shared.infrastructure.database import get_session
from app.shared.infrastructure.http.auth import CurrentPrincipal

router = APIRouter(prefix="/menu", tags=["menu"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class MenuImageOut(BaseModel):
    thumbnail_url: str | None
    card_url: str | None


class MenuItemOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    price_cents: int
    image: MenuImageOut | None
    badges: list[str]


class MenuCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    items: list[MenuItemOut]


_MENU = TypeAdapter(list[MenuCategoryOut])


def menu_cache(request: Request) -> RedisMenuCache:
    return RedisMenuCache(request.app.state.redis)


def get_menu(session: SessionDep) -> GetMenu:
    return GetMenu(SqlAlchemyCategoryRepository(session), SqlAlchemyItemRepository(session))


async def _read_menu(tenant_id: uuid.UUID, use_case: GetMenu, images: ImageStorage) -> list[MenuCategoryOut]:
    return [
        MenuCategoryOut(
            id=entry.category.id,
            name=entry.category.name,
            items=[
                MenuItemOut(
                    id=item.id,
                    name=item.name,
                    description=item.description,
                    price_cents=item.price_cents,
                    image=MenuImageOut(
                        thumbnail_url=images.url(item.image_public_id, ImageVariant.THUMBNAIL),
                        card_url=images.url(item.image_public_id, ImageVariant.CARD),
                    )
                    if item.image_public_id is not None
                    else None,
                    badges=list(item.badges),
                )
                for item in entry.items
            ],
        )
        for entry in await use_case.execute(tenant_id)
    ]


@router.get("", response_model=list[MenuCategoryOut])
async def read_menu(
    principal: CurrentPrincipal,
    request: Request,
    use_case: Annotated[GetMenu, Depends(get_menu)],
    cache: Annotated[RedisMenuCache, Depends(menu_cache)],
) -> Response:
    """Every signed-in role reads its own tenant's menu (tables and guests order from it)."""
    generation, cached = await cache.get(principal.tenant_id)
    if cached is None:
        menu = await _read_menu(principal.tenant_id, use_case, request.app.state.image_storage)
        cached = _MENU.dump_json(menu).decode()
        if generation is not None:
            await cache.put(principal.tenant_id, generation, cached)
    return Response(content=cached, media_type="application/json")
