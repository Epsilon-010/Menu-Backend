import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.get_current_account import GetCurrentAccount
from app.modules.auth.application.login import Login
from app.modules.auth.application.logout import Logout
from app.modules.auth.application.refresh_session import RefreshSession
from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.domain.errors import AccountNotFound, InvalidCredentials, InvalidRefreshToken, TooManyLoginAttempts
from app.modules.auth.domain.refresh_token import ACCESS_TOKEN_TTL
from app.modules.auth.infrastructure.rate_limiter import RedisLoginAttemptLimiter
from app.modules.auth.infrastructure.refresh_tokens import OpaqueRefreshTokenCodec, SqlAlchemyRefreshTokenRepository
from app.modules.staff.application.find_user import FindUserByEmail, GetUser
from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository
from app.shared.domain.principal import Role
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import CurrentPrincipal
from app.shared.infrastructure.security import Argon2PasswordHasher, SystemClock

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
# Same value as the API prefix + this router's prefix: the cookie only travels to auth endpoints.
REFRESH_COOKIE_PATH = "/api/v1/auth"

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


# --- Schemas -----------------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    role: Role


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut


# --- Wiring ------------------------------------------------------------------------------------


def _session_issuer(request: Request, session: AsyncSession) -> SessionIssuer:
    return SessionIssuer(
        SqlAlchemyRefreshTokenRepository(session),
        OpaqueRefreshTokenCodec(),
        request.app.state.access_tokens,
        SystemClock(),
    )


def get_login(request: Request, session: SessionDep) -> Login:
    settings = get_settings()
    limiter = RedisLoginAttemptLimiter(
        request.app.state.redis,
        window_seconds=settings.login_failure_window_seconds,
        max_per_account=settings.login_max_failures_per_account,
        max_per_ip=settings.login_max_failures_per_ip,
    )
    return Login(
        FindUserByEmail(SqlAlchemyUserRepository(session)),
        Argon2PasswordHasher(),
        limiter,
        _session_issuer(request, session),
        SqlAlchemyUnitOfWork(session),
    )


def get_refresh_session(request: Request, session: SessionDep) -> RefreshSession:
    return RefreshSession(
        SqlAlchemyRefreshTokenRepository(session),
        OpaqueRefreshTokenCodec(),
        GetUser(SqlAlchemyUserRepository(session)),
        _session_issuer(request, session),
        SystemClock(),
        SqlAlchemyUnitOfWork(session),
    )


def get_logout(session: SessionDep) -> Logout:
    return Logout(
        SqlAlchemyRefreshTokenRepository(session), OpaqueRefreshTokenCodec(), SystemClock(), SqlAlchemyUnitOfWork(session)
    )


def get_current_account(session: SessionDep) -> GetCurrentAccount:
    return GetCurrentAccount(GetUser(SqlAlchemyUserRepository(session)), GetTenant(SqlAlchemyTenantRepository(session)))


# --- Helpers -----------------------------------------------------------------------------------


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime, issued_at: datetime) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int((expires_at - issued_at).total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=get_settings().refresh_cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=get_settings().refresh_cookie_secure,
        samesite="strict",
    )


def _token_response(response: Response, auth: AuthSession) -> TokenResponse:
    _set_refresh_cookie(response, auth.refresh_token, auth.refresh_expires_at, auth.access_expires_at - ACCESS_TOKEN_TTL)
    return TokenResponse(
        access_token=auth.access_token, expires_in=int(ACCESS_TOKEN_TTL.total_seconds()), role=auth.role
    )


# --- Routes ------------------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, use_case: Annotated[Login, Depends(get_login)]
) -> TokenResponse | JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    try:
        auth = await use_case.execute(body.email, body.password, client_ip)
    except InvalidCredentials:
        return JSONResponse({"detail": "Invalid email or password"}, status_code=status.HTTP_401_UNAUTHORIZED)
    except TooManyLoginAttempts as error:
        return JSONResponse(
            {"detail": "Too many login attempts. Try again later."},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(error.retry_after)},
        )
    return _token_response(response, auth)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    use_case: Annotated[RefreshSession, Depends(get_refresh_session)],
    refresh_token: RefreshCookie = None,
) -> TokenResponse | JSONResponse:
    try:
        auth = await use_case.execute(refresh_token or "")
    except InvalidRefreshToken:
        rejected = JSONResponse({"detail": "Invalid session"}, status_code=status.HTTP_401_UNAUTHORIZED)
        _clear_refresh_cookie(rejected)
        return rejected
    return _token_response(response, auth)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(use_case: Annotated[Logout, Depends(get_logout)], refresh_token: RefreshCookie = None) -> Response:
    await use_case.execute(refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    principal: CurrentPrincipal, use_case: Annotated[GetCurrentAccount, Depends(get_current_account)]
) -> MeResponse | JSONResponse:
    try:
        account = await use_case.execute(principal)
    except AccountNotFound:
        return JSONResponse(
            {"detail": "Not authenticated"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    user, tenant = account.user, account.tenant
    return MeResponse(
        user=UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role),
        tenant=TenantOut(id=tenant.id, name=tenant.name),
    )
