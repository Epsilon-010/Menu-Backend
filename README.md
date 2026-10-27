# Menu Backend

FastAPI API for the Menu SaaS (multi-tenant self-service digital menu). Hexagonal layout:
`app/modules/<module>/{domain,application,infrastructure}` plus `app/shared/`.

The frontend lives in the sibling repository `../Menu-Frontend`; `docker-compose.yml` here runs both.

## Run everything with Docker

```sh
cp .env.example .env
docker compose up -d --build
```

- API: http://localhost:8020/api/v1/health
- Frontend: http://localhost:5173

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
