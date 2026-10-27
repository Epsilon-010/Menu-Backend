"""Central authentication and authorization dependencies.

The tenant, the role and the table always come from the access token, never from the request
body or URL. Routes declare who may call them with `require_role(...)`.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.shared.domain.principal import AccessTokenDecoder, InvalidAccessToken, Principal, Role

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    if credentials is None:
        raise _unauthorized()
    decoder: AccessTokenDecoder = request.app.state.access_tokens
    try:
        return decoder.decode(credentials.credentials)
    except InvalidAccessToken as error:
        raise _unauthorized() from error


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: `Depends(require_role("admin", "waiter"))` returns the principal or 403."""
    allowed = frozenset(Role(role) for role in roles)

    async def dependency(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return principal

    return dependency
