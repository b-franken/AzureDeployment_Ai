import logging

import pytest

from app.core.container import Container, inject
from app.core.exceptions import ConfigurationError


class _MissingDep:
    pass


def test_inject_strict_mode_raises(monkeypatch):
    monkeypatch.setenv("DI_STRICT_MODE", "1")
    container = Container()

    @inject(container)
    def fn(dep: _MissingDep) -> _MissingDep:
        return dep

    with pytest.raises(ConfigurationError) as exc:
        fn()
    assert "Failed to resolve dependency" in str(exc.value)


def test_inject_logs_when_not_strict(monkeypatch, caplog):
    monkeypatch.delenv("DI_STRICT_MODE", raising=False)
    container = Container()

    @inject(container)
    def fn(dep: _MissingDep | None = None) -> _MissingDep | None:
        return dep

    with caplog.at_level(logging.WARNING):
        assert fn() is None
    assert "Failed to resolve dependency" in caplog.text
