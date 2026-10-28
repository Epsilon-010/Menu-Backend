from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import InvalidCredentials, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import LoginAttemptLimiter
from app.modules.staff.application.find_user import FindUserByLogin
from app.modules.staff.domain.user import normalize_username
from app.shared.domain.ports import PasswordHasher, UnitOfWork


class Login:
    """Signs in with the admin's email or a staff member's username; the tenant comes from the account."""

    def __init__(
        self,
        find_user: FindUserByLogin,
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

    async def execute(self, login: str, password: str, client: str) -> AuthSession:
        """`client` is the caller's IP: failures only lock that device out of the account."""
        # Emails and usernames normalize the same way (trimmed, lowercased).
        account = normalize_username(login)
        # Namespaced like the table login ("table:<code>"), so no typed login can ever share a counter
        # with a table and lock its tablet out.
        attempts_key = f"staff:{account}"
        # Counted before checking the password, so parallel requests cannot exceed the limit.
        retry_after = await self._limiter.acquire(attempts_key, client)
        if retry_after is not None:
            raise TooManyLoginAttempts(retry_after)

        user = await self._find_user.execute(account)
        if user is None:
            await self._hasher.verify_dummy(password)
        if user is None or not await self._hasher.verify(user.password_hash, password) or not user.is_active:
            raise InvalidCredentials()

        await self._limiter.succeeded(attempts_key, client)
        session = await self._sessions.issue(user)
        await self._uow.commit()
        return session
