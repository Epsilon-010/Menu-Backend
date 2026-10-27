from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.modules.auth.infrastructure import router as auth_router
from app.modules.auth.infrastructure.access_revocations import RedisAccessRevocations
from app.modules.auth.infrastructure.access_tokens import JoseAccessTokens
from app.modules.catalog.infrastructure import router as catalog_router
from app.modules.staff.infrastructure import router as staff_router
from app.modules.tables.infrastructure import router as tables_router
from app.shared.infrastructure.cache import create_redis
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.shared.infrastructure.http import health_router
from app.shared.infrastructure.http.problems import register_problem_handlers
from app.shared.infrastructure.images import build_image_storage

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings.redis_url)
    app.state.access_revocations = RedisAccessRevocations(app.state.redis)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.access_tokens = JoseAccessTokens(settings.jwt_secret.get_secret_value())
    app.state.image_storage = build_image_storage(settings)
    register_problem_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health_router.router)
    api.include_router(auth_router.router)
    api.include_router(staff_router.router)
    api.include_router(tables_router.router)
    api.include_router(catalog_router.router)
    app.include_router(api)
    return app


app = create_app()
