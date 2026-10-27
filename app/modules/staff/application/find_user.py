import uuid

from app.modules.staff.domain.user import User, UserRepository, is_email_login, normalize_email, normalize_username


class FindUserByLogin:
    """Platform-wide lookup used only by login, before any tenant is known.

    The login is the admin's email or a staff member's username.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, login: str) -> User | None:
        if is_email_login(login):
            return await self._users.get_by_email(normalize_email(login))
        return await self._users.get_by_username(normalize_username(login))


class GetUser:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        return await self._users.get(tenant_id, user_id)
