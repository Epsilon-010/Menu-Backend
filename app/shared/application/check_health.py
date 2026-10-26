import asyncio
from collections.abc import Sequence

from app.shared.domain.health import DependencyProbe, HealthReport


class CheckHealth:
    """Runs every dependency probe concurrently; errors and timeouts count as unhealthy."""

    def __init__(self, probes: Sequence[DependencyProbe], timeout_seconds: float = 2.0) -> None:
        self._probes = probes
        self._timeout_seconds = timeout_seconds

    async def execute(self) -> HealthReport:
        results = await asyncio.gather(*(self._run(probe) for probe in self._probes))
        return HealthReport(checks={probe.name: ok for probe, ok in zip(self._probes, results, strict=True)})

    async def _run(self, probe: DependencyProbe) -> bool:
        try:
            return await asyncio.wait_for(probe.is_healthy(), timeout=self._timeout_seconds)
        except Exception:
            return False
