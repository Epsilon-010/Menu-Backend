# Menu Backend

FastAPI API for the Menu SaaS (multi-tenant self-service digital menu). Hexagonal layout:
`app/modules/<module>/{domain,application,infrastructure}` plus `app/shared/`.

The frontend lives in the sibling repository `../Menu-Frontend`; `docker-compose.yml` here runs both.

## Run everything with Docker

```sh
cp .env.example .env   # then set JWT_SECRET to a long random value
docker compose up -d --build
```

- API: http://localhost:8020/api/v1/health
- Frontend: http://localhost:5173 (sign in at `/login`)

## Create the first tenant and admin

```sh
docker compose exec backend uv run python -m app.seed --tenant-name "My Diner" --admin-email owner@example.com --admin-name "Owner"
```

The password comes from `--admin-password`, the `SEED_ADMIN_PASSWORD` variable, or an interactive prompt
(at least 8 characters). Emails are unique across all tenants. Outside Docker run the same command with `uv run`.

## Authentication

- `POST /api/v1/auth/login` (email + password) returns a 15-minute access JWT and sets the refresh token
  as an `httpOnly`, `Secure`, `SameSite=Strict` cookie limited to `/api/v1/auth`.
- `POST /api/v1/auth/refresh` rotates the refresh token; reusing an already rotated one revokes its whole family.
- `POST /api/v1/auth/logout` revokes the current family. `GET /api/v1/auth/me` returns the user and the business.
- Failed logins are rate limited per IP and per account in Redis (`LOGIN_*` settings in `.env.example`).
- Routes declare their allowed roles with `Depends(require_role("admin", ...))`
  (`app/shared/infrastructure/http/auth.py`); the tenant always comes from the token.

Host ports are configurable in `.env` (`POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT`).

## Local development with uv

```sh
docker compose up -d postgres redis
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run pytest
```

Tests use their own resources derived from `.env`: database `<name>_test` (recreated with Alembic
migrations on every run) and Redis logical db 15.

## Conventions

- Every primary key is an auto-generated UUID: models inherit `UUIDPrimaryKey` from
  `app/shared/infrastructure/database.py`.
- Schema changes only through Alembic: `uv run alembic revision --autogenerate -m "<message>"`.
