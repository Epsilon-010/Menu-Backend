"""Images live in an external storage; the database keeps only their public id.

The browser uploads straight to the storage with a signature the backend issues for one exact
public id inside the tenant's folder (`tenants/{tenant_id}/<kind>/<random>`), so an upload can
never land in another tenant's folder. Before saving a public id, the backend checks that it is
inside the caller's folder and asks the storage for its real format and size.
"""

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Folders and random names only: no dots (no "..", no extensions), no URLs.
_PUBLIC_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*")
_MAX_PUBLIC_ID_LENGTH = 255


class ImageKind(StrEnum):
    """What an image is for; the value is its folder inside the tenant's folder."""

    ITEM = "items"


ALLOWED_FORMATS: dict[ImageKind, tuple[str, ...]] = {ImageKind.ITEM: ("jpg", "png", "webp")}


class ImageVariant(StrEnum):
    """Sizes the API serves; the storage builds an optimized URL for each."""

    THUMBNAIL = "thumbnail"
    CARD = "card"


class InvalidImage(ValueError):
    pass


class ImageStorageUnavailable(Exception):
    """The image storage cannot be used: not configured, or failing right now. The message is for the admin."""


@dataclass(frozen=True)
class UploadSignature:
    """Everything the browser sends to the storage along with the file.

    `overwrite` is always False: an upload that was already checked cannot be replaced later
    by another file under the same public id.
    """

    upload_url: str
    api_key: str
    timestamp: int
    signature: str
    public_id: str
    allowed_formats: tuple[str, ...]
    overwrite: bool = False


@dataclass(frozen=True)
class StoredImage:
    public_id: str
    format: str
    bytes: int


def image_folder(tenant_id: uuid.UUID, kind: ImageKind) -> str:
    return f"tenants/{tenant_id}/{kind.value}"


def new_image_public_id(tenant_id: uuid.UUID, kind: ImageKind) -> str:
    return f"{image_folder(tenant_id, kind)}/{uuid.uuid4().hex}"


def ensure_owned_image(tenant_id: uuid.UUID, kind: ImageKind, public_id: str) -> str:
    """The public id must name one image inside the tenant's folder for that kind."""
    folder = f"{image_folder(tenant_id, kind)}/"
    if (
        len(public_id) > _MAX_PUBLIC_ID_LENGTH
        or not _PUBLIC_ID_PATTERN.fullmatch(public_id)
        or not public_id.startswith(folder)
        or "/" in public_id[len(folder) :]
    ):
        raise InvalidImage("The image does not belong to this business")
    return public_id


def validate_stored_image(image: StoredImage, kind: ImageKind) -> None:
    allowed = ALLOWED_FORMATS[kind]
    if image.format.lower() not in allowed:
        raise InvalidImage(f"Image format must be one of: {', '.join(allowed)}")
    if image.bytes > MAX_IMAGE_BYTES:
        raise InvalidImage(f"Image must be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB")


class ImageRegistry(Protocol):
    """Port: Postgres record of every image the backend signed (implemented by the media module).

    Cloudinary and Postgres share no transaction, so this record is what guarantees cleanup: an
    image is `pending` from signing until attached, and `discarded` once no longer used; a
    background job deletes discarded and expired pending images from the storage. None of these
    methods commit: the calling use case owns the transaction.
    """

    async def register(self, tenant_id: uuid.UUID, public_id: str) -> None: ...

    async def attach(self, tenant_id: uuid.UUID, public_id: str) -> bool:
        """Marks a pending image of the tenant as used. False if it is unknown, used or discarded."""
        ...

    async def discard(self, tenant_id: uuid.UUID, public_id: str) -> None:
        """Marks the image for deletion from the storage."""
        ...


class ImageCleanupScheduler(Protocol):
    """Port: asks the background worker to clean up discarded images soon.

    Best effort, called after the commit: it never raises, and a periodic run catches anything missed.
    """

    async def request_cleanup(self) -> None: ...


class ImageStorage(Protocol):
    def sign_upload(self, public_id: str, allowed_formats: tuple[str, ...]) -> UploadSignature:
        """Signs a direct browser upload to exactly that public id. Raises ImageStorageUnavailable."""
        ...

    async def find(self, public_id: str) -> StoredImage | None:
        """What the storage really holds under that id, or None. Raises ImageStorageUnavailable."""
        ...

    async def delete(self, public_id: str) -> None: ...

    def url(self, public_id: str, variant: ImageVariant) -> str | None:
        """Optimized delivery URL, or None when the storage is not configured."""
        ...
