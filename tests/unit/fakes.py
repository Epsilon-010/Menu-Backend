"""In-memory fakes for the domain ports, shared by the unit tests."""

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from app.modules.auth.domain.refresh_token import RefreshToken
from app.modules.catalog.domain.catalog import Category, Item
from app.modules.catalog.domain.errors import CategoryNotEmpty
from app.modules.media.domain.uploads import DueImage
from app.modules.staff.domain.user import STAFF_MEMBER_ROLES, User
from app.modules.tables.domain.table import Table
from app.modules.tenants.domain.tenant import Tenant
from app.shared.domain.images import ImageStorageUnavailable, ImageVariant, StoredImage, UploadSignature


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now_value = now or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.now_value

    def advance(self, delta: timedelta) -> None:
        self.now_value += delta


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakePasswordHasher:
    """Reversible stand-in for Argon2: keeps tests fast and readable."""

    def __init__(self) -> None:
        self.verified: list[str] = []

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verified.append(password_hash)
        return password_hash == f"hashed:{password}"

    async def verify_dummy(self, password: str) -> None:
        self.verified.append("dummy")


class InMemoryTenantRepository:
    def __init__(self) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}

    async def add(self, tenant: Tenant) -> None:
        self.tenants[tenant.id] = tenant

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self.tenants.get(tenant_id)


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        # Ids read with get_for_update: proves a write use case locked its row.
        self.locked: list[uuid.UUID] = []
        self.create_locks: list[uuid.UUID] = []

    async def add(self, user: User) -> None:
        self.users[user.id] = user

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        user = self.users.get(user_id)
        return user if user is not None and user.tenant_id == tenant_id else None

    async def get_for_update(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        self.locked.append(user_id)
        return await self.get(tenant_id, user_id)

    async def exists_anywhere(self, user_id: uuid.UUID) -> bool:
        return user_id in self.users

    async def lock_creates(self, tenant_id: uuid.UUID) -> None:
        self.create_locks.append(tenant_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def get_by_username(self, username: str) -> User | None:
        return next((user for user in self.users.values() if user.username == username), None)

    async def list_staff(self, tenant_id: uuid.UUID) -> list[User]:
        staff = [user for user in self.users.values() if user.tenant_id == tenant_id and user.role in STAFF_MEMBER_ROLES]
        return sorted(staff, key=lambda user: user.full_name.lower())

    async def update(self, user: User) -> None:
        self.users[user.id] = user


class InMemoryTableRepository:
    def __init__(self) -> None:
        self.tables: dict[uuid.UUID, Table] = {}
        self.locked: list[uuid.UUID] = []
        self.create_locks: list[uuid.UUID] = []

    async def add(self, table: Table) -> None:
        self.tables[table.id] = table

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        table = self.tables.get(table_id)
        return table if table is not None and table.tenant_id == tenant_id else None

    async def get_for_update(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        self.locked.append(table_id)
        return await self.get(tenant_id, table_id)

    async def exists_anywhere(self, table_id: uuid.UUID) -> bool:
        return table_id in self.tables

    async def lock_creates(self, tenant_id: uuid.UUID) -> None:
        self.create_locks.append(tenant_id)

    async def get_by_code(self, code: str) -> Table | None:
        return next((table for table in self.tables.values() if table.code == code), None)

    async def get_by_qr_token(self, qr_token: str) -> Table | None:
        return next((table for table in self.tables.values() if table.qr_token == qr_token), None)

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Table | None:
        return next(
            (
                table
                for table in self.tables.values()
                if table.tenant_id == tenant_id and table.name.lower() == name.lower()
            ),
            None,
        )

    async def list(self, tenant_id: uuid.UUID) -> list[Table]:
        tables = [table for table in self.tables.values() if table.tenant_id == tenant_id]
        return sorted(tables, key=lambda table: table.name.lower())

    async def update(self, table: Table) -> None:
        self.tables[table.id] = table


class FakeTableCredentials:
    """Hands out the queued codes first (to force collisions), then sequential ones."""

    def __init__(self, codes: list[str] | None = None) -> None:
        self.codes = list(codes or [])
        self.issued_codes = 0
        self.issued_pins = 0
        self.issued_qr_tokens = 0

    def new_code(self) -> str:
        if self.codes:
            return self.codes.pop(0)
        self.issued_codes += 1
        return f"CODE{self.issued_codes:02d}"

    def new_pin(self) -> str:
        self.issued_pins += 1
        return f"{self.issued_pins:06d}"

    def new_qr_token(self) -> str:
        self.issued_qr_tokens += 1
        return f"qr-token-{self.issued_qr_tokens}"


def _by_position(entity: Category | Item) -> tuple[int, str]:
    return entity.position, entity.name.lower()


class InMemoryCategoryRepository:
    def __init__(self) -> None:
        self.categories: dict[uuid.UUID, Category] = {}
        # Item counts per category, kept by InMemoryItemRepository to mimic the RESTRICT foreign key.
        self.item_counts: dict[uuid.UUID, int] = {}
        self.locked: list[uuid.UUID] = []
        self.order_locks: list[uuid.UUID] = []

    async def add(self, category: Category) -> None:
        self.categories[category.id] = category

    async def get(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        category = self.categories.get(category_id)
        return category if category is not None and category.tenant_id == tenant_id else None

    async def get_for_update(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        self.locked.append(category_id)
        return await self.get(tenant_id, category_id)

    async def exists_anywhere(self, category_id: uuid.UUID) -> bool:
        return category_id in self.categories

    async def lock_order(self, tenant_id: uuid.UUID) -> None:
        self.order_locks.append(tenant_id)

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Category | None:
        return next(
            (c for c in self.categories.values() if c.tenant_id == tenant_id and c.name.lower() == name.lower()),
            None,
        )

    async def next_position(self, tenant_id: uuid.UUID) -> int:
        return max((c.position + 1 for c in self.categories.values() if c.tenant_id == tenant_id), default=0)

    async def update(self, category: Category) -> None:
        self.categories[category.id] = category

    async def delete(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> None:
        if self.item_counts.get(category_id, 0):
            raise CategoryNotEmpty(category_id)
        if (await self.get(tenant_id, category_id)) is not None:
            del self.categories[category_id]

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        for position, category_id in enumerate(ordered_ids):
            category = self.categories[category_id]
            assert category.tenant_id == tenant_id
            self.categories[category_id] = replace(category, position=position)

    # Last on purpose: a method named `list` shadows the builtin in the annotations below it.
    async def list(self, tenant_id: uuid.UUID) -> list[Category]:
        return sorted((c for c in self.categories.values() if c.tenant_id == tenant_id), key=_by_position)


class InMemoryItemRepository:
    def __init__(self, categories: InMemoryCategoryRepository) -> None:
        self.items: dict[uuid.UUID, Item] = {}
        self._categories = categories
        self.locked: list[uuid.UUID] = []
        self.order_locks: list[list[uuid.UUID]] = []

    async def get_for_update(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None:
        self.locked.append(item_id)
        return await self.get(tenant_id, item_id)

    async def exists_anywhere(self, item_id: uuid.UUID) -> bool:
        return item_id in self.items

    async def lock_order(self, tenant_id: uuid.UUID, category_ids: list[uuid.UUID]) -> None:
        self.order_locks.append(sorted(set(category_ids)))

    def _recount(self) -> None:
        counts: dict[uuid.UUID, int] = {}
        for item in self.items.values():
            counts[item.category_id] = counts.get(item.category_id, 0) + 1
        self._categories.item_counts = counts

    async def add(self, item: Item) -> None:
        self.items[item.id] = item
        self._recount()

    async def get(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item | None:
        item = self.items.get(item_id)
        return item if item is not None and item.tenant_id == tenant_id else None

    async def list_in_category(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> list[Item]:
        return [item for item in await self.list(tenant_id) if item.category_id == category_id]

    async def next_position(self, tenant_id: uuid.UUID, category_id: uuid.UUID) -> int:
        return max((item.position + 1 for item in await self.list_in_category(tenant_id, category_id)), default=0)

    async def update(self, item: Item) -> None:
        self.items[item.id] = item
        self._recount()

    async def delete(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
        if (await self.get(tenant_id, item_id)) is not None:
            del self.items[item_id]
        self._recount()

    async def set_positions(self, tenant_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
        for position, item_id in enumerate(ordered_ids):
            item = self.items[item_id]
            assert item.tenant_id == tenant_id
            self.items[item_id] = replace(item, position=position)

    async def list(self, tenant_id: uuid.UUID) -> list[Item]:
        return sorted((i for i in self.items.values() if i.tenant_id == tenant_id), key=_by_position)


class FakeImageStorage:
    """Stands in for Cloudinary: `upload` plays the browser's direct upload."""

    def __init__(self) -> None:
        self.stored: dict[str, StoredImage] = {}
        self.deleted: list[str] = []
        self.fail_deletes = False
        self.fail_deletes_for: set[str] = set()
        self.fail_lookups = False

    def upload(self, public_id: str, image_format: str = "jpg", size: int = 1_000) -> None:
        self.stored[public_id] = StoredImage(public_id=public_id, format=image_format, bytes=size)

    def sign_upload(self, public_id: str, allowed_formats: tuple[str, ...]) -> UploadSignature:
        return UploadSignature(
            upload_url="https://upload.test/image/upload",
            api_key="test-key",
            timestamp=1_700_000_000,
            signature=f"signed:{public_id}",
            public_id=public_id,
            allowed_formats=allowed_formats,
        )

    async def find(self, public_id: str) -> StoredImage | None:
        if self.fail_lookups:
            raise ImageStorageUnavailable("Image storage is not reachable right now. Try again in a moment")
        return self.stored.get(public_id)

    async def delete(self, public_id: str) -> None:
        if self.fail_deletes or public_id in self.fail_deletes_for:
            raise ConnectionError("storage down")
        self.stored.pop(public_id, None)
        self.deleted.append(public_id)

    def url(self, public_id: str, variant: ImageVariant) -> str | None:
        return f"https://images.test/{variant.value}/{public_id}"


@dataclass
class _UploadRecord:
    tenant_id: uuid.UUID
    status: str
    created_at: datetime
    attempts: int = 0
    next_attempt_at: datetime | None = None


class InMemoryImageRegistry:
    """Fake of the media module's image records: implements `ImageRegistry` and `CleanupRepository`."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.clock = clock or FakeClock()
        self.records: dict[str, _UploadRecord] = {}

    def status(self, public_id: str) -> str | None:
        record = self.records.get(public_id)
        return record.status if record is not None else None

    async def register(self, tenant_id: uuid.UUID, public_id: str) -> None:
        self.records[public_id] = _UploadRecord(tenant_id, "pending", self.clock.now())

    async def attach(self, tenant_id: uuid.UUID, public_id: str) -> bool:
        record = self.records.get(public_id)
        if record is None or record.tenant_id != tenant_id or record.status != "pending":
            return False
        record.status = "attached"
        return True

    async def discard(self, tenant_id: uuid.UUID, public_id: str) -> None:
        record = self.records.get(public_id)
        if record is not None and record.tenant_id == tenant_id:
            record.status = "discarded"

    async def reject(self, tenant_id: uuid.UUID, public_id: str) -> None:
        record = self.records.get(public_id)
        if record is not None and record.tenant_id == tenant_id and record.status == "pending":
            record.status = "discarded"

    async def claim_due(self, now: datetime, pending_before: datetime, limit: int) -> list[DueImage]:
        due = [
            (record.next_attempt_at or record.created_at, public_id, record.attempts)
            for public_id, record in self.records.items()
            if (record.status == "discarded" or (record.status == "pending" and record.created_at < pending_before))
            and (record.next_attempt_at is None or record.next_attempt_at <= now)
        ]
        return [DueImage(public_id, attempts) for _, public_id, attempts in sorted(due)][:limit]

    async def forget(self, public_id: str) -> None:
        self.records.pop(public_id, None)

    async def postpone(self, public_id: str, until: datetime) -> None:
        record = self.records[public_id]
        record.attempts += 1
        record.next_attempt_at = until

class FakeCleanupScheduler:
    def __init__(self) -> None:
        self.requests = 0

    async def request_cleanup(self) -> None:
        self.requests += 1


class InMemoryRefreshTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[uuid.UUID, RefreshToken] = {}

    async def add(self, token: RefreshToken) -> None:
        self.tokens[token.id] = token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((token for token in self.tokens.values() if token.token_hash == token_hash), None)

    async def mark_rotated(self, token_id: uuid.UUID, at: datetime) -> bool:
        token = self.tokens[token_id]
        if token.rotated_at is not None or token.revoked_at is not None:
            return False
        self.tokens[token_id] = replace(token, rotated_at=at)
        return True

    async def revoke_family(self, family_id: uuid.UUID, at: datetime) -> None:
        for token_id, token in self.tokens.items():
            if token.family_id == family_id and token.revoked_at is None:
                self.tokens[token_id] = replace(token, revoked_at=at)

    async def revoke_all_for_user(self, tenant_id: uuid.UUID, user_id: uuid.UUID, at: datetime) -> None:
        for token_id, token in self.tokens.items():
            if token.tenant_id == tenant_id and token.user_id == user_id and token.revoked_at is None:
                self.tokens[token_id] = replace(token, revoked_at=at)

    async def revoke_all_for_table(self, tenant_id: uuid.UUID, table_id: uuid.UUID, at: datetime) -> None:
        for token_id, token in self.tokens.items():
            if token.tenant_id == tenant_id and token.table_id == table_id and token.revoked_at is None:
                self.tokens[token_id] = replace(token, revoked_at=at)

    async def delete_expired(self, before: datetime, limit: int) -> int:
        expired = [token_id for token_id, token in self.tokens.items() if token.expires_at < before][:limit]
        for token_id in expired:
            del self.tokens[token_id]
        return len(expired)


class FakeAccessRevocations:
    def __init__(self) -> None:
        self.required: dict[uuid.UUID, int] = {}

    async def require_version(self, subject_id: uuid.UUID, session_version: int) -> None:
        self.required[subject_id] = max(session_version, self.required.get(subject_id, 0))

    async def required_version(self, subject_id: uuid.UUID) -> int | None:
        return self.required.get(subject_id)


class FakeLoginAttemptLimiter:
    def __init__(self, blocked_for: int | None = None) -> None:
        self.blocked_for = blocked_for
        self.acquired: list[tuple[str, str]] = []
        self.succeeded_logins: list[tuple[str, str]] = []

    async def acquire(self, account: str, client: str) -> int | None:
        self.acquired.append((account, client))
        return self.blocked_for

    async def succeeded(self, account: str, client: str) -> None:
        self.succeeded_logins.append((account, client))

class FakeTableGuests:
    """Records which tables had their QR guests ended, and when their access was revoked."""

    def __init__(self) -> None:
        self.ended: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.access_ended = 0

    async def end_all(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        self.ended.append((tenant_id, table_id))

    async def end_access(self) -> None:
        self.access_ended += 1


class NoActiveGuests:
    """Stands in for GetActiveGuest where no QR guest takes part."""

    async def execute(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> None:
        return None
