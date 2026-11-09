"""A tenant cannot keep requesting upload signatures: each one is a pending row the cleanup still has to do."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select

from app.modules.media.infrastructure.models import ImageUploadModel
from app.modules.media.infrastructure.repository import SqlAlchemyImageUploads
from app.modules.media.domain.uploads import TooManyPendingUploads
from app.seed import SeedResult
from app.shared.infrastructure.config import Settings, get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from tests.integration.modules.catalog.test_catalog_api import (  # noqa: F401  (fixtures)
    SIGNATURE_URL as ITEM_SIGNATURE_URL,
    ClientFactory,
    admin_of,
    create_category,
    create_item,
    images,
    new_client,
    ok,
    tenant_a,
    tenant_b,
    upload_image,
    ITEMS_URL,
)
from tests.integration.modules.theming.test_theme_api import SIGNATURE_URL as THEME_SIGNATURE_URL
from tests.unit.fakes import FakeImageStorage

TOO_MANY = "Too many images are waiting to be used; try again later"


@pytest.fixture
def limit_of_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "image_max_pending_per_tenant", 2)


def sign_item(admin: TestClient) -> Response:
    return admin.post(ITEM_SIGNATURE_URL)


def sign_logo(admin: TestClient) -> Response:
    return admin.post(THEME_SIGNATURE_URL, json={"kind": "logo"})


def pending_rows(tenant_id: object) -> int:
    async def count() -> int:
        engine = create_engine(get_settings().database_url)
        try:
            async with create_session_factory(engine)() as session:
                query = (
                    select(func.count())
                    .select_from(ImageUploadModel)
                    .where(ImageUploadModel.tenant_id == tenant_id, ImageUploadModel.status == "pending")
                )
                return int(await session.scalar(query) or 0)
        finally:
            await engine.dispose()

    return asyncio.run(count())


def assert_refused(response: Response) -> None:
    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == TOO_MANY


def test_the_limit_defaults_to_one_hundred() -> None:
    assert Settings.model_fields["image_max_pending_per_tenant"].default == 100


def test_item_signatures_stop_at_the_limit_and_nothing_more_is_recorded(
    new_client: ClientFactory, tenant_a: SeedResult, limit_of_two: None
) -> None:
    admin = admin_of(new_client)
    assert ok(sign_item(admin))["public_id"].startswith(f"tenants/{tenant_a.tenant_id}/items/")
    ok(sign_item(admin))

    assert_refused(sign_item(admin))

    assert pending_rows(tenant_a.tenant_id) == 2


def test_theme_signatures_count_against_the_same_limit(
    new_client: ClientFactory, tenant_a: SeedResult, limit_of_two: None
) -> None:
    admin = admin_of(new_client)
    ok(sign_logo(admin))
    ok(sign_item(admin))

    assert_refused(sign_logo(admin))
    assert_refused(sign_item(admin))

    assert pending_rows(tenant_a.tenant_id) == 2


def test_a_tenant_at_its_limit_never_blocks_another(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult, limit_of_two: None
) -> None:
    admin = admin_of(new_client)
    ok(sign_item(admin))
    ok(sign_item(admin))
    assert_refused(sign_item(admin))

    other = admin_of(new_client, "boss@example.com")

    assert ok(sign_item(other))["public_id"].startswith(f"tenants/{tenant_b.tenant_id}/items/")
    assert pending_rows(tenant_b.tenant_id) == 1
    assert pending_rows(tenant_a.tenant_id) == 2


def test_attaching_an_image_frees_room_for_another(
    new_client: ClientFactory, tenant_a: SeedResult, images: FakeImageStorage, limit_of_two: None
) -> None:
    admin = admin_of(new_client)
    category = ok(create_category(admin, "Tacos"), 201)["id"]
    item = ok(create_item(admin, category, "Pastor", 2500), 201)["id"]
    public_id = upload_image(admin, images)
    ok(sign_item(admin))
    assert_refused(sign_item(admin))

    ok(admin.put(f"{ITEMS_URL}/{item}/image", json={"public_id": public_id}))

    ok(sign_item(admin))
    assert pending_rows(tenant_a.tenant_id) == 2


def test_concurrent_signatures_never_go_over_the_limit(tenant_a: SeedResult) -> None:
    async def run() -> list[bool]:
        engine = create_engine(get_settings().database_url)
        factory = create_session_factory(engine)
        try:

            async def register(n: int) -> bool:
                async with factory() as session:
                    uploads = SqlAlchemyImageUploads(session, max_pending=3)
                    try:
                        await uploads.register(tenant_a.tenant_id, f"tenants/{tenant_a.tenant_id}/items/{n}")
                    except TooManyPendingUploads:
                        return False
                    await session.commit()
                    return True

            return await asyncio.gather(*(register(n) for n in range(12)))
        finally:
            await engine.dispose()

    results = asyncio.run(run())

    assert results.count(True) == 3
    assert pending_rows(tenant_a.tenant_id) == 3


def test_an_unconfigured_storage_still_answers_503_before_any_limit(
    new_client: ClientFactory, tenant_a: SeedResult, limit_of_two: None
) -> None:
    from app.shared.infrastructure.images import UnconfiguredImageStorage

    admin = admin_of(new_client)
    admin.app.state.image_storage = UnconfiguredImageStorage()  # type: ignore[attr-defined]

    assert sign_item(admin).status_code == 503
    assert pending_rows(tenant_a.tenant_id) == 0
