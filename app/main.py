from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.shared.infrastructure.cache import create_redis
from app.shared.infrastructure.config import get_settings
from app.shared.infrastructure.database import create_engine, create_session_factory
from app.shared.infrastructure.http import health_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings.redis_url)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name, lifespan=lifespan)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health_router.router)
    app.include_router(api)
    return app


app = create_app()
