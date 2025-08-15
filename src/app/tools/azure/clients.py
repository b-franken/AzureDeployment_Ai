from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.cosmosdb import CosmosDBManagementClient
from azure.mgmt.keyvault import KeyVaultManagementClient
from azure.mgmt.loganalytics import LogAnalyticsManagementClient
from azure.mgmt.msi import ManagedServiceIdentityClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.privatedns import PrivateDnsManagementClient
from azure.mgmt.redis import RedisManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.sql import SqlManagementClient
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.web import WebSiteManagementClient


def _sub_id(explicit: str | None) -> str:
    sid = explicit or os.getenv("AZURE_SUBSCRIPTION_ID", "")
    if not sid:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID missing and no subscription_id provided")
    return sid


def _credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


@dataclass(frozen=True)
class Clients:
    subscription_id: str
    cred: DefaultAzureCredential
    res: ResourceManagementClient
    stor: StorageManagementClient
    net: NetworkManagementClient
    web: WebSiteManagementClient
    acr: ContainerRegistryManagementClient
    aks: ContainerServiceClient
    cmp: ComputeManagementClient
    auth: AuthorizationManagementClient
    sql: SqlManagementClient
    kv: KeyVaultManagementClient
    cosmos: CosmosDBManagementClient
    law: LogAnalyticsManagementClient
    appi: ApplicationInsightsManagementClient
    msi: ManagedServiceIdentityClient
    redis: RedisManagementClient
    pdns: PrivateDnsManagementClient

    async def run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)


_CACHE: OrderedDict[str, tuple[Clients, int]] = OrderedDict()
_CACHE_LOCK = asyncio.Lock()
_CACHE_MAX_SIZE = 8
_TOKEN_SCOPE = "https://management.azure.com/.default"


def _dispose(clients: Clients) -> None:
    for attr in (
        "res",
        "stor",
        "net",
        "web",
        "acr",
        "aks",
        "cmp",
        "auth",
        "sql",
        "kv",
        "cosmos",
        "law",
        "appi",
        "msi",
        "redis",
        "pdns",
    ):
        obj = getattr(clients, attr, None)
        close = getattr(obj, "close", None)
        if callable(close):
            close()
    cclose = getattr(clients.cred, "close", None)
    if callable(cclose):
        cclose()


async def _build_clients(sid: str) -> tuple[Clients, int]:
    cred = _credential()
    token = await asyncio.to_thread(cred.get_token, _TOKEN_SCOPE)
    expiry = token.expires_on
    return (
        Clients(
            subscription_id=sid,
            cred=cred,
            res=ResourceManagementClient(cred, sid),
            stor=StorageManagementClient(cred, sid),
            net=NetworkManagementClient(cred, sid),
            web=WebSiteManagementClient(cred, sid),
            acr=ContainerRegistryManagementClient(cred, sid),
            aks=ContainerServiceClient(cred, sid),
            cmp=ComputeManagementClient(cred, sid),
            auth=AuthorizationManagementClient(cred, sid),
            sql=SqlManagementClient(cred, sid),
            kv=KeyVaultManagementClient(cred, sid),
            cosmos=CosmosDBManagementClient(cred, sid),
            law=LogAnalyticsManagementClient(cred, sid),
            appi=ApplicationInsightsManagementClient(cred, sid),
            msi=ManagedServiceIdentityClient(cred, sid),
            redis=RedisManagementClient(cred, sid),
            pdns=PrivateDnsManagementClient(cred, sid),
        ),
        expiry,
    )


async def get_clients(subscription_id: str | None) -> Clients:
    sid = _sub_id(subscription_id)
    async with _CACHE_LOCK:
        now = int(time.time())
        entry = _CACHE.get(sid)
        if entry:
            clients, expiry = entry
            if expiry > now:
                _CACHE.move_to_end(sid)
                return clients
            _dispose(clients)
            _CACHE.pop(sid, None)
        clients, expiry = await _build_clients(sid)
        _CACHE[sid] = (clients, expiry)
        _CACHE.move_to_end(sid)
        while len(_CACHE) > _CACHE_MAX_SIZE:
            _, (old_clients, _) = _CACHE.popitem(last=False)
            _dispose(old_clients)
        return clients
