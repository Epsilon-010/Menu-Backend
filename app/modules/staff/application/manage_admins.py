"""Admin use cases over the other admins of the tenant, and an admin's own password.

Every lookup is scoped to the caller's tenant and to the admin role: another tenant's users and
waiters or cooks are reported as not found. There is no hard delete; deactivating is the removal.
A new admin gets a temporary password (shown once) and must replace it on first sign-in.
"""

import uuid
from dataclasses import dataclass

from app.modules.staff.domain.errors import (
    AdminAlreadyCreated,
    AdminNotFound,
    CannotDeactivateSelf,
    EmailAlreadyInUse,
    NotAnActiveAdmin,
    StaffIdTaken,
    WrongCurrentPassword,
)
from app.modules.staff.domain.user import (
    SessionRevoker,
    StaffCredentials,
    User,
    UserRepository,
    validate_admin,
    validate_new_password,
)
from app.shared.domain.ports import PasswordHasher, UnitOfWork


@dataclass(frozen=True)
class AdminWithTemporaryPassword:
    """The plain temporary password only exists in this result: it is shown once and stored as a hash."""

    admin: User
    temporary_password: str


class CreateAdmin:
    def __init__(
        self, users: UserRepository, credentials: StaffCredentials, hasher: PasswordHasher, uow: UnitOfWork
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._uow = uow

    async def execute(
        self, tenant_id: uuid.UUID, full_name: str, email: str, user_id: uuid.UUID | None = None
    ) -> AdminWithTemporaryPassword:
        """`user_id` makes the create idempotent: a repeat never makes a second admin. It cannot return
        the password again (only its hash exists), so it raises AdminAlreadyCreated instead."""
        full_name, email = validate_admin(full_name, email)
        # Taken before the replay check, so a concurrent replay waits and then finds the first one.
        await self._users.lock_creates(tenant_id)
        if user_id is not None:
            existing = await self._users.get(tenant_id, user_id)
            if existing is not None and existing.is_admin:
                raise AdminAlreadyCreated(user_id)
            if existing is not None or await self._users.exists_anywhere(user_id):
                raise StaffIdTaken(user_id)
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyInUse(email)

        temporary_password = self._credentials.new_temporary_password()
        admin = User.create_admin(tenant_id, email, full_name, await self._hasher.hash(temporary_password), user_id)
        await self._users.add(admin)
        await self._uow.commit()
        return AdminWithTemporaryPassword(admin=admin, temporary_password=temporary_password)


class ListAdmins:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, tenant_id: uuid.UUID) -> list[User]:
        return await self._users.list_admins(tenant_id)


class UpdateAdmin:
    """Renames or (de)activates another admin. Deactivating ends every session of that admin right away.

    Nobody deactivates their own account, and changes are serialized per tenant with the caller checked
    to still be an active admin: so the business always keeps at least one active admin.
    """

    def __init__(self, users: UserRepository, sessions: SessionRevoker, uow: UnitOfWork) -> None:
        self._users = users
        self._sessions = sessions
        self._uow = uow

    async def execute(
        self,
        tenant_id: uuid.UUID,
        caller_id: uuid.UUID,
        user_id: uuid.UUID,
        full_name: str | None = None,
        is_active: bool | None = None,
    ) -> User:
        # Lock order: the tenant's admin lock before any row lock, like every other ordered lock.
        await self._users.lock_admin_changes(tenant_id)
        caller = await self._users.get_for_update(tenant_id, caller_id)
        if caller is None or not caller.is_admin or not caller.is_active:
            raise NotAnActiveAdmin(caller_id)
        admin = await self._users.get_for_update(tenant_id, user_id)
        if admin is None or not admin.is_admin:
            raise AdminNotFound(user_id)
        if is_active is False and admin.id == caller_id:
            raise CannotDeactivateSelf(user_id)

        updated = admin.with_changes(full_name=full_name, is_active=is_active)
        deactivated = admin.is_active and not updated.is_active
        if deactivated:
            updated = updated.with_sessions_ended()

        await self._users.update(updated)
        if deactivated:
            await self._sessions.revoke_all(tenant_id, user_id)
        await self._uow.commit()
        if deactivated:
            await self._sessions.end_access(user_id, updated.session_version)
        return updated


class ReplaceOwnPassword:
    """An admin replaces their own password (temporary or not) after proving the current one.

    It does not commit and does not end the sessions: the auth module owns that transaction, since it
    also ends every session and signs the caller back in.
    """

    def __init__(self, users: UserRepository, hasher: PasswordHasher) -> None:
        self._users = users
        self._hasher = hasher

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID, current: str, new: str) -> User:
        user = await self._users.get_for_update(tenant_id, user_id)
        if user is None or not user.is_admin or not user.is_active:
            raise NotAnActiveAdmin(user_id)
        if not await self._hasher.verify(user.password_hash, current):
            raise WrongCurrentPassword()

        updated = user.with_password(await self._hasher.hash(new))
        await self._users.update(updated)
        return updated


def check_new_password(current: str, new: str) -> None:
    """Validates the new password before anything is counted or verified."""
    validate_new_password(current, new)
