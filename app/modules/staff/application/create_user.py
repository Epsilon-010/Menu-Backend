import uuid

from app.modules.staff.domain.errors import EmailAlreadyInUse
from app.modules.staff.domain.user import User, UserRepository, normalize_email, validate_password
from app.shared.domain.ports import PasswordHasher, UnitOfWork
from app.shared.domain.principal import Role


class CreateUser:
    def __init__(self, users: UserRepository, hasher: PasswordHasher, uow: UnitOfWork) -> None:
        self._users = users
        self._hasher = hasher
        self._uow = uow

    async def execute(self, tenant_id: uuid.UUID, email: str, full_name: str, role: Role, password: str) -> User:
        validate_password(password)
        # Validate the rest before paying for the hash.
        User.create(tenant_id, email, full_name, role, password_hash="")
        if await self._users.get_by_email(normalize_email(email)) is not None:
            raise EmailAlreadyInUse(email)

        user = User.create(tenant_id, email, full_name, role, self._hasher.hash(password))
        await self._users.add(user)
        await self._uow.commit()
        return user
