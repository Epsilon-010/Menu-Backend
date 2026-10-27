import uuid

from app.modules.auth.domain.refresh_token import RefreshTokenRepository
from app.shared.domain.ports import Clock
from app.shared.domain.principal import AccessRevocations


class RevokeUserSessions:
    """Ends every session of a user right away: all refresh families and the live access tokens.

    It does not commit: the calling use case (deactivating a user, resetting a password...) owns
    the transaction. The access marker is written before that commit; if the commit then fails,
    the user only has to sign in again.
    """

    def __init__(
        self, refresh_tokens: RefreshTokenRepository, access_revocations: AccessRevocations, clock: Clock
    ) -> None:
        self._refresh_tokens = refresh_tokens
        self._access_revocations = access_revocations
        self._clock = clock

    async def execute(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        now = self._clock.now()
        await self._refresh_tokens.revoke_all_for_user(tenant_id, user_id, now)
        await self._access_revocations.revoke(user_id, now)


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
        now = self._clock.now()
        await self._refresh_tokens.revoke_all_for_table(tenant_id, table_id, now)
        await self._access_revocations.revoke(table_id, now)
