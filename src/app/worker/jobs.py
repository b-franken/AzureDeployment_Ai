# src/app/worker/jobs.py
import asyncio
from typing import Any

from app.core.logging import get_logger
from app.tools.azure.utils.terraform_runner import plan_and_apply

logger = get_logger(__name__)


def run() -> None:
    logger.info("Starting worker job runner")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("Running main worker task")
        loop.run_until_complete(_main())
        logger.info("Worker job completed successfully")
    except Exception as e:
        logger.error("Worker job failed", error=str(e), error_type=type(e).__name__)
        raise
    finally:
        logger.info("Shutting down worker event loop")
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


async def _main() -> None:
    logger.info("Executing main worker logic")
    spec: dict[str, Any] = {}
    logger.debug("Running terraform plan and apply", spec=spec)
    await plan_and_apply(spec, plan_only=False)
    logger.info("Terraform plan and apply completed")
