import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stats.application.get_statistics import GetStatistics
from app.modules.stats.domain.errors import InvalidStatsRange
from app.modules.stats.domain.report import Duration, Statistics
from app.modules.stats.infrastructure.sales_source import ModulesSalesSource
from app.shared.domain.principal import Principal
from app.shared.infrastructure.database import get_session
from app.shared.infrastructure.http.auth import require_role
from app.shared.infrastructure.http.problems import problem

router = APIRouter(prefix="/stats", tags=["stats"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_role("admin"))]


class TotalsOut(BaseModel):
    collected_cents: int
    paid_bills: int
    average_ticket_cents: int
    pending_cents: int
    pending_orders: int


class DayOut(BaseModel):
    date: date
    collected_cents: int
    pending_cents: int


class MethodOut(BaseModel):
    method: str
    bills: int
    amount_cents: int


class ProductOut(BaseModel):
    item_id: uuid.UUID
    name: str
    quantity: int
    collected_cents: int
    pending_cents: int


class TableOut(BaseModel):
    table_id: uuid.UUID
    name: str
    orders: int
    collected_cents: int
    pending_cents: int


class DurationOut(BaseModel):
    average_seconds: int | None
    median_seconds: int | None
    count: int


class ProductTimesOut(BaseModel):
    item_id: uuid.UUID
    name: str
    queue: DurationOut
    preparation: DurationOut
    delivery: DurationOut


class TimesOut(BaseModel):
    queue: DurationOut
    preparation: DurationOut
    delivery: DurationOut
    order: DurationOut
    products: list[ProductTimesOut]


class StatisticsOut(BaseModel):
    # `from` is a Python keyword: the field is `first_day`, sent as "from" like the query.
    first_day: date = Field(serialization_alias="from")
    to: date
    timezone: str
    totals: TotalsOut
    days: list[DayOut]
    payment_methods: list[MethodOut]
    products: list[ProductOut]
    tables: list[TableOut]
    times: TimesOut


def _duration(value: Duration) -> DurationOut:
    return DurationOut(average_seconds=value.average_seconds, median_seconds=value.median_seconds, count=value.count)


def _out(stats: Statistics) -> StatisticsOut:
    times = stats.times
    return StatisticsOut(
        first_day=stats.first_day,
        to=stats.last_day,
        timezone=stats.timezone,
        totals=TotalsOut(**vars(stats.totals)),
        days=[DayOut(**vars(day)) for day in stats.days],
        payment_methods=[MethodOut(**vars(method)) for method in stats.payment_methods],
        products=[ProductOut(**vars(product)) for product in stats.products],
        tables=[TableOut(**vars(table)) for table in stats.tables],
        times=TimesOut(
            queue=_duration(times.queue),
            preparation=_duration(times.preparation),
            delivery=_duration(times.delivery),
            order=_duration(times.order),
            products=[
                ProductTimesOut(
                    item_id=product.item_id,
                    name=product.name,
                    queue=_duration(product.queue),
                    preparation=_duration(product.preparation),
                    delivery=_duration(product.delivery),
                )
                for product in times.products
            ],
        ),
    )


@router.get("", response_model=StatisticsOut)
async def read_statistics(
    admin: Admin,
    session: SessionDep,
    first_day: Annotated[date, Query(alias="from")],
    last_day: Annotated[date, Query(alias="to")],
) -> StatisticsOut | JSONResponse:
    """Sales, products, tables, payment methods and kitchen times for whole local days."""
    try:
        stats = await GetStatistics(ModulesSalesSource(session)).execute(admin.tenant_id, first_day, last_day)
    except InvalidStatsRange as error:
        return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    return _out(stats)
