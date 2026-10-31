import ipaddress
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.get_current_account import GetCurrentAccount
from app.modules.auth.application.login import Login
from app.modules.auth.application.logout import Logout
from app.modules.auth.application.qr_login import QrLogin
from app.modules.auth.application.refresh_session import RefreshSession
from app.modules.auth.application.register_business import RegisterBusiness
from app.modules.auth.application.session_issuer import AuthSession, SessionIssuer
from app.modules.auth.application.table_login import TableLogin
from app.modules.auth.domain.errors import (
    AccountNotFound,
    BusinessIdTaken,
    InvalidCredentials,
    InvalidRefreshToken,
    TooManyLoginAttempts,
)
from app.modules.auth.domain.refresh_token import ACCESS_TOKEN_TTL
from app.modules.auth.infrastructure.rate_limiter import RedisLoginAttemptLimiter
from app.modules.auth.infrastructure.refresh_tokens import OpaqueRefreshTokenCodec, SqlAlchemyRefreshTokenRepository
from app.modules.orders.application.guests import GetActiveGuest, JoinTable
from app.modules.orders.domain.errors import InvalidOrderData, TableNotOpen
from app.modules.orders.domain.model import MAX_GUEST_NAME_LENGTH
from app.modules.orders.infrastructure.adapters import TablesModule
from app.modules.orders.infrastructure.repository import (
    PostgresTableLocks,
    SqlAlchemyBillRepository,
    SqlAlchemyGuestRepository,
)
from app.modules.staff.application.create_user import CreateUser, LockEmail
from app.modules.staff.application.find_user import FindUserByLogin, GetUser
from app.modules.staff.domain.errors import EmailAlreadyInUse, InvalidUserData
from app.modules.staff.infrastructure.repository import SqlAlchemyUserRepository
from app.modules.tables.application.find_table import FindTableByCode, FindTableByQrToken, GetTable
from app.modules.tables.infrastructure.repository import SqlAlchemyTableRepository
from app.modules.tenants.application.create_tenant import CreateTenant
from app.modules.tenants.application.get_tenant import GetTenant
from app.modules.tenants.domain.errors import InvalidTenantData, TenantIdTaken
from app.modules.tenants.domain.tenant import MAX_TIMEZONE_LENGTH
from app.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository
from app.shared.domain.principal import Role
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import SqlAlchemyUnitOfWork, get_session
from app.shared.infrastructure.http.auth import ACCESS_COOKIE, ACCESS_COOKIE_PATH, CurrentPrincipal
from app.shared.infrastructure.http.problems import problem
from app.shared.infrastructure.security import Argon2PasswordHasher, SystemClock

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
# Same value as the API prefix + this router's prefix: the cookie only travels to auth endpoints.
REFRESH_COOKIE_PATH = "/api/v1/auth"

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


# --- Schemas -----------------------------------------------------------------------------------


class LoginRequest(BaseModel):
    # The admin's email or a staff member's username.
    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class TableLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    pin: str = Field(min_length=1, max_length=20)


class QrLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The random part of the QR link (`/q/<token>`).
    token: str = Field(min_length=1, max_length=64)
    # Shown next to what the guest adds to the shared cart; "Guest N" when left out.
    name: str | None = Field(default=None, max_length=MAX_GUEST_NAME_LENGTH)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional client-chosen id of the new business: repeating the sign-up signs in to it.
    id: uuid.UUID | None = None
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    business_name: str = Field(max_length=200)
    # The browser's IANA time zone; the statistics cut days in it.
    timezone: str | None = Field(default=None, max_length=MAX_TIMEZONE_LENGTH)


class SessionResponse(BaseModel):
    """Both tokens travel only in httpOnly cookies; the body tells the client who it is."""

    expires_in: int
    role: Role


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    full_name: str
    role: Role


class TableOut(BaseModel):
    id: uuid.UUID
    name: str


class GuestOut(BaseModel):
    id: uuid.UUID
    name: str


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str


class MeResponse(BaseModel):
    """Staff accounts get `user`; table devices get `table`; QR guests get `guest` and the `table` they joined."""

    user: UserOut | None
    table: TableOut | None
    guest: GuestOut | None = None
    tenant: TenantOut


# --- Wiring ------------------------------------------------------------------------------------


def _session_issuer(request: Request, session: AsyncSession) -> SessionIssuer:
    return SessionIssuer(
        SqlAlchemyRefreshTokenRepository(session),
        OpaqueRefreshTokenCodec(),
        request.app.state.access_tokens,
        SystemClock(),
    )


