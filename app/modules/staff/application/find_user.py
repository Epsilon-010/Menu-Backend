import uuid

from app.modules.staff.domain.user import User, UserRepository, normalize_email


class FindUserByEmail:
    """Platform-wide lookup used only by login, before any tenant is known."""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, email: str) -> User | None:
        return await self._users.get_by_email(normalize_email(email))


class GetUser:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        return await self._users.get(tenant_id, user_id)
