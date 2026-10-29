from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.infrastructure.jobs import image_cleanup_scheduler, image_registry
from app.modules.theming.application.manage_theme import (
    GetPublishedTheme,
    GetThemeDraft,
    PublishTheme,
    RequestThemeImageUpload,
    SaveThemeDraft,
    ThemeState,
)
from app.modules.theming.domain.presets import PRESETS
from app.modules.theming.domain.theme import InvalidTheme, Theme, colors_to_dict, contrast_warnings, default_colors
from app.modules.theming.infrastructure.repository import SqlAlchemyThemeRepository
from app.modules.theming.infrastructure.theme_cache import RedisThemeCache
from app.shared.domain.images import (
    MAX_IMAGE_BYTES,
    ImageCleanupScheduler,
    ImageKind,
    ImageStorage,
    ImageStorageUnavailable,
    ImageVariant,
    InvalidImage,
)
from app.shared.domain.principal import Principal
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import CurrentPrincipal, require_role
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import SystemClock

router = APIRouter(prefix="/theme", tags=["theme"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_role("admin"))]
T = TypeVar("T")


def get_image_storage(request: Request) -> ImageStorage:
    storage: ImageStorage = request.app.state.image_storage
    return storage


def theme_cache(request: Request) -> RedisThemeCache:
    return RedisThemeCache(request.app.state.redis)


ImagesDep = Annotated[ImageStorage, Depends(get_image_storage)]
CleanupDep = Annotated[ImageCleanupScheduler, Depends(image_cleanup_scheduler)]
CacheDep = Annotated[RedisThemeCache, Depends(theme_cache)]


# --- Schemas: the shape and JSON types only (strict, unknown fields rejected); the domain checks every value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GradientDoc(_Strict):
    enabled: StrictBool
    from_: StrictStr = Field(alias="from")
    to: StrictStr
    angle: StrictInt


class ColorsDoc(_Strict):
    mode: StrictStr
    primary: StrictStr
    secondary: StrictStr
    accent: StrictStr
    background: StrictStr
    surface: StrictStr
    text: StrictStr
    text_muted: StrictStr
    price: StrictStr
    button_bg: StrictStr
    button_text: StrictStr
    button_hover: StrictStr
    border: StrictStr
    badge_bg: StrictStr
    badge_text: StrictStr
    cart_bg: StrictStr
    cart_text: StrictStr
    gradient: GradientDoc


class LogoDoc(_Strict):
    image_id: StrictStr | None
    size: StrictStr
    position: StrictStr


class BannerDoc(_Strict):
    image_id: StrictStr | None
    height: StrictStr
    overlay_color: StrictStr
    overlay_opacity: StrictInt


class BackgroundDoc(_Strict):
    kind: StrictStr
    image_id: StrictStr | None
    pattern: StrictStr
    opacity: StrictInt
    blur: StrictInt


class BrandDoc(_Strict):
    name: StrictStr
    tagline: StrictStr
    welcome_message: StrictStr
    logo: LogoDoc
    banner: BannerDoc
    background: BackgroundDoc


class RoleFontsDoc(_Strict):
    heading: StrictStr
    body: StrictStr
    price: StrictStr
    button: StrictStr


class TextStyleDoc(_Strict):
    font: StrictStr
    size: StrictInt
    weight: StrictInt
    style: StrictStr
    line_height: StrictInt
    letter_spacing: StrictInt
    transform: StrictStr
    align: StrictStr


class TextElementsDoc(_Strict):
    business_name: TextStyleDoc
    category: TextStyleDoc
    product_name: TextStyleDoc
    description: TextStyleDoc
    price: TextStyleDoc
    button: TextStyleDoc


class TypographyDoc(_Strict):
    scale: StrictInt
    fonts: RoleFontsDoc
    elements: TextElementsDoc


class LayoutDoc(_Strict):
    navigation: StrictStr
    product_view: StrictStr
    columns: StrictInt
    density: StrictStr
    sticky_header: StrictBool
    category_header: StrictStr
    show_banner: StrictBool
    show_tagline: StrictBool
    show_welcome: StrictBool
    cart: StrictStr


class ThemeDoc(_Strict):
    schema_version: StrictInt
    colors: ColorsDoc
    brand: BrandDoc
    typography: TypographyDoc
    layout: LayoutDoc


class ContrastWarningOut(BaseModel):
    foreground: str
    background: str
    ratio: float


class DefaultPalettesOut(BaseModel):
    light: ColorsDoc
    dark: ColorsDoc


class ThemePresetOut(BaseModel):
    id: str
    name: str
    description: str
    colors: ColorsDoc
    typography: TypographyDoc
    layout: LayoutDoc


class ThemeDraftOut(BaseModel):
    draft: ThemeDoc
    published: ThemeDoc | None
    published_at: datetime | None
    has_unpublished_changes: bool
    contrast_warnings: list[ContrastWarningOut]
    defaults: DefaultPalettesOut
    # Complete designs (colors, typography and layout) the editor applies to the draft; the brand is never part of one.
    presets: list[ThemePresetOut]
    # Delivery URL of every image the draft or the published theme uses, by public id.
    image_urls: dict[str, str]


class PublishedThemeOut(BaseModel):
    theme: ThemeDoc
    image_urls: dict[str, str]


class ImageSlotIn(_Strict):
    kind: Literal["logo", "banner", "background"]


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


