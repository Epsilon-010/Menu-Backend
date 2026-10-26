from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import InvalidCredentials, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import LoginAttemptLimiter
from app.modules.staff.application.find_user import FindUserByEmail
from app.modules.staff.domain.user import normalize_email
from app.shared.domain.ports import PasswordHasher, UnitOfWork


class Login:
    def __init__(
        self,
        find_user: FindUserByEmail,
        hasher: PasswordHasher,
        limiter: LoginAttemptLimiter,
        sessions: SessionIssuer,
        uow: UnitOfWork,
    ) -> None:
        self._find_user = find_user
        self._hasher = hasher
        self._limiter = limiter
        self._sessions = sessions
        self._uow = uow

    async def execute(self, email: str, password: str, client_ip: str) -> AuthSession:
        account = normalize_email(email)
        retry_after = await self._limiter.retry_after(client_ip, account)
        if retry_after is not None:
            raise TooManyLoginAttempts(retry_after)

        user = await self._find_user.execute(account)
        if user is None:
            self._hasher.verify_dummy(password)
        if user is None or not self._hasher.verify(user.password_hash, password) or not user.is_active:
            await self._limiter.record_failure(client_ip, account)
            raise InvalidCredentials()

        await self._limiter.reset(account)
        session = await self._sessions.issue(user)
        await self._uow.commit()
        return session
