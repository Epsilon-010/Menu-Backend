import asyncio

import pytest

from app.shared.application.check_health import CheckHealth


class FakeProbe:
    def __init__(self, name: str, healthy: bool = True, delay: float = 0.0, error: bool = False) -> None:
        self.name = name
        self._healthy = healthy
        self._delay = delay
        self._error = error

    async def is_healthy(self) -> bool:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise ConnectionError("boom")
        return self._healthy


pytestmark = pytest.mark.anyio


async def test_reports_healthy_when_every_dependency_is_up() -> None:
    report = await CheckHealth([FakeProbe("postgres"), FakeProbe("redis")]).execute()

    assert report.healthy is True
    assert report.checks == {"postgres": True, "redis": True}


async def test_reports_unhealthy_when_a_dependency_is_down() -> None:
    report = await CheckHealth([FakeProbe("postgres"), FakeProbe("redis", healthy=False)]).execute()

    assert report.healthy is False
    assert report.checks == {"postgres": True, "redis": False}


async def test_treats_a_probe_error_as_unhealthy() -> None:
    report = await CheckHealth([FakeProbe("postgres", error=True)]).execute()

    assert report.checks == {"postgres": False}


async def test_treats_a_slow_probe_as_unhealthy() -> None:
    report = await CheckHealth([FakeProbe("redis", delay=0.5)], timeout_seconds=0.05).execute()

    assert report.checks == {"redis": False}
