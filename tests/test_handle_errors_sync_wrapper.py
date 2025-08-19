import asyncio

from app.core.exceptions import handle_errors


@handle_errors(recover=False, default_return="ok")
def _sync_fail() -> None:
    raise ValueError("boom")


def test_sync_function_in_sync_context() -> None:
    assert _sync_fail() == "ok"


def test_sync_function_in_async_context() -> None:
    async def runner() -> str:
        return await _sync_fail()

    assert asyncio.run(runner()) == "ok"
