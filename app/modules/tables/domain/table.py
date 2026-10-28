import uuid
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.modules.tables.domain.errors import InvalidTableData

MAX_TABLE_NAME_LENGTH = 60
# Uppercase letters and digits without the look-alikes 0/O, 1/I/L: the code is typed on a tablet.
TABLE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TABLE_CODE_LENGTH = 6
PIN_LENGTH = 6


def normalize_table_code(code: str) -> str:
    """Table codes are unique across the platform: the device login receives no tenant."""
    return code.strip().upper()


def validate_table_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_TABLE_NAME_LENGTH:
        raise InvalidTableData(f"Table name must have 1 to {MAX_TABLE_NAME_LENGTH} characters")
    return name


@dataclass(frozen=True)
class Table:
    """A table of a tenant; its tablet signs in with the table code and a PIN.

    The code is generated once and never changes; the PIN is only stored as a hash.
    """

    tenant_id: uuid.UUID
    name: str
    code: str
    pin_hash: str
    is_active: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def create(
        cls, tenant_id: uuid.UUID, name: str, code: str, pin_hash: str, table_id: uuid.UUID | None = None
    ) -> "Table":
        """`table_id` comes from the client to make the create idempotent; None generates one."""
        return cls(
            tenant_id=tenant_id,
            name=validate_table_name(name),
            code=normalize_table_code(code),
            pin_hash=pin_hash,
            id=table_id or uuid.uuid4(),
        )

    def with_changes(self, name: str | None = None, is_active: bool | None = None) -> "Table":
        return replace(
            self,
            name=self.name if name is None else validate_table_name(name),
            is_active=self.is_active if is_active is None else is_active,
        )


class TableRepository(Protocol):
    async def add(self, table: Table) -> None: ...

    async def get(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None: ...

    async def get_for_update(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table | None:
        """Same as `get`, locking the row until the transaction ends: for every read-then-write."""
        ...

    async def exists_anywhere(self, table_id: uuid.UUID) -> bool:
        """Whether the id is taken in any tenant (to answer a clash without revealing that row)."""
        ...

    async def lock_creates(self, tenant_id: uuid.UUID) -> None:
        """Serializes the tenant's table creates until the transaction ends, so a concurrent replay
        of a create waits for the first one and then finds it."""
        ...

    async def get_by_code(self, code: str) -> Table | None:
        """Platform-wide lookup, used only by the device login before any tenant is known."""
        ...

    async def get_by_name(self, tenant_id: uuid.UUID, name: str) -> Table | None:
        """Case-insensitive match inside the tenant."""
        ...

    async def list(self, tenant_id: uuid.UUID) -> list[Table]:
        """Tables of the tenant ordered by name."""
        ...

    async def update(self, table: Table) -> None: ...


class TableCredentials(Protocol):
    """Port: generates random table codes and PINs."""

    def new_code(self) -> str: ...

    def new_pin(self) -> str: ...


class SessionRevoker(Protocol):
    """Port: ends every session of a table right away (implemented by the auth module).

    It does not commit: the calling use case owns the transaction.
    """

    async def revoke_all(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None: ...
