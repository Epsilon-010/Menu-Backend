"""Admin use cases over the tenant's waiters and cooks.

Every lookup is scoped to the admin's tenant and to staff-member roles: another tenant's users
and admins are reported as not found. There is no hard delete; deactivating is the removal.
Members sign in with a generated code (unique across the platform, so names may repeat) and a PIN.
"""

import uuid
from dataclasses import dataclass, replace

from app.modules.staff.domain.errors import StaffAlreadyCreated, StaffCodeTaken, StaffIdTaken, StaffMemberNotFound
from app.modules.staff.domain.user import (
    SessionRevoker,
    StaffCredentials,
    User,
    UserRepository,
    normalize_username,
    validate_staff_member,
)
from app.shared.domain.ports import PasswordHasher, UnitOfWork
from app.shared.domain.principal import Role

# Codes come from ~887 million combinations; a collision is rare, several in a row are a bug.
_MAX_CODE_ATTEMPTS = 10


@dataclass(frozen=True)
class StaffMemberWithPin:
    """The plain PIN only exists in this result: it is shown once and stored as a hash."""

    member: User
    pin: str


async def _get_staff_member(users: UserRepository, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    # Every caller rewrites the member: lock the row so concurrent edits never overwrite each other.
    user = await users.get_for_update(tenant_id, user_id)
    if user is None or not user.is_staff_member:
        raise StaffMemberNotFound(user_id)
    return user


class CreateStaffMember:
    def __init__(
        self, users: UserRepository, credentials: StaffCredentials, hasher: PasswordHasher, uow: UnitOfWork
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._uow = uow

    async def execute(
        self, tenant_id: uuid.UUID, full_name: str, role: Role, user_id: uuid.UUID | None = None
    ) -> StaffMemberWithPin:
        """`user_id` makes the create idempotent: a repeat never makes a second member. It cannot return
        the PIN again (only its hash exists), so it raises StaffAlreadyCreated instead."""
        full_name, role = validate_staff_member(full_name, role)
        # Taken before the replay check, so a concurrent replay waits and then finds the first one.
        await self._users.lock_creates(tenant_id)
        if user_id is not None:
            existing = await self._users.get(tenant_id, user_id)
            if existing is not None and existing.is_staff_member:
                raise StaffAlreadyCreated(user_id)
            if existing is not None or await self._users.exists_anywhere(user_id):
                raise StaffIdTaken(user_id)

        pin = self._credentials.new_pin()
        pin_hash = await self._hasher.hash(pin)
        for _ in range(_MAX_CODE_ATTEMPTS):
            member = User.create_staff(tenant_id, await self._unused_code(), full_name, role, pin_hash, user_id)
            try:
                await self._users.add(member)
            except StaffCodeTaken:
                # A concurrent create took this code after our check: draw another one.
                continue
            await self._uow.commit()
            return StaffMemberWithPin(member=member, pin=pin)
        raise RuntimeError("Could not insert a staff member with an unused code")

    async def _unused_code(self) -> str:
        for _ in range(_MAX_CODE_ATTEMPTS):
            code = self._credentials.new_code()
            if await self._users.get_by_username(normalize_username(code)) is None:
                return code
        raise RuntimeError("Could not generate an unused staff code")


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
        deactivated = member.is_active and not updated.is_active
        ends_sessions = deactivated or updated.role != member.role
        if ends_sessions:
            updated = updated.with_sessions_ended()

        await self._users.update(updated)
        if ends_sessions:
            await self._sessions.revoke_all(tenant_id, user_id)
        await self._uow.commit()
        if ends_sessions:
            await self._sessions.end_access(user_id, updated.session_version)
        return updated


class RegenerateStaffPin:
    """Issues a new PIN (the code stays) and ends every session of the member."""

    def __init__(
        self,
        users: UserRepository,
        credentials: StaffCredentials,
        hasher: PasswordHasher,
        sessions: SessionRevoker,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._sessions = sessions
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> StaffMemberWithPin:
        member = await _get_staff_member(self._users, tenant_id, user_id)
        pin = self._credentials.new_pin()
        updated = replace(member, password_hash=await self._hasher.hash(pin)).with_sessions_ended()

        await self._users.update(updated)
        await self._sessions.revoke_all(tenant_id, user_id)
        await self._uow.commit()
        await self._sessions.end_access(user_id, updated.session_version)
        return StaffMemberWithPin(member=updated, pin=pin)
