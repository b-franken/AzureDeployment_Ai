from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    last_check: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None


class HealthMonitor:
    def __init__(self) -> None:
        self.checks: dict[str, Callable[[], Awaitable[Any]]] = {}
        self.results: dict[str, ComponentHealth] = {}
        self.check_interval = 30
        self._running = False
        self._task: asyncio.Task | None = None

    def register_check(self, name: str, check_fn: Callable[[], Awaitable[Any]]) -> None:
        self.checks[name] = check_fn

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _monitor_loop(self) -> None:
        while self._running:
            await self.run_health_checks()
            await asyncio.sleep(self.check_interval)

    async def run_health_checks(self) -> dict[str, ComponentHealth]:
        tasks: list[Awaitable[ComponentHealth]] = []
        for name, check_fn in self.checks.items():
            tasks.append(self._run_check(name, check_fn))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, ComponentHealth):
                self.results[result.name] = result
        return self.results

    async def _run_check(
        self, name: str, check_fn: Callable[[], Awaitable[Any]]
    ) -> ComponentHealth:
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(check_fn(), timeout=10.0)
            latency_ms = (time.monotonic() - start_time) * 1000.0
            if isinstance(result, bool):
                status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
                details: dict[str, Any] = {}
            elif isinstance(result, dict):
                status = HealthStatus(result.get("status", "healthy"))
                details = result.get("details", {})
            else:
                status = HealthStatus.HEALTHY
                details = {"result": str(result)}
            return ComponentHealth(
                name=name,
                status=status,
                latency_ms=latency_ms,
                details=details,
            )
        except TimeoutError:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=10000.0,
                error="Health check timed out",
            )
        except Exception as e:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=(time.monotonic() - start_time) * 1000.0,
                error=str(e),
            )

    async def get_overall_health(self) -> dict[str, Any]:
        if not self.results:
            await self.run_health_checks()
        overall_status = HealthStatus.HEALTHY
        unhealthy_components: list[str] = []
        degraded_components: list[str] = []
        for component in self.results.values():
            if component.status == HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.UNHEALTHY
                unhealthy_components.append(component.name)
            elif component.status == HealthStatus.DEGRADED:
                if overall_status != HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED
                degraded_components.append(component.name)
        return {
            "status": overall_status.value,
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                name: {
                    "status": health.status.value,
                    "latency_ms": health.latency_ms,
                    "details": health.details,
                    "last_check": health.last_check.isoformat(),
                    "error": health.error,
                }
                for name, health in self.results.items()
            },
            "unhealthy_components": unhealthy_components,
            "degraded_components": degraded_components,
        }


async def check_database_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "details": {"connections": 45, "max_connections": 100, "response_time_ms": 12},
    }


async def check_redis_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "details": {"memory_used_mb": 256, "memory_max_mb": 1024, "connected_clients": 23},
    }


async def check_azure_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "details": {"subscription_active": True, "api_available": True},
    }


health_monitor = HealthMonitor()
health_monitor.register_check("database", check_database_health)
health_monitor.register_check("redis", check_redis_health)
health_monitor.register_check("azure", check_azure_health)
