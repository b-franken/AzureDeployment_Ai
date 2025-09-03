from __future__ import annotations

import asyncio
import importlib
import shutil
import subprocess
from collections.abc import Sequence

from app.core.logging import get_logger
from app.tools.base import Tool, ToolResult

logger = get_logger(__name__)

_TOOLS: dict[str, Tool] = {}
_LOADED = False


def register(tool: Tool) -> None:
    _TOOLS[tool.name] = tool


def list_tools() -> list[Tool]:
    return list(_TOOLS.values())


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def _import_tool(module_path: str, class_name: str) -> Tool | None:
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        if not isinstance(cls, type) or not issubclass(cls, Tool):
            raise TypeError(f"{module_path}.{class_name} is not a Tool")
        return cls()
    except Exception as e:
        logger.warning("tool load failed %s.%s: %s", module_path, class_name, e)
        return None


def ensure_tools_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    registry: list[tuple[str, str]] = [
        ("app.tools.azure.intelligent_provision", "IntelligentAzureProvision"),
        ("app.tools.finops.cost_tool", "AzureCosts"),
        ("app.tools.azure.quota_check", "AzureQuotaCheck"),
    ]
    for module_path, class_name in registry:
        try:
            logger.info(f"Loading tool: {module_path}.{class_name}")
            tool = _import_tool(module_path, class_name)
            if tool is not None:
                register(tool)
                logger.info(f"Successfully registered tool: {tool.name}")
            else:
                logger.error(f"Tool creation failed for {module_path}.{class_name}")
        except Exception as e:
            logger.error(f"Failed to load tool {module_path}.{class_name}: {e}", exc_info=True)
    _LOADED = True


async def run_cmd(
    args: Sequence[str],
    input_text: str | None = None,
    timeout: int = 180,
    cwd: str | None = None,
) -> ToolResult:
    if not args or shutil.which(args[0]) is None:
        return {
            "ok": False,
            "summary": "executable not found",
            "output": args[0] if args else "",
        }

    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            list(args),
            cwd=cwd,
            input=(input_text.encode() if input_text else None),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )

    try:
        cp = await asyncio.to_thread(_run)
        out = (cp.stdout or b"").decode(errors="replace")
        return {
            "ok": cp.returncode == 0,
            "summary": f"exit {cp.returncode}",
            "output": out,
        }
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace")
        return {"ok": False, "summary": "timeout", "output": out}


__all__ = ["ensure_tools_loaded", "get_tool", "list_tools", "register", "run_cmd"]
