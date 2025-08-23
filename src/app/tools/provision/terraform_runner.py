from __future__ import annotations

import asyncio
import json
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class TerraformError(Exception):
    pass


async def _run(cmd: list[str], cwd: Path, timeout: float = 60.0) -> tuple[int, str]:
    start = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        try:
            proc.kill()
        finally:
            await proc.communicate()
        logger.error(
            "terraform_runner.exec_timeout",
            cmd=cmd,
            cwd=str(cwd),
            timeout_s=timeout,
        )
        raise
    if stdout_bytes is None:
        stdout_bytes = b""
    rc = proc.returncode if proc.returncode is not None else -1
    out = stdout_bytes.decode("utf-8", errors="replace")
    logger.debug(
        "terraform_runner.exec_done",
        cmd=cmd,
        cwd=str(cwd),
        rc=rc,
        duration_ms=(time.perf_counter() - start) * 1000.0,
        out_len=len(out),
    )
    return rc, out


def _tf_main_tf(spec: dict[str, Any]) -> str:
    params = spec.get("parameters", {})
    location = params.get("location") or "westeurope"
    rg_name = params.get("resource_group_name") or "rg-demo"
    plan_sku = params.get("plan_sku", "B1")
    app_name = params.get("name", "webapp-demo")
    plan_name = params.get("plan_name", f"{app_name}-plan")
    return textwrap.dedent(
        f"""
    terraform {{
      required_version = ">= 1.5.0"
      required_providers {{
        azurerm {{
          source  = "hashicorp/azurerm"
          version = ">= 3.111.0"
        }}
      }}
    }}

    provider "azurerm" {{
      features {{}}
    }}

    resource "azurerm_resource_group" "rg" {{
      name     = "{rg_name}"
      location = "{location}"
    }}

    resource "azurerm_service_plan" "plan" {{
      name                = "{plan_name}"
      location            = azurerm_resource_group.rg.location
      resource_group_name = azurerm_resource_group.rg.name
      os_type             = "Linux"
      sku_name            = "{plan_sku}"
    }}

    resource "azurerm_linux_web_app" "app" {{
      name                = "{app_name}"
      location            = azurerm_resource_group.rg.location
      resource_group_name = azurerm_resource_group.rg.name
      service_plan_id     = azurerm_service_plan.plan.id
      https_only          = true
      site_config {{
        minimum_tls_version = "1.2"
      }}
    }}

    output "web_app_default_hostname" {{
      value = azurerm_linux_web_app.app.default_hostname
    }}
    """
    )


async def plan_and_apply(spec: dict[str, Any], plan_only: bool) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as d:
        cwd = Path(d)
        (cwd / "main.tf").write_text(_tf_main_tf(spec), encoding="utf-8")

        logger.info("terraform_runner.init.start", cwd=str(cwd))
        code, out = await _run(["terraform", "init", "-input=false", "-no-color"], cwd)
        if code != 0:
            logger.error("terraform_runner.init.failed", rc=code)
            raise TerraformError(out)

        logger.info("terraform_runner.plan.start", cwd=str(cwd))
        code, plan_out = await _run(["terraform", "plan", "-input=false", "-no-color"], cwd)
        if code != 0:
            logger.error("terraform_runner.plan.failed", rc=code)
            raise TerraformError(plan_out)

        result: dict[str, Any] = {"plan": plan_out}

        if plan_only:
            logger.info("terraform_runner.plan_only.completed")
            return result

        logger.info("terraform_runner.apply.start", cwd=str(cwd))
        code, apply_out = await _run(
            ["terraform", "apply", "-auto-approve", "-input=false", "-no-color"], cwd
        )
        if code != 0:
            logger.error("terraform_runner.apply.failed", rc=code)
            raise TerraformError(apply_out)

        logger.info("terraform_runner.output.start", cwd=str(cwd))
        code, json_out = await _run(["terraform", "output", "-json"], cwd)
        outputs: dict[str, Any] = {}
        if code == 0:
            try:
                outputs = json.loads(json_out)
            except Exception as exc:
                logger.warning(
                    "terraform_runner.output.parse_error",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

        result["apply"] = apply_out
        result["outputs"] = outputs
        logger.info("terraform_runner.completed", has_outputs=bool(outputs))
        return result
