import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff.domain.user import STAFF_MEMBER_ROLES, User
from app.modules.staff.infrastructure.models import UserModel
from app.shared.domain.principal import Role


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
    )


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                id=user.id,
                tenant_id=user.tenant_id,
                email=user.email,
                username=user.username,
                full_name=user.full_name,
                role=user.role.value,
                password_hash=user.password_hash,
                is_active=user.is_active,
            )
        )
        await self._session.flush()

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        model = await self._session.scalar(
            select(UserModel).where(UserModel.tenant_id == tenant_id, UserModel.id == user_id)
        )
        return _to_entity(model) if model is not None else None

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

    async def update(self, user: User) -> None:
        # Tenant-scoped like every other query; email and username never change.
        await self._session.execute(
            update(UserModel)
            .where(UserModel.tenant_id == user.tenant_id, UserModel.id == user.id)
            .values(
                full_name=user.full_name,
                role=user.role.value,
                password_hash=user.password_hash,
                is_active=user.is_active,
            )
        )
