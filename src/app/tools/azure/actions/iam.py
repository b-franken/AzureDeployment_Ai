from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from azure.core.credentials import AccessToken, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError

from ..clients import Clients

logger = logging.getLogger(__name__)


async def _get_token_str(cred: TokenCredential | AsyncTokenCredential, scope: str) -> str:
    if isinstance(cred, AsyncTokenCredential):
        tok: AccessToken = await cred.get_token(scope)
    else:
        tok = await asyncio.to_thread(cred.get_token, scope)
    return tok.token


async def create_service_principal(
    *,
    clients: Clients,
    display_name: str,
    password: str | None = None,
    dry_run: bool = False,
) -> tuple[str, object]:
    if dry_run:
        return "plan", {"display_name": display_name, "password": bool(password)}
    try:
        token = await _get_token_str(clients.cred, "https://graph.microsoft.com/.default")
    except Exception as exc:
        logger.error("Failed to acquire Graph token: %s", str(exc))
        return "error", {"message": "failed to acquire graph token"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            app_res = await client.post(
                "https://graph.microsoft.com/v1.0/applications",
                headers=headers,
                json={"displayName": display_name},
            )
            app_res.raise_for_status()
            app = app_res.json()
            sp_res = await client.post(
                "https://graph.microsoft.com/v1.0/servicePrincipals",
                headers=headers,
                json={"appId": app["appId"]},
            )
            sp_res.raise_for_status()
            sp = sp_res.json()
            secret_res: dict[str, Any] | None = None
            if password:
                sres = await client.post(
                    f"https://graph.microsoft.com/v1.0/applications/{app['id']}/addPassword",
                    headers=headers,
                    json={"passwordCredential": {"displayName": "default"}},
                )
                sres.raise_for_status()
                secret_res = sres.json()
        return "created", {
            "app": {"id": app["id"], "appId": app["appId"]},
            "sp": {"id": sp["id"]},
            "password": bool(secret_res),
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        logger.error("Graph request failed: %s", str(exc))
        return "error", {"code": status, "message": "graph request failed"}
    except httpx.RequestError as exc:
        logger.error("Graph request error: %s", str(exc))
        return "error", {"message": "graph request error"}


async def assign_role(
    *,
    clients: Clients,
    scope: str,
    principal_object_id: str,
    role_definition_id: str | None = None,
    role_name: str | None = None,
    dry_run: bool = False,
) -> tuple[str, object]:
    if dry_run:
        return "plan", {
            "scope": scope,
            "principal_id": principal_object_id,
            "role": role_definition_id or role_name,
        }
    role_id = role_definition_id
    if not role_id and role_name:
        try:
            safe_name = role_name.replace("'", "''")
            defs = await clients.run(
                clients.auth.role_definitions.list,
                scope,
                filter=f"roleName eq '{safe_name}'",
            )
            defs_list = list(defs)
        except HttpResponseError as exc:
            logger.error("Role definition lookup failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}
        if len(defs_list) == 0:
            return "error", {"message": "role not found", "role_name": role_name}
        if len(defs_list) > 1:
            return "error", {"message": "role ambiguous", "role_name": role_name}
        role_id = defs_list[0].id
    if not role_id:
        return "error", {"message": "role_id is required"}
    try:
        existing = list(
            await clients.run(
                clients.auth.role_assignments.list_for_scope,
                scope,
                filter=f"assignedTo('{principal_object_id}')",
            )
        )
    except HttpResponseError as exc:
        logger.error("Role assignment list failed: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}
    for ra in existing:
        rid = ra.properties.role_definition_id if getattr(ra, "properties", None) else None
        if rid and rid.endswith(role_id.split("/")[-1]):
            return "exists", ra.as_dict()
    assign_id = str(uuid.uuid4())
    try:
        ra = await clients.run(
            clients.auth.role_assignments.create,
            scope,
            assign_id,
            {
                "properties": {
                    "role_definition_id": role_id,
                    "principal_id": principal_object_id,
                }
            },
        )
        return "created", ra.as_dict()
    except HttpResponseError as exc:
        logger.error("Role assignment create failed: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}
