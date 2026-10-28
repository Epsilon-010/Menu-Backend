from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import InvalidCredentials, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import LoginAttemptLimiter
from app.modules.tables.application.find_table import FindTableByCode
from app.modules.tables.domain.table import normalize_table_code
from app.shared.domain.ports import PasswordHasher, UnitOfWork


class TableLogin:
    """Signs a tablet in as its table with the table code and PIN; the tenant comes from the table."""

    def __init__(
        self,
        find_table: FindTableByCode,
        hasher: PasswordHasher,
        limiter: LoginAttemptLimiter,
        sessions: SessionIssuer,
        uow: UnitOfWork,
    ) -> None:
        self._find_table = find_table
        self._hasher = hasher
        self._limiter = limiter
        self._sessions = sessions
        self._uow = uow

    async def execute(self, code: str, pin: str, client: str) -> AuthSession:
        """`client` is the caller's IP: failures only lock that device out of the table."""
        code = normalize_table_code(code)
        # Staff logins count under "staff:<login>", so no typed login ever shares this table's counter.
        account = f"table:{code}"
        retry_after = await self._limiter.acquire(account, client)
        if retry_after is not None:
            raise TooManyLoginAttempts(retry_after)

        table = await self._find_table.execute(code)
        if table is None:
            await self._hasher.verify_dummy(pin)
        if table is None or not await self._hasher.verify(table.pin_hash, pin) or not table.is_active:
            raise InvalidCredentials()

        await self._limiter.succeeded(account, client)
        session = await self._sessions.issue_for_table(table)
        await self._uow.commit()
        return session
