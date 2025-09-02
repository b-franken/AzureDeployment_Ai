from __future__ import annotations

import asyncio
import logging
from typing import Any

from azure.core.credentials import AccessToken, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError

from ..clients import Clients
from ..validators import validate_name

logger = logging.getLogger(__name__)


class _AsyncToSyncCredential(TokenCredential):
    def __init__(self, async_cred: AsyncTokenCredential) -> None:
        self._async_cred = async_cred

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._async_cred.get_token(*scopes, **kwargs))
        finally:
            loop.close()

    def close(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            aclose = getattr(self._async_cred, "aclose", None)
            if callable(aclose):
                loop.run_until_complete(aclose())
        finally:
            loop.close()


def _ensure_sync_credential(cred: TokenCredential | AsyncTokenCredential) -> TokenCredential:
    if isinstance(cred, AsyncTokenCredential):
        return _AsyncToSyncCredential(cred)
    return cred


async def create_policy_definition(
    *,
    clients: Clients,
    name: str,
    display_name: str,
    description: str,
    policy_type: str = "Custom",
    mode: str = "All",
    policy_rule: dict[str, Any],
    parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid policy definition name"}

    if dry_run:
        return "plan", {
            "name": name,
            "display_name": display_name,
            "description": description,
            "policy_type": policy_type,
            "mode": mode,
            "policy_rule": policy_rule,
            "parameters": parameters or {},
            "metadata": metadata or {},
        }

    from azure.mgmt.resource import PolicyClient
    from azure.mgmt.resource.policy.models import PolicyDefinition

    sync_cred = _ensure_sync_credential(clients.cred)
    policy_client = PolicyClient(sync_cred, clients.subscription_id)

    try:
        existing = await clients.run(
            policy_client.policy_definitions.get,
            name,
        )
        if existing and not force:
            return "exists", existing.as_dict()
    except HttpResponseError as exc:
        if exc.status_code != 404:
            logger.error("Policy definition retrieval failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}

    policy_definition = PolicyDefinition(
        policy_type=policy_type,
        mode=mode,
        display_name=display_name,
        description=description,
        policy_rule=policy_rule,
        parameters=parameters,
        metadata=metadata or {"version": "1.0.0", "category": "Custom"},
    )

    result = await clients.run(
        policy_client.policy_definitions.create_or_update,
        name,
        policy_definition,
    )

    return "created", result.as_dict()


async def create_policy_assignment(
    *,
    clients: Clients,
    scope: str,
    name: str,
    display_name: str,
    policy_definition_id: str,
    parameters: dict[str, Any] | None = None,
    enforcement_mode: str = "Default",
    non_compliance_messages: list[dict[str, Any]] | None = None,
    location: str | None = None,
    identity: dict[str, Any] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid policy assignment name"}

    if dry_run:
        return "plan", {
            "name": name,
            "scope": scope,
            "display_name": display_name,
            "policy_definition_id": policy_definition_id,
            "parameters": parameters or {},
            "enforcement_mode": enforcement_mode,
            "location": location,
        }

    from typing import cast

    from azure.mgmt.resource import PolicyClient
    from azure.mgmt.resource.policy.models import (
        Identity,
        NonComplianceMessage,
        PolicyAssignment,
    )

    sync_cred = _ensure_sync_credential(clients.cred)
    policy_client = PolicyClient(sync_cred, clients.subscription_id)

    try:
        existing = await clients.run(
            policy_client.policy_assignments.get,
            scope,
            name,
        )
        if existing and not force:
            return "exists", existing.as_dict()
    except HttpResponseError as exc:
        if exc.status_code != 404:
            logger.error("Policy assignment retrieval failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}

    ncm_typed = cast(
        "list[NonComplianceMessage] | None",
        non_compliance_messages,
    )
    identity_typed = cast("Identity | None", identity)

    policy_assignment = PolicyAssignment(
        display_name=display_name,
        policy_definition_id=policy_definition_id,
        parameters=parameters,
        enforcement_mode=enforcement_mode,
        non_compliance_messages=ncm_typed,
        location=location,
        identity=identity_typed,
    )

    result = await clients.run(
        policy_client.policy_assignments.create,
        scope,
        name,
        policy_assignment,
    )

    return "created", result.as_dict()


async def create_initiative_definition(
    *,
    clients: Clients,
    name: str,
    display_name: str,
    description: str,
    policy_definitions: list[dict[str, Any]],
    policy_type: str = "Custom",
    parameters: dict[str, Any] | None = None,
    policy_definition_groups: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid initiative definition name"}

    if dry_run:
        return "plan", {
            "name": name,
            "display_name": display_name,
            "description": description,
            "policy_definitions": policy_definitions,
            "policy_type": policy_type,
            "parameters": parameters or {},
            "policy_definition_groups": policy_definition_groups or [],
            "metadata": metadata or {},
        }

    from typing import cast

    from azure.mgmt.resource import PolicyClient
    from azure.mgmt.resource.policy.models import (
        PolicyDefinitionGroup,
        PolicyDefinitionReference,
        PolicySetDefinition,
    )

    sync_cred = _ensure_sync_credential(clients.cred)
    policy_client = PolicyClient(sync_cred, clients.subscription_id)

    try:
        existing = await clients.run(
            policy_client.policy_set_definitions.get,
            name,
        )
        if existing and not force:
            return "exists", existing.as_dict()
    except HttpResponseError as exc:
        if exc.status_code != 404:
            logger.error("Initiative retrieval failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}

    policy_definitions_typed = cast(
        "list[PolicyDefinitionReference] | None",
        policy_definitions,
    )
    policy_definition_groups_typed = cast(
        "list[PolicyDefinitionGroup] | None",
        policy_definition_groups,
    )

    initiative = PolicySetDefinition(
        policy_type=policy_type,
        display_name=display_name,
        description=description,
        policy_definitions=policy_definitions_typed,
        parameters=parameters,
        policy_definition_groups=policy_definition_groups_typed,
        metadata=metadata or {"version": "1.0.0", "category": "Custom"},
    )

    result = await clients.run(
        policy_client.policy_set_definitions.create_or_update,
        name,
        initiative,
    )

    return "created", result.as_dict()
