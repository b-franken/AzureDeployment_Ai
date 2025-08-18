# src/app/worker/jobs.py
import asyncio
from typing import Any

from app.tools.provision.terraform_runner import plan_and_apply


def run() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


async def _main() -> None:
    spec: dict[str, Any] = {}
    await plan_and_apply(spec, plan_only=False)
