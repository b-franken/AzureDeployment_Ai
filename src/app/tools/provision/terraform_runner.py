from __future__ import annotations

import asyncio
import json
import tempfile
import textwrap
from pathlib import Path
from typing import Any


class TerraformError(Exception):
    pass


async def _run(cmd: list[str], cwd: Path, timeout: float = 60.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    if stdout_bytes is None:
        stdout_bytes = b""
    return proc.returncode, stdout_bytes.decode("utf-8", errors="replace")


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

        code, out = await _run(["terraform", "init", "-input=false", "-no-color"], cwd)
        if code != 0:
            raise TerraformError(out)

        code, plan_out = await _run(["terraform", "plan", "-input=false", "-no-color"], cwd)
        if code != 0:
            raise TerraformError(plan_out)

        result: dict[str, Any] = {"plan": plan_out}

        if plan_only:
            return result

        code, apply_out = await _run(
            ["terraform", "apply", "-auto-approve", "-input=false", "-no-color"], cwd
        )
        if code != 0:
            raise TerraformError(apply_out)

        code, json_out = await _run(["terraform", "output", "-json"], cwd)
        outputs: dict[str, Any] = {}
        try:
            outputs = json.loads(json_out) if code == 0 else {}
        except Exception:
            outputs = {}

        result["apply"] = apply_out
        result["outputs"] = outputs
        return result