def _login_limiter(request: Request) -> RedisLoginAttemptLimiter:
    settings = get_settings()
    return RedisLoginAttemptLimiter(
        request.app.state.redis,
        window_seconds=settings.login_failure_window_seconds,
        max_per_client=settings.login_max_failures_per_client,
        max_per_account=settings.login_max_failures_backstop,
    )


def _client_address(request: Request) -> str:
    """The caller's IP. Behind the frontend proxy, uvicorn takes it from X-Forwarded-For only when the
    request comes from an address in FORWARDED_ALLOW_IPS, so a direct caller cannot choose it."""
    if request.client is None:
        return "unknown"
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return request.client.host
    # The same device can arrive as IPv4 or IPv4-mapped IPv6 (::ffff:a.b.c.d): count it once.
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return str(mapped or address)


def get_login(request: Request, session: SessionDep) -> Login:
    return Login(
        FindUserByLogin(SqlAlchemyUserRepository(session)),
        Argon2PasswordHasher(),
        _login_limiter(request),
        _session_issuer(request, session),
        SqlAlchemyUnitOfWork(session),
    )


class _CommitLater:
    """Unit of work for the use cases a larger one composes: their `commit` does nothing, so the outer
    use case commits everything at once (or nothing, when it fails)."""

    async def commit(self) -> None:
        return None


def get_register_business(request: Request, session: SessionDep) -> RegisterBusiness:
    users = SqlAlchemyUserRepository(session)
    tenants = SqlAlchemyTenantRepository(session)
    hasher = Argon2PasswordHasher()
    return RegisterBusiness(
        LockEmail(users),
        FindUserByLogin(users),
        GetTenant(tenants),
        CreateTenant(tenants, _CommitLater()),
        CreateUser(users, hasher, _CommitLater()),
        hasher,
        _login_limiter(request),
        _session_issuer(request, session),
        SqlAlchemyUnitOfWork(session),
    )


def get_table_login(request: Request, session: SessionDep) -> TableLogin:
    return TableLogin(
        FindTableByCode(SqlAlchemyTableRepository(session)),
        Argon2PasswordHasher(),
        _login_limiter(request),
        _session_issuer(request, session),
        SqlAlchemyUnitOfWork(session),
    )


def _get_active_guest(session: AsyncSession) -> GetActiveGuest:
    return GetActiveGuest(SqlAlchemyBillRepository(session), SqlAlchemyGuestRepository(session), SystemClock())


def get_qr_login(request: Request, session: SessionDep) -> QrLogin:
    return QrLogin(
        FindTableByQrToken(SqlAlchemyTableRepository(session)),
        JoinTable(
            PostgresTableLocks(session),
            TablesModule(session),
            SqlAlchemyBillRepository(session),
            SqlAlchemyGuestRepository(session),
            SystemClock(),
        ),
        _login_limiter(request),
        _session_issuer(request, session),
        SqlAlchemyUnitOfWork(session),
    )


def get_refresh_session(request: Request, session: SessionDep) -> RefreshSession:
    return RefreshSession(
        SqlAlchemyRefreshTokenRepository(session),
        OpaqueRefreshTokenCodec(),
        GetUser(SqlAlchemyUserRepository(session)),
        GetTable(SqlAlchemyTableRepository(session)),
        _get_active_guest(session),
        _session_issuer(request, session),
        SystemClock(),
        SqlAlchemyUnitOfWork(session),
    )


def get_logout(session: SessionDep) -> Logout:
    return Logout(
        SqlAlchemyRefreshTokenRepository(session), OpaqueRefreshTokenCodec(), SystemClock(), SqlAlchemyUnitOfWork(session)
    )


def get_current_account(session: SessionDep) -> GetCurrentAccount:
    return GetCurrentAccount(
        GetUser(SqlAlchemyUserRepository(session)),
        GetTable(SqlAlchemyTableRepository(session)),
        GetTenant(SqlAlchemyTenantRepository(session)),
        _get_active_guest(session),
    )


# --- Cookies -----------------------------------------------------------------------------------


def _set_cookie(response: Response, name: str, value: str, path: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        httponly=True,
        secure=get_settings().auth_cookie_secure,
        samesite="strict",
    )


def _set_session_cookies(response: Response, auth: AuthSession) -> None:
    issued_at = auth.access_expires_at - ACCESS_TOKEN_TTL
    _set_cookie(response, ACCESS_COOKIE, auth.access_token, ACCESS_COOKIE_PATH, int(ACCESS_TOKEN_TTL.total_seconds()))
    _set_cookie(
        response,
        REFRESH_COOKIE,
        auth.refresh_token,
        REFRESH_COOKIE_PATH,
        int((auth.refresh_expires_at - issued_at).total_seconds()),
    )


