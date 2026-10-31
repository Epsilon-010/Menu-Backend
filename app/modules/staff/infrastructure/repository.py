import secrets
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff.domain.errors import EmailAlreadyInUse, StaffCodeTaken, StaffIdTaken, StaffMemberNotFound
from app.modules.staff.domain.user import (
    STAFF_CODE_ALPHABET,
    STAFF_CODE_LENGTH,
    STAFF_MEMBER_ROLES,
    STAFF_PIN_LENGTH,
    TEMPORARY_PASSWORD_LENGTH,
    User,
)
from app.modules.staff.infrastructure.models import UserModel
from app.shared.domain.principal import Role
from app.shared.infrastructure.database import affected_rows, advisory_xact_lock, violated_unique_constraint


class RandomStaffCredentials:
    """Staff codes and PINs from the OS CSPRNG."""

    def new_code(self) -> str:
        return "".join(secrets.choice(STAFF_CODE_ALPHABET) for _ in range(STAFF_CODE_LENGTH))

    def new_pin(self) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(STAFF_PIN_LENGTH))

    def new_temporary_password(self) -> str:
        # Same unambiguous alphabet as the codes: it is read off a screen and typed once.
        return "".join(secrets.choice(STAFF_CODE_ALPHABET) for _ in range(TEMPORARY_PASSWORD_LENGTH))


def _to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        tenant_id=model.tenant_id,
        email=model.email,
        username=model.username,
        full_name=model.full_name,
        role=Role(model.role),
        password_hash=model.password_hash,
        is_active=model.is_active,
        session_version=model.session_version,
        must_change_password=model.must_change_password,
    )


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        model = UserModel(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role.value,
            password_hash=user.password_hash,
            is_active=user.is_active,
            session_version=user.session_version,
            must_change_password=user.must_change_password,
        )
        try:
            # A savepoint: when the random staff code collides, only this insert rolls back and the use
            # case can retry with a new code in the same transaction.
            async with self._session.begin_nested():
                self._session.add(model)
        except IntegrityError as error:
            # Another request took the login after the use case checked it.
            constraint = violated_unique_constraint(error)
            if constraint == "pk_users":
                # A concurrent replay of the same create, or a clash with another tenant's id.
                raise StaffIdTaken(user.id) from error
            if constraint == "uq_users_username":
                raise StaffCodeTaken(user.username) from error
            if constraint == "uq_users_email":
                raise EmailAlreadyInUse(user.email) from error
            raise

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        model = await self._session.scalar(
            select(UserModel).where(UserModel.tenant_id == tenant_id, UserModel.id == user_id)
        )
        return _to_entity(model) if model is not None else None

    async def get_for_update(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        model = await self._session.scalar(
            select(UserModel).where(UserModel.tenant_id == tenant_id, UserModel.id == user_id).with_for_update()
        )
        return _to_entity(model) if model is not None else None

    async def exists_anywhere(self, user_id: uuid.UUID) -> bool:
        return await self._session.scalar(select(UserModel.id).where(UserModel.id == user_id)) is not None

    async def lock_creates(self, tenant_id: uuid.UUID) -> None:
        await advisory_xact_lock(self._session, f"staff-create:{tenant_id}")

    async def lock_admin_changes(self, tenant_id: uuid.UUID) -> None:
        await advisory_xact_lock(self._session, f"admin-changes:{tenant_id}")

    async def lock_email(self, email: str) -> None:
        await advisory_xact_lock(self._session, f"signup-email:{email}")

    async def get_by_email(self, email: str) -> User | None:
        model = await self._session.scalar(select(UserModel).where(UserModel.email == email))
        return _to_entity(model) if model is not None else None

    async def get_by_username(self, username: str) -> User | None:
        model = await self._session.scalar(select(UserModel).where(UserModel.username == username))
        return _to_entity(model) if model is not None else None

    async def list_staff(self, tenant_id: uuid.UUID) -> list[User]:
        models = await self._session.scalars(
            select(UserModel)
            .where(UserModel.tenant_id == tenant_id, UserModel.role.in_([role.value for role in STAFF_MEMBER_ROLES]))
            .order_by(func.lower(UserModel.full_name), UserModel.username)
        )
        return [_to_entity(model) for model in models]

    async def list_admins(self, tenant_id: uuid.UUID) -> list[User]:
        models = await self._session.scalars(
            select(UserModel)
            .where(UserModel.tenant_id == tenant_id, UserModel.role == Role.ADMIN.value)
            .order_by(func.lower(UserModel.full_name), UserModel.email)
        )
        return [_to_entity(model) for model in models]

    async def update(self, user: User) -> None:
        # Tenant-scoped like every other query; email and username never change.
        result = await self._session.execute(
            update(UserModel)
            .where(UserModel.tenant_id == user.tenant_id, UserModel.id == user.id)
            .values(
                full_name=user.full_name,
                role=user.role.value,
                password_hash=user.password_hash,
                is_active=user.is_active,
                must_change_password=user.must_change_password,
                # Never lowered, even by a stale copy: that would revive the sessions it ended.
                session_version=func.greatest(UserModel.session_version, user.session_version),
            )
        )
        if not affected_rows(result):
            raise StaffMemberNotFound(user.id)
