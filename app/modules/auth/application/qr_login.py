from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import InvalidCredentials, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import LoginAttemptLimiter
from app.modules.orders.application.guests import JoinTable
from app.modules.orders.domain.errors import QrNotValid, TableFull
from app.modules.tables.application.find_table import FindTableByQrToken
from app.shared.domain.ports import UnitOfWork

_MAX_QR_TOKEN_LENGTH = 64


class QrLogin:
    """Signs a guest in as the table whose QR they scanned, opening the table (a new visit) if nobody is there.

    The guest's sessions are bound to that visit's bill, so paying or closing it signs every one of them out:
    a phone left open from a paid visit never reaches the next one, even after a new scan opened it.
    """

    def __init__(
        self,
        find_table: FindTableByQrToken,
        join_table: JoinTable,
        limiter: LoginAttemptLimiter,
        sessions: SessionIssuer,
        uow: UnitOfWork,
    ) -> None:
        self._find_table = find_table
        self._join_table = join_table
        self._limiter = limiter
        self._sessions = sessions
        self._uow = uow

    async def execute(self, qr_token: str, name: str | None, client: str) -> AuthSession:
        """Raises InvalidCredentials for an unknown, old or inactive table's QR, TableFull past the guest cap."""
        qr_token = qr_token.strip()[:_MAX_QR_TOKEN_LENGTH]
        # Namespaced like the other logins ("staff:", "table:"), so no other login shares this counter.
        account = f"qr:{qr_token}"
        retry_after = await self._limiter.acquire(account, client)
        if retry_after is not None:
            raise TooManyLoginAttempts(retry_after)

        table = await self._find_table.execute(qr_token) if qr_token else None
        if table is None or not table.is_active:
            raise InvalidCredentials()
        try:
            joined = await self._join_table.execute(table.tenant_id, table.id, qr_token, name)
        except QrNotValid as error:
            raise InvalidCredentials() from error
        except TableFull:
            # A real QR at a full table is no guess: never count it, so nobody is locked out once a seat frees.
            await self._limiter.succeeded(account, client)
            raise

        await self._limiter.succeeded(account, client)
        session = await self._sessions.issue_for_guest(joined.guest)
        await self._uow.commit()
        await self._join_table.announce(joined)
        return session
