from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.shared.application.check_health import CheckHealth
from app.shared.infrastructure.cache import RedisProbe
from app.shared.infrastructure.database import PostgresProbe

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Literal["ok", "unavailable"]]


def get_check_health(request: Request) -> CheckHealth:
    state = request.app.state
    return CheckHealth([PostgresProbe(state.engine), RedisProbe(state.redis)])


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response, check_health: Annotated[CheckHealth, Depends(get_check_health)]
) -> HealthResponse:
    report = await check_health.execute()
    if not report.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if report.healthy else "degraded",
        checks={name: "ok" if ok else "unavailable" for name, ok in report.checks.items()},
    )
