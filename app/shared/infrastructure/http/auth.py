"""Central authentication and authorization dependencies.

The access token travels only in an httpOnly cookie (JavaScript never sees it). The tenant,
the role and the table always come from that token, never from the request body or URL.
Routes declare who may call them with `require_role(...)`.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status

from app.shared.domain.principal import AccessRevocations, AccessTokenDecoder, InvalidAccessToken, Principal, Role

ACCESS_COOKIE = "access_token"
# Sent to every API route; never to the static frontend.
ACCESS_COOKIE_PATH = "/api"


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_principal(
    request: Request, access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None
) -> Principal:
    if not access_token:
        raise _unauthorized()
    decoder: AccessTokenDecoder = request.app.state.access_tokens
    try:
        principal = decoder.decode(access_token)
    except InvalidAccessToken as error:
        raise _unauthorized() from error

    # Deactivating an account (or resetting its password) ends its sessions right away.
    revocations: AccessRevocations = request.app.state.access_revocations
    revoked_at = await revocations.revoked_since(principal.subject_id)
    if revoked_at is not None and (principal.issued_at is None or principal.issued_at <= revoked_at):
        raise _unauthorized()
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: `Depends(require_role("admin", "waiter"))` returns the principal or 403."""
    allowed = frozenset(Role(role) for role in roles)

    async def dependency(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return principal

    return dependency
