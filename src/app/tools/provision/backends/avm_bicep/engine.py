from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .az_cli import AzCli
from .emitters import EMITTERS
from .versions import resolve
from .writer import BicepWriter


@dataclass
class ProvisionContext:
    subscription_id: str
    resource_group: str
    location: str = "westeurope"
    name_prefix: str = "app"
    environment: str = "dev"
    tags: dict[str, str] | None = None


@dataclass
class PlanPreview:
    bicep_path: str
    parameters_path: str | None
    what_if: str | None
    rendered: str


class BicepAvmBackend:
    def __init__(self, avm_version_map: dict[str, str] | None = None) -> None:
        self._az = AzCli()
        self._overrides = avm_version_map or {}

    async def plan(
        self, ctx: ProvisionContext, spec: dict[str, Any], dry_run: bool = True
    ) -> PlanPreview:
        rendered = self._render(ctx, spec)
        tmpdir = Path(tempfile.mkdtemp(prefix="avm_plan_"))
        bicep_path = tmpdir / "main.bicep"
        bicep_path.write_text(rendered, encoding="utf-8")
        parameters_path: str | None = None
        what_if: str | None = None
        if dry_run:
            what_if = await self._az.what_if_group(
                ctx.resource_group, str(bicep_path), ctx.subscription_id
            )
        return PlanPreview(
            bicep_path=str(bicep_path),
            parameters_path=parameters_path,
            what_if=what_if,
            rendered=rendered,
        )

    async def apply(self, ctx: ProvisionContext, bicep_file: str) -> dict[str, Any]:
        out = await self._az.deploy_group(ctx.resource_group, bicep_file, ctx.subscription_id)
        try:
            return json.loads(out)
        except Exception:
            return {"raw": out}

    def _render(self, ctx: ProvisionContext, spec: dict[str, Any]) -> str:
        w = BicepWriter()
        w.line("param location string = '" + ctx.location + "'")
        tags = {"env": ctx.environment, **(ctx.tags or {})}
        w.line("var tags = " + w.obj(tags))
        w.line("var namePrefix = '" + ctx.name_prefix + "'")
        w.line("")
        for idx, r in enumerate(spec.get("resources", []), start=1):
            rtype = r.get("type")
            emitted = False
            for e in self._emitters():
                if e.supports(rtype):
                    w.extend(e.emit(idx, r, ctx, w, self._mod))
                    emitted = True
                    break
            if not emitted:
                raise ValueError("unsupported resource type: " + str(rtype))
        return w.render()

    def _emitters(self) -> Sequence:
        return EMITTERS

    def _mod(self, ref: str) -> str:
        return resolve(ref, self._overrides)