def _clear_session_cookies(response: Response) -> None:
    for name, path in ((ACCESS_COOKIE, ACCESS_COOKIE_PATH), (REFRESH_COOKIE, REFRESH_COOKIE_PATH)):
        response.delete_cookie(
            name, path=path, httponly=True, secure=get_settings().auth_cookie_secure, samesite="strict"
        )


def _session_response(response: Response, auth: AuthSession) -> SessionResponse:
    _set_session_cookies(response, auth)
    return SessionResponse(expires_in=int(ACCESS_TOKEN_TTL.total_seconds()), role=auth.role)


def _too_many_attempts(error: TooManyLoginAttempts) -> JSONResponse:
    return problem(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many login attempts. Try again later.",
        headers={"Retry-After": str(error.retry_after)},
    )


# --- Routes ------------------------------------------------------------------------------------


@router.post("/login", response_model=SessionResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, use_case: Annotated[Login, Depends(get_login)]
) -> SessionResponse | JSONResponse:
    try:
        auth = await use_case.execute(body.username, body.password, _client_address(request))
    except InvalidCredentials:
        return problem(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    except TooManyLoginAttempts as error:
        return _too_many_attempts(error)
    return _session_response(response, auth)


@router.post("/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    use_case: Annotated[RegisterBusiness, Depends(get_register_business)],
) -> SessionResponse | JSONResponse:
    """Self sign-up: creates the business and its admin in one transaction and signs the admin in."""
    try:
        auth = await use_case.execute(
            body.email, body.password, body.business_name, _client_address(request), body.id, body.timezone
        )
    except (InvalidUserData, InvalidTenantData) as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except EmailAlreadyInUse:
        return problem(status.HTTP_409_CONFLICT, "Email already in use")
    except (BusinessIdTaken, TenantIdTaken):
        return problem(status.HTTP_409_CONFLICT, "That id is already used by something else")
    except TooManyLoginAttempts as error:
        return _too_many_attempts(error)
    return _session_response(response, auth)


@router.post("/table-login", response_model=SessionResponse)
async def table_login(
    body: TableLoginRequest,
    request: Request,
    response: Response,
    use_case: Annotated[TableLogin, Depends(get_table_login)],
) -> SessionResponse | JSONResponse:
    try:
        auth = await use_case.execute(body.code, body.pin, _client_address(request))
    except InvalidCredentials:
        return problem(status.HTTP_401_UNAUTHORIZED, "Invalid table code or PIN")
    except TooManyLoginAttempts as error:
        return _too_many_attempts(error)
    return _session_response(response, auth)


@router.post("/qr", response_model=SessionResponse)
async def qr_login(
    body: QrLoginRequest,
    request: Request,
    response: Response,
    use_case: Annotated[QrLogin, Depends(get_qr_login)],
) -> SessionResponse | JSONResponse:
    """A guest who scanned the table's QR joins its open visit (any number of guests per table)."""
    try:
        auth = await use_case.execute(body.token, body.name, _client_address(request))
    except InvalidCredentials:
        return problem(status.HTTP_401_UNAUTHORIZED, "This QR code is not valid")
    except TableNotOpen:
        return problem(status.HTTP_409_CONFLICT, "This table is not open yet; ask your waiter")
    except InvalidOrderData as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except TooManyLoginAttempts as error:
        return _too_many_attempts(error)
    return _session_response(response, auth)


@router.post("/refresh", response_model=SessionResponse)
async def refresh(
    response: Response,
    use_case: Annotated[RefreshSession, Depends(get_refresh_session)],
    refresh_token: RefreshCookie = None,
) -> SessionResponse | JSONResponse:
    try:
        auth = await use_case.execute(refresh_token or "")
    except InvalidRefreshToken:
        rejected = problem(status.HTTP_401_UNAUTHORIZED, "Invalid session")
        _clear_session_cookies(rejected)
        return rejected
    return _session_response(response, auth)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(use_case: Annotated[Logout, Depends(get_logout)], refresh_token: RefreshCookie = None) -> Response:
    await use_case.execute(refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookies(response)
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    principal: CurrentPrincipal, use_case: Annotated[GetCurrentAccount, Depends(get_current_account)]
) -> MeResponse | JSONResponse:
    try:
        account = await use_case.execute(principal)
    except AccountNotFound:
        return problem(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user, table, guest, tenant = account.user, account.table, account.guest, account.tenant
    return MeResponse(
        user=UserOut(id=user.id, email=user.email, username=user.username, full_name=user.full_name, role=user.role)
        if user is not None
        else None,
        table=TableOut(id=table.id, name=table.name) if table is not None else None,
        guest=GuestOut(id=guest.id, name=guest.name) if guest is not None else None,
        tenant=TenantOut(id=tenant.id, name=tenant.name),
    )
