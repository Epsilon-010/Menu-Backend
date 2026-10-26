from dataclasses import dataclass
from typing import Protocol


class DependencyProbe(Protocol):
    """Port: checks whether an external dependency (database, cache...) is reachable."""

    name: str

    async def is_healthy(self) -> bool: ...


@dataclass(frozen=True)
class HealthReport:
    checks: dict[str, bool]

    @property
    def healthy(self) -> bool:
        return all(self.checks.values())
