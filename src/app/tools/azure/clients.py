from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from random import random
from typing import Any

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
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
_RETRY_MAX_ATTEMPTS = int(os.getenv("AZURE_POLL_RETRY_MAX", "6"))
_RETRY_BASE_SECONDS = float(os.getenv("AZURE_POLL_RETRY_BASE", "1.0"))
_RETRY_CAP_SECONDS = float(os.getenv("AZURE_POLL_RETRY_CAP", "30.0"))


@dataclass(frozen=True)
class AzureOperationError(Exception):
    code: str
    message: str
    status_code: int | None
    retryable: bool

    def __post_init__(self) -> None:
        super().__init__(self.message)


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
    expiry = int(token.expires_on)
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


def _http_status(e: BaseException) -> int | None:
    if isinstance(e, HttpResponseError):
        sc = getattr(e, "status_code", None)
        if sc is not None:
            return int(sc)
        resp = getattr(e, "response", None)
        if resp is not None:
            sc = getattr(resp, "status_code", None)
            if sc is not None:
                return int(sc)
    return None


def _classify(e: BaseException) -> tuple[bool, str, int | None]:
    if isinstance(e, ClientAuthenticationError):
        return False, "auth_error", _http_status(e)
    if isinstance(
        e,
        ServiceRequestError | ServiceResponseError | TimeoutError | OSError,
    ):
        return True, "transient_io", _http_status(e)
    if isinstance(e, HttpResponseError):
        sc = _http_status(e)
        if sc in (408, 429) or (sc is not None and 500 <= sc <= 599):
            return True, f"http_{sc}", sc
        return False, f"http_{sc}" if sc is not None else "http_error", sc
    if isinstance(e, AzureError):
        return False, "azure_error", _http_status(e)
    return False, "unknown_error", _http_status(e)


def _is_poller(obj: Any) -> bool:
    return hasattr(obj, "result") and hasattr(obj, "status")


async def run_poller(
    clients: Clients,
    fn: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    poller = await clients.run(fn, *args, **kwargs)
    if not _is_poller(poller):
        return poller
    attempt = 0
    while True:
        try:
            return await clients.run(poller.result)
        except BaseException as e:
            retryable, code, sc = _classify(e)
            if not retryable or attempt >= _RETRY_MAX_ATTEMPTS - 1:
                raise AzureOperationError(
                    code=code,
                    message=str(e),
                    status_code=sc,
                    retryable=retryable,
                ) from e
            base = min(_RETRY_BASE_SECONDS * (2**attempt), _RETRY_CAP_SECONDS)
            delay = base * (0.5 + random() * 0.5)
            attempt += 1
            await asyncio.sleep(delay)
