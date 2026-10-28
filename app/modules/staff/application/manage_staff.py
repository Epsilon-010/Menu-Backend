"""Admin use cases over the tenant's waiters and cooks.

Every lookup is scoped to the admin's tenant and to staff-member roles: another tenant's users
and admins are reported as not found. There is no hard delete; deactivating is the removal.
"""

import uuid
from dataclasses import replace

from app.modules.staff.domain.errors import StaffIdTaken, StaffMemberNotFound, UsernameNotAvailable
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
    # Every caller rewrites the member: lock the row so concurrent edits never overwrite each other.
    user = await users.get_for_update(tenant_id, user_id)
    if user is None or not user.is_staff_member:
        raise StaffMemberNotFound(user_id)
    return user


class CreateStaffMember:
    def __init__(self, users: UserRepository, hasher: PasswordHasher, uow: UnitOfWork) -> None:
        self._users = users
        self._hasher = hasher
        self._uow = uow

    async def execute(
        self,
        tenant_id: uuid.UUID,
        username: str,
        full_name: str,
        role: Role,
        password: str,
        user_id: uuid.UUID | None = None,
    ) -> User:
        """`user_id` makes the create idempotent: repeating it returns the member already created."""
        validate_password(password)
        # Validate the rest before paying for the hash.
        draft = User.create_staff(tenant_id, username, full_name, role, password_hash="")
        # Taken before the replay check, so a concurrent replay waits and then finds the first one.
        await self._users.lock_creates(tenant_id)
        if user_id is not None:
            existing = await self._users.get(tenant_id, user_id)
            if existing is not None:
                same = (existing.username, existing.full_name, existing.role) == (
                    draft.username,
                    draft.full_name,
                    draft.role,
                )
                # A replay is the same request: the password too, or a new one would be dropped silently.
                if not (
                    existing.is_staff_member
                    and same
                    and await self._hasher.verify(existing.password_hash, password)
                ):
                    raise StaffIdTaken(user_id)
                return existing
            if await self._users.exists_anywhere(user_id):
                raise StaffIdTaken(user_id)
        if await self._users.get_by_username(normalize_username(username)) is not None:
            raise UsernameNotAvailable(username)

        member = User.create_staff(tenant_id, username, full_name, role, await self._hasher.hash(password), user_id)
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
