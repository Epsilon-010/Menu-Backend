"""Admin use cases over the tenant's waiters and cooks.

Every lookup is scoped to the admin's tenant and to staff-member roles: another tenant's users
and admins are reported as not found. There is no hard delete; deactivating is the removal.
"""

import uuid
from dataclasses import replace

from app.modules.staff.domain.errors import StaffMemberNotFound, UsernameNotAvailable
from app.modules.staff.domain.user import (
    SessionRevoker,
    User,
    UserRepository,
    normalize_username,
    validate_password,
)
from app.shared.domain.ports import PasswordHasher, UnitOfWork
from app.shared.domain.principal import Role


async def _get_staff_member(users: UserRepository, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = await users.get(tenant_id, user_id)
    if user is None or not user.is_staff_member:
        raise StaffMemberNotFound(user_id)
    return user


class CreateStaffMember:
    def __init__(self, users: UserRepository, hasher: PasswordHasher, uow: UnitOfWork) -> None:
        self._users = users
        self._hasher = hasher
        self._uow = uow

    async def execute(
        self, tenant_id: uuid.UUID, username: str, full_name: str, role: Role, password: str
    ) -> User:
        validate_password(password)
        # Validate the rest before paying for the hash.
        User.create_staff(tenant_id, username, full_name, role, password_hash="")
        if await self._users.get_by_username(normalize_username(username)) is not None:
            raise UsernameNotAvailable(username)

        member = User.create_staff(tenant_id, username, full_name, role, await self._hasher.hash(password))
        await self._users.add(member)
        await self._uow.commit()
        return member


class ListStaff:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, tenant_id: uuid.UUID) -> list[User]:
        return await self._users.list_staff(tenant_id)


class UpdateStaffMember:
    """Renames, changes the role or (de)activates. Deactivating or changing the role ends every
    session of the member right away, since their tokens carry the old role."""

    def __init__(self, users: UserRepository, sessions: SessionRevoker, uow: UnitOfWork) -> None:
        self._users = users
        self._sessions = sessions
        self._uow = uow

    async def execute(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        full_name: str | None = None,
        role: Role | None = None,
        is_active: bool | None = None,
    ) -> User:
        member = await _get_staff_member(self._users, tenant_id, user_id)
        updated = member.with_changes(full_name=full_name, role=role, is_active=is_active)

        await self._users.update(updated)
        deactivated = member.is_active and not updated.is_active
        if deactivated or updated.role != member.role:
            await self._sessions.revoke_all(tenant_id, user_id)
        await self._uow.commit()
        return updated


class ResetStaffPassword:
    """Sets a new password chosen by the admin and ends every session of the member."""

    def __init__(
        self, users: UserRepository, hasher: PasswordHasher, sessions: SessionRevoker, uow: UnitOfWork
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._sessions = sessions
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID, password: str) -> None:
        validate_password(password)
        member = await _get_staff_member(self._users, tenant_id, user_id)

        await self._users.update(replace(member, password_hash=await self._hasher.hash(password)))
        await self._sessions.revoke_all(tenant_id, user_id)
        await self._uow.commit()
