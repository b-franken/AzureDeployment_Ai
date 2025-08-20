import asyncio

import pytest

from app.core.container import Container, inject
from app.core.exceptions import ConfigurationError


def test_inject_logs_missing_dependency(caplog: pytest.LogCaptureFixture) -> None:
    container = Container()

    @inject(container)
    async def func(dep: int = 5) -> int:
        return dep

    with caplog.at_level("WARNING"):
        result = asyncio.run(func())

    assert result == 5
    assert any("Dependency" in r.message for r in caplog.records)


def test_inject_raises_on_missing_required_dependency() -> None:
    container = Container()

    @inject(container)
    async def func(dep: int) -> int:
        return dep

    with pytest.raises(ConfigurationError):
        asyncio.run(func())

