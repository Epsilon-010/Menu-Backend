"""What other modules use to end sessions right away, without knowing how auth stores them."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.revoke_user_sessions import RevokeTableSessions, RevokeUserSessions
from app.modules.auth.infrastructure.refresh_tokens import SqlAlchemyRefreshTokenRepository
from app.shared.infrastructure.security import SystemClock


def revoke_user_sessions(request: Request, session: AsyncSession) -> RevokeUserSessions:
    """Runs in the caller's transaction (`session`); the caller commits."""
    return RevokeUserSessions(
        SqlAlchemyRefreshTokenRepository(session), request.app.state.access_revocations, SystemClock()
    )


def revoke_table_sessions(request: Request, session: AsyncSession) -> RevokeTableSessions:
    """Runs in the caller's transaction (`session`); the caller commits."""
    return RevokeTableSessions(
        SqlAlchemyRefreshTokenRepository(session), request.app.state.access_revocations, SystemClock()
    )
