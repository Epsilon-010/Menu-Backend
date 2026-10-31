import uuid

from app.modules.auth.application.revoke_user_sessions import RevokeUserSessions
from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import LoginAttemptLimiter
from app.modules.staff.application.manage_admins import ReplaceOwnPassword, check_new_password
from app.shared.domain.ports import UnitOfWork


class ChangePassword:
    """An admin replaces their own password: every session of the account ends (other devices are signed
    out) and the caller gets a fresh one, all in one transaction.

    Wrong current passwords count like failed logins (per device and account), so this endpoint cannot be
    used to guess the password of a stolen session.
    """

    def __init__(
        self,
        replace_password: ReplaceOwnPassword,
        limiter: LoginAttemptLimiter,
        revoke: RevokeUserSessions,
        sessions: SessionIssuer,
        uow: UnitOfWork,
    ) -> None:
        self._replace_password = replace_password
        self._limiter = limiter
        self._revoke = revoke
        self._sessions = sessions
        self._uow = uow

    async def execute(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, current: str, new: str, client: str
    ) -> AuthSession:
        """`client` is the caller's IP. Raises InvalidUserData before counting anything when the new
        password is not acceptable."""
        check_new_password(current, new)
        attempts_key = f"password:{user_id}"
        retry_after = await self._limiter.acquire(attempts_key, client)
        if retry_after is not None:
            raise TooManyLoginAttempts(retry_after)

        user = await self._replace_password.execute(tenant_id, user_id, current, new)
        await self._limiter.succeeded(attempts_key, client)
        # Old refresh tokens first, then the caller's new one: only this session survives.
        await self._revoke.execute(tenant_id, user_id)
        session = await self._sessions.issue(user)
        await self._uow.commit()
        await self._revoke.end_access(user_id, user.session_version)
        return session
