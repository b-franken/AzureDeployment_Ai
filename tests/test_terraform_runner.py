import asyncio
from pathlib import Path

import pytest

from app.tools.provision.terraform_runner import _run


def test_run_success(tmp_path: Path) -> None:
    code, out = asyncio.run(_run(["bash", "-c", "echo -n success"], tmp_path, timeout=5))
    assert code == 0
    assert out == "success"


def test_run_failure(tmp_path: Path) -> None:
    code, out = asyncio.run(
        _run(["bash", "-c", "echo -n fail; exit 1"], tmp_path, timeout=5)
    )
    assert code != 0
    assert "fail" in out


def test_run_timeout(tmp_path: Path) -> None:
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(_run(["bash", "-c", "sleep 2"], tmp_path, timeout=0.1))
