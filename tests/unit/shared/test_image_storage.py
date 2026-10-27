"""The Cloudinary adapter's offline parts: upload signing, delivery URLs and configuration."""

import hashlib

import cloudinary.api
import cloudinary.exceptions
import pytest
from pydantic import SecretStr

from app.shared.domain.images import ImageStorageUnavailable, ImageVariant
from app.shared.infrastructure.config import Settings
from app.shared.infrastructure.images import (
    STORAGE_TIMEOUT_SECONDS,
    CloudinaryImageStorage,
    UnconfiguredImageStorage,
    build_image_storage,
)

pytestmark = pytest.mark.anyio

PUBLIC_ID = "tenants/0f6e/items/abc123"


def _settings(**values: str) -> Settings:
    # Explicit values win over .env and the environment, which may hold real credentials.
    unset: dict[str, str | None] = {"cloudinary_cloud_name": None, "cloudinary_api_key": None, "cloudinary_api_secret": None}
    return Settings(jwt_secret=SecretStr("x" * 32), **(unset | values))  # type: ignore[arg-type]


def test_signs_the_exact_public_id_and_formats_with_cloudinarys_sha1_scheme() -> None:
    storage = CloudinaryImageStorage("demo-cloud", "key-123", "secret-xyz")

    signature = storage.sign_upload(PUBLIC_ID, ("jpg", "png", "webp"))

    # Cloudinary: sorted "key=value" pairs joined by "&", then the API secret, hashed with SHA-1.
    # overwrite=false: a checked upload cannot be replaced later with another file under the same id.
    payload = (
        f"allowed_formats=jpg,png,webp&overwrite=false&public_id={PUBLIC_ID}&timestamp={signature.timestamp}secret-xyz"
    )
    assert signature.signature == hashlib.sha1(payload.encode()).hexdigest()
    assert signature.upload_url == "https://api.cloudinary.com/v1_1/demo-cloud/image/upload"
    assert (signature.api_key, signature.public_id) == ("key-123", PUBLIC_ID)
    assert "secret-xyz" not in repr(signature)


@pytest.mark.parametrize(
    "failure",
    [cloudinary.exceptions.RateLimited("slow down"), cloudinary.exceptions.AuthorizationRequired("bad key"), OSError("timeout")],
)
async def test_storage_failures_other_than_not_found_mean_unavailable(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def resource(public_id: str, **options: object) -> dict[str, object]:
        raise failure

    monkeypatch.setattr(cloudinary.api, "resource", resource)

    with pytest.raises(ImageStorageUnavailable):
        await CloudinaryImageStorage("demo-cloud", "key-123", "secret-xyz").find(PUBLIC_ID)


async def test_a_missing_image_is_none_and_lookups_have_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def resource(public_id: str, **options: object) -> dict[str, object]:
        calls.append(options)
        raise cloudinary.exceptions.NotFound("missing")

    monkeypatch.setattr(cloudinary.api, "resource", resource)

    assert await CloudinaryImageStorage("demo-cloud", "key-123", "secret-xyz").find(PUBLIC_ID) is None
    assert calls[0]["timeout"] == STORAGE_TIMEOUT_SECONDS


def test_delivery_urls_are_optimized_and_sized_per_use() -> None:
    storage = CloudinaryImageStorage("demo-cloud", "key-123", "secret-xyz")

    thumbnail = storage.url(PUBLIC_ID, ImageVariant.THUMBNAIL)
    card = storage.url(PUBLIC_ID, ImageVariant.CARD)

    assert thumbnail is not None and card is not None
    assert thumbnail.startswith("https://res.cloudinary.com/demo-cloud/image/upload/")
    assert thumbnail.endswith(f"/{PUBLIC_ID}")
    for part in ("c_fill", "f_auto", "q_auto", "w_160", "h_160"):
        assert part in thumbnail
    assert "w_640" in card and "h_480" in card


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"cloudinary_cloud_name": "", "cloudinary_api_key": "", "cloudinary_api_secret": ""},
        {"cloudinary_cloud_name": "demo-cloud", "cloudinary_api_key": "key-123"},
    ],
)
async def test_missing_credentials_leave_images_unavailable(values: dict[str, str]) -> None:
    storage = build_image_storage(_settings(**values))

    assert isinstance(storage, UnconfiguredImageStorage)
    assert storage.url(PUBLIC_ID, ImageVariant.CARD) is None
    with pytest.raises(ImageStorageUnavailable):
        storage.sign_upload(PUBLIC_ID, ("jpg",))
    with pytest.raises(ImageStorageUnavailable):
        await storage.find(PUBLIC_ID)


def test_full_credentials_use_cloudinary() -> None:
    storage = build_image_storage(
        _settings(cloudinary_cloud_name="demo-cloud", cloudinary_api_key="key-123", cloudinary_api_secret="secret-xyz")
    )

    assert isinstance(storage, CloudinaryImageStorage)
