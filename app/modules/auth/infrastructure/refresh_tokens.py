import hashlib
import secrets
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.refresh_token import RefreshToken
from app.modules.auth.infrastructure.models import RefreshTokenModel


class OpaqueRefreshTokenCodec:
    """256-bit random values; a fast SHA-256 is enough to store tokens with that much entropy."""

    def generate(self) -> str:
        return secrets.token_urlsafe(32)

    def hash(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()


def _to_entity(model: RefreshTokenModel) -> RefreshToken:
    return RefreshToken(
        id=model.id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        table_id=model.table_id,
        family_id=model.family_id,
        token_hash=model.token_hash,
        created_at=model.created_at,
        expires_at=model.expires_at,
        rotated_at=model.rotated_at,
        revoked_at=model.revoked_at,
    )


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: RefreshToken) -> None:
        self._session.add(
            RefreshTokenModel(
                id=token.id,
                tenant_id=token.tenant_id,
                user_id=token.user_id,
                table_id=token.table_id,
                family_id=token.family_id,
                token_hash=token.token_hash,
                created_at=token.created_at,
                expires_at=token.expires_at,
            )
        )
        await self._session.flush()

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        model = await self._session.scalar(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash).with_for_update()
        )
        return _to_entity(model) if model is not None else None

    async def mark_rotated(self, token_id: uuid.UUID, at: datetime) -> bool:
        result = await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.id == token_id,
                RefreshTokenModel.rotated_at.is_(None),
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(rotated_at=at)
        )
        return result.rowcount == 1  # type: ignore[attr-defined]

    async def revoke_family(self, family_id: uuid.UUID, at: datetime) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.family_id == family_id, RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def revoke_all_for_user(self, tenant_id: uuid.UUID, user_id: uuid.UUID, at: datetime) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.tenant_id == tenant_id,
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=at)
        )

    async def revoke_all_for_table(self, tenant_id: uuid.UUID, table_id: uuid.UUID, at: datetime) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.tenant_id == tenant_id,
                RefreshTokenModel.table_id == table_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=at)
        )