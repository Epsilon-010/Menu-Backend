import uuid

from app.modules.auth.domain.refresh_token import RefreshTokenRepository
from app.shared.domain.ports import Clock
from app.shared.domain.principal import AccessRevocations


class RevokeUserSessions:
    """Ends every session of a user right away: all refresh families and the live access tokens.

    `execute` revokes the refresh tokens inside the calling use case's transaction (deactivating a
    user, resetting a password...), which commits. `end_access` runs after that commit with the new
    session version, so access tokens of an older version are rejected; if it fails (Redis down),
    they still expire within one access-token lifetime.
    """

    def __init__(
        self, refresh_tokens: RefreshTokenRepository, access_revocations: AccessRevocations, clock: Clock
    ) -> None:
        self._refresh_tokens = refresh_tokens
        self._access_revocations = access_revocations
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._refresh_tokens.revoke_all_for_user(tenant_id, user_id, self._clock.now())

    async def end_access(self, user_id: uuid.UUID, session_version: int) -> None:
        await self._access_revocations.require_version(user_id, session_version)


class RevokeTableSessions:
    """Ends every session of a table's device right away (deactivating it, regenerating its PIN).

    Same transaction rules as `RevokeUserSessions`; the table id is the access-token subject.
    """

    def __init__(
        self, refresh_tokens: RefreshTokenRepository, access_revocations: AccessRevocations, clock: Clock
    ) -> None:
        self._refresh_tokens = refresh_tokens
        self._access_revocations = access_revocations
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID, table_id: uuid.UUID) -> None:
        await self._refresh_tokens.revoke_all_for_table(tenant_id, table_id, self._clock.now())

    async def end_access(self, table_id: uuid.UUID, session_version: int) -> None:
        await self._access_revocations.require_version(table_id, session_version)
