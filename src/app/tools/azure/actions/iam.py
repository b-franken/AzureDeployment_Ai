from __future__ import annotations

import uuid

import httpx

from ..clients import Clients


async def create_service_principal(
    *,
    clients: Clients,
    display_name: str,
    password: str | None = None,
    dry_run: bool = False,
) -> tuple[str, object]:
    if dry_run:
        return "plan", {"display_name": display_name, "password": bool(password)}
    token = clients.cred.get_token("https://graph.microsoft.com/.default").token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
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
        secret_res = None
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
        safe_name = role_name.replace("'", "''")
        defs = await clients.run(
            clients.auth.role_definitions.list,
            scope,
            filter=f"roleName eq '{safe_name}'",
        )
        defs_list = list(defs)
        if len(defs_list) == 0:
            return "error", {"message": "role not found", "role_name": role_name}
        if len(defs_list) > 1:
            return "error", {"message": "role ambiguous", "role_name": role_name}
        role_id = defs_list[0].id
    if not role_id:
        return "error", {"message": "role_id is required"}
    existing = list(
        await clients.run(
            clients.auth.role_assignments.list_for_scope,
            scope,
            filter=f"assignedTo('{principal_object_id}')",
        )
    )
    for ra in existing:
        rid = ra.properties.role_definition_id if getattr(ra, "properties", None) else None
        if rid and rid.endswith(role_id.split("/")[-1]):
            return "exists", ra.as_dict()
    assign_id = str(uuid.uuid4())
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