_SLOT_KINDS = {"logo": ImageKind.LOGO, "banner": ImageKind.BANNER, "background": ImageKind.BACKGROUND}
_KIND_VARIANTS = {
    ImageKind.LOGO: ImageVariant.LOGO,
    ImageKind.BANNER: ImageVariant.BANNER,
    ImageKind.BACKGROUND: ImageVariant.BACKGROUND,
}


def _doc(theme: Theme) -> ThemeDoc:
    return ThemeDoc.model_validate(theme.to_dict())


def _image_urls(images: ImageStorage, *themes: Theme | None) -> dict[str, str]:
    urls: dict[str, str] = {}
    for theme in themes:
        if theme is None:
            continue
        for public_id, kind in theme.images().items():
            url = images.url(public_id, _KIND_VARIANTS[kind])
            if url is not None:
                urls[public_id] = url
    return urls


def _draft_out(state: ThemeState, images: ImageStorage) -> ThemeDraftOut:
    return ThemeDraftOut(
        draft=_doc(state.draft),
        published=_doc(state.published) if state.published is not None else None,
        published_at=state.published_at,
        has_unpublished_changes=state.has_unpublished_changes,
        contrast_warnings=[ContrastWarningOut(**vars(w)) for w in contrast_warnings(state.draft.colors)],
        defaults=DefaultPalettesOut(
            light=ColorsDoc.model_validate(colors_to_dict(default_colors("light"))),
            dark=ColorsDoc.model_validate(colors_to_dict(default_colors("dark"))),
        ),
        presets=[ThemePresetOut.model_validate(preset.to_dict()) for preset in PRESETS],
        image_urls=_image_urls(images, state.draft, state.published),
    )


async def _run(call: Awaitable[T]) -> T | JSONResponse:
    """Maps the theme's expected errors to RFC 9457 problems."""
    try:
        return await call
    except (InvalidTheme, InvalidImage) as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except ImageStorageUnavailable as error:
        return problem(status.HTTP_503_SERVICE_UNAVAILABLE, str(error) or "Image storage is not available")


# --- Use case factories


def get_published_theme(session: SessionDep) -> GetPublishedTheme:
    return GetPublishedTheme(SqlAlchemyThemeRepository(session))


def get_theme_draft(session: SessionDep) -> GetThemeDraft:
    return GetThemeDraft(SqlAlchemyThemeRepository(session))


def get_save_theme_draft(session: SessionDep, images: ImagesDep, cleanup: CleanupDep) -> SaveThemeDraft:
    return SaveThemeDraft(
        SqlAlchemyThemeRepository(session), images, image_registry(session), SqlAlchemyUnitOfWork(session), cleanup
    )


def get_publish_theme(session: SessionDep, cleanup: CleanupDep, cache: CacheDep) -> PublishTheme:
    return PublishTheme(
        SqlAlchemyThemeRepository(session),
        image_registry(session),
        SqlAlchemyUnitOfWork(session),
        cleanup,
        cache,
        SystemClock(),
    )


def get_request_theme_image_upload(session: SessionDep, images: ImagesDep) -> RequestThemeImageUpload:
    return RequestThemeImageUpload(images, image_registry(session), SqlAlchemyUnitOfWork(session))


# --- Routes


@router.get("", response_model=PublishedThemeOut)
async def read_published_theme(
    principal: CurrentPrincipal,
    images: ImagesDep,
    cache: CacheDep,
    use_case: Annotated[GetPublishedTheme, Depends(get_published_theme)],
) -> Response:
    """Every signed-in role reads its own tenant's published theme (the table menu is drawn with it)."""
    generation, cached = await cache.get(principal.tenant_id)
    if cached is None:
        theme = await use_case.execute(principal.tenant_id)
        cached = PublishedThemeOut(theme=_doc(theme), image_urls=_image_urls(images, theme)).model_dump_json(
            by_alias=True
        )
        if generation is not None:
            await cache.put(principal.tenant_id, generation, cached)
    return Response(content=cached, media_type="application/json")


@router.get("/draft", response_model=ThemeDraftOut)
async def read_theme_draft(
    admin: Admin, images: ImagesDep, use_case: Annotated[GetThemeDraft, Depends(get_theme_draft)]
) -> ThemeDraftOut:
    return _draft_out(await use_case.execute(admin.tenant_id), images)


@router.put("/draft", response_model=ThemeDraftOut)
async def save_theme_draft(
    body: ThemeDoc,
    admin: Admin,
    images: ImagesDep,
    use_case: Annotated[SaveThemeDraft, Depends(get_save_theme_draft)],
) -> ThemeDraftOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id, body.model_dump(by_alias=True)))
    return result if isinstance(result, JSONResponse) else _draft_out(result, images)


@router.post("/publish", response_model=ThemeDraftOut)
async def publish_theme(
    admin: Admin, images: ImagesDep, use_case: Annotated[PublishTheme, Depends(get_publish_theme)]
) -> ThemeDraftOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id))
    return result if isinstance(result, JSONResponse) else _draft_out(result, images)


@router.post("/images/signature", response_model=UploadSignatureOut)
async def sign_theme_image_upload(
    body: ImageSlotIn,
    admin: Admin,
    use_case: Annotated[RequestThemeImageUpload, Depends(get_request_theme_image_upload)],
) -> UploadSignatureOut | JSONResponse:
    result = await _run(use_case.execute(admin.tenant_id, _SLOT_KINDS[body.kind]))
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
