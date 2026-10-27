"""Image storage adapters. This is the only module that imports the Cloudinary SDK.

The SDK talks HTTP synchronously, so its network calls run in a worker thread. Credentials are
passed on every call instead of through the SDK's global config.
"""

import asyncio
import time
from typing import Any

import cloudinary.api
import cloudinary.exceptions
import cloudinary.uploader
import cloudinary.utils

from app.shared.domain.images import ImageStorage, ImageStorageUnavailable, ImageVariant, StoredImage, UploadSignature
from app.shared.infrastructure.config import Settings

# Crop to fill the box, automatic format (WebP/AVIF when the browser takes it) and quality.
_VARIANT_TRANSFORMATIONS: dict[ImageVariant, dict[str, Any]] = {
    ImageVariant.THUMBNAIL: {"width": 160, "height": 160, "crop": "fill", "fetch_format": "auto", "quality": "auto"},
    ImageVariant.CARD: {"width": 640, "height": 480, "crop": "fill", "fetch_format": "auto", "quality": "auto"},
}


class CloudinaryImageStorage:
    def __init__(self, cloud_name: str, api_key: str, api_secret: str) -> None:
        self._cloud_name = cloud_name
        self._api_key = api_key
        self._api_secret = api_secret

    def _credentials(self) -> dict[str, str]:
        return {"cloud_name": self._cloud_name, "api_key": self._api_key, "api_secret": self._api_secret}

    def sign_upload(self, public_id: str, allowed_formats: tuple[str, ...]) -> UploadSignature:
        # Every signed parameter must be sent by the browser exactly as signed: the public id
        # cannot be changed and the formats cannot be widened. Cloudinary accepts a signature
        # for one hour after its timestamp.
        timestamp = int(time.time())
        params = {"timestamp": timestamp, "public_id": public_id, "allowed_formats": ",".join(allowed_formats)}
        return UploadSignature(
            upload_url=f"https://api.cloudinary.com/v1_1/{self._cloud_name}/image/upload",
            api_key=self._api_key,
            timestamp=timestamp,
            signature=cloudinary.utils.api_sign_request(params, self._api_secret),
            public_id=public_id,
            allowed_formats=allowed_formats,
        )

    async def find(self, public_id: str) -> StoredImage | None:
        try:
            resource = await asyncio.to_thread(cloudinary.api.resource, public_id, **self._credentials())
        except cloudinary.exceptions.NotFound:
            return None
        return StoredImage(public_id=public_id, format=str(resource["format"]), bytes=int(resource["bytes"]))

    async def delete(self, public_id: str) -> None:
        await asyncio.to_thread(cloudinary.uploader.destroy, public_id, invalidate=True, **self._credentials())

    def url(self, public_id: str, variant: ImageVariant) -> str | None:
        url, _ = cloudinary.utils.cloudinary_url(
            public_id, secure=True, cloud_name=self._cloud_name, **_VARIANT_TRANSFORMATIONS[variant]
        )
        return str(url)


class UnconfiguredImageStorage:
    """Used while the Cloudinary credentials are missing: the API runs, images are unavailable."""

    def sign_upload(self, public_id: str, allowed_formats: tuple[str, ...]) -> UploadSignature:
        raise ImageStorageUnavailable

    async def find(self, public_id: str) -> StoredImage | None:
        raise ImageStorageUnavailable

    async def delete(self, public_id: str) -> None:
        raise ImageStorageUnavailable

    def url(self, public_id: str, variant: ImageVariant) -> str | None:
        return None


def build_image_storage(settings: Settings) -> ImageStorage:
    secret = settings.cloudinary_api_secret
    if settings.cloudinary_cloud_name and settings.cloudinary_api_key and secret and secret.get_secret_value():
        return CloudinaryImageStorage(settings.cloudinary_cloud_name, settings.cloudinary_api_key, secret.get_secret_value())
    return UnconfiguredImageStorage()
