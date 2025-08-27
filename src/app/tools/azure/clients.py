from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from random import random
from typing import Any

from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.mgmt.applicationinsights.aio import ApplicationInsightsManagementClient
from azure.mgmt.authorization.aio import AuthorizationManagementClient
from azure.mgmt.compute.aio import ComputeManagementClient
from azure.mgmt.containerregistry.aio import ContainerRegistryManagementClient
from azure.mgmt.containerservice.aio import ContainerServiceClient
from azure.mgmt.cosmosdb.aio import CosmosDBManagementClient
from azure.mgmt.keyvault.aio import KeyVaultManagementClient
from azure.mgmt.loganalytics.aio import LogAnalyticsManagementClient
from azure.mgmt.msi.aio import ManagedServiceIdentityClient
from azure.mgmt.network.aio import NetworkManagementClient
from azure.mgmt.privatedns.aio import PrivateDnsManagementClient
from azure.mgmt.redis.aio import RedisManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.sql.aio import SqlManagementClient
from azure.mgmt.storage.aio import StorageManagementClient
from azure.mgmt.web.aio import WebSiteManagementClient

from app.core.azure_auth import arm_scopes, build_async_credential, build_credential
from app.core.config import settings

logger = logging.getLogger(__name__)


def _sub_id(explicit: str | None) -> str:
    sid = explicit or settings.azure.subscription_id
    if not sid:
        raise RuntimeError(
            f"subscription_id missing and no subscription_id provided. "
            f"Explicit: {explicit}, Settings: {settings.azure.subscription_id}. "
            f"Please configure settings.azure.subscription_id or pass subscription_id via context."
        )
    return sid


async def _credential_async() -> AsyncTokenCredential:
    return await build_async_credential()


def _credential_sync() -> TokenCredential:
    return build_credential()


@dataclass(frozen=True)
class Clients:
    subscription_id: str
    cred: AsyncTokenCredential
    cred_sync: TokenCredential
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

    async def run(
        self, fn: Callable[..., Any] | Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        if inspect.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):
            return await res
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def close(self) -> None:
        # Close client connections first
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
            try:
                obj = getattr(self, attr, None)
                if obj is None:
                    continue
                close = getattr(obj, "close", None)
                if callable(close):
                    if inspect.iscoroutinefunction(close):
                        await close()
                    else:
                        await asyncio.to_thread(close)
            except Exception as e:
                # Log individual client close errors but don't fail the whole cleanup
                logger.debug(f"Error closing client {attr}: {e}")

        # Close credentials last
        try:
            cclose = getattr(self.cred, "close", None)
            if callable(cclose):
                await cclose()
        except Exception as e:
            logger.debug(f"Error closing async credential: {e}")

        try:
            sclose = getattr(self.cred_sync, "close", None)
            if callable(sclose):
                await asyncio.to_thread(sclose)
        except Exception as e:
            logger.debug(f"Error closing sync credential: {e}")


_CACHE: OrderedDict[str, tuple[Clients, int]] = OrderedDict()
_CACHE_LOCK = asyncio.Lock()
_CACHE_MAX_SIZE = 8
_TOKEN_SCOPE = arm_scopes()[0]
_EXPIRY_MARGIN_SECONDS = 5 * 60
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


async def _dispose(clients: Clients) -> None:
    try:
        # Close all client connections gracefully
        await clients.close()
    except Exception as exc:
        # Log but don't propagate disposal errors as they're not critical
        logger.warning(
            "azure_clients.dispose_error",
            extra={"subscription_id": clients.subscription_id, "error": str(exc)},
            exc_info=True,
        )


async def _build_clients(sid: str) -> tuple[Clients, int]:
    logger.debug("azure_clients.build.start", extra={"subscription_id": sid})
    # Create fresh credentials for each client instance to avoid shared transport issues
    cred_async = await build_async_credential(use_cache=False)
    try:
        token = await cred_async.get_token(_TOKEN_SCOPE)
        expiry = int(token.expires_on) - _EXPIRY_MARGIN_SECONDS
        cred_sync = build_credential(use_cache=False)

        clients = Clients(
            subscription_id=sid,
            cred=cred_async,
            cred_sync=cred_sync,
            res=ResourceManagementClient(cred_sync, sid),
            stor=StorageManagementClient(cred_async, sid),
            net=NetworkManagementClient(cred_async, sid),
            web=WebSiteManagementClient(cred_async, sid),
            acr=ContainerRegistryManagementClient(cred_async, sid),
            aks=ContainerServiceClient(cred_async, sid),
            cmp=ComputeManagementClient(cred_async, sid),
            auth=AuthorizationManagementClient(cred_async, sid),
            sql=SqlManagementClient(cred_async, sid),
            kv=KeyVaultManagementClient(cred_async, sid),
            cosmos=CosmosDBManagementClient(cred_async, sid),
            law=LogAnalyticsManagementClient(cred_async, sid),
            appi=ApplicationInsightsManagementClient(cred_async, sid),
            msi=ManagedServiceIdentityClient(cred_async, sid),
            redis=RedisManagementClient(cred_async, sid),
            pdns=PrivateDnsManagementClient(cred_async, sid),
        )
        logger.debug(
            "azure_clients.build.end",
            extra={"subscription_id": sid, "expires_in_s": expiry - int(time.time())},
        )
        return clients, expiry
    except Exception as exc:
        # Only close credentials if client creation failed
        try:
            close_async = getattr(cred_async, "close", None)
            if callable(close_async):
                await close_async()
        except Exception:
            pass  # Ignore cleanup errors
        logger.error(
            "azure_clients.build.error",
            extra={"subscription_id": sid, "error_type": type(exc).__name__, "error": str(exc)},
            exc_info=True,
        )
        raise


async def get_clients(subscription_id: str | None) -> Clients:
    sid = _sub_id(subscription_id)
    async with _CACHE_LOCK:
        now = int(time.time())
        entry = _CACHE.get(sid)
        if entry:
            clients, expiry = entry
            if expiry <= now:
                # Schedule disposal asynchronously to avoid blocking
                asyncio.create_task(_dispose(clients))
                _CACHE.pop(sid, None)
                logger.debug("azure_clients.cache.expired", extra={"subscription_id": sid})
            else:
                _CACHE.move_to_end(sid)
                logger.debug("azure_clients.cache.hit", extra={"subscription_id": sid})
                return clients

        # Build new clients
        try:
            clients, expiry = await _build_clients(sid)
            _CACHE[sid] = (clients, expiry)
            _CACHE.move_to_end(sid)

            # Clean up old entries asynchronously
            while len(_CACHE) > _CACHE_MAX_SIZE:
                _, (old_clients, _) = _CACHE.popitem(last=False)
                asyncio.create_task(_dispose(old_clients))

            logger.debug("azure_clients.cache.miss", extra={"subscription_id": sid})
            return clients
        except Exception as exc:
            logger.error(
                "azure_clients.get_clients.error",
                extra={"subscription_id": sid, "error_type": type(exc).__name__, "error": str(exc)},
                exc_info=True,
            )
            raise


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
    if isinstance(e, ServiceRequestError | ServiceResponseError | TimeoutError | OSError):
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
    fn: Callable[..., Any] | Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    poller = await clients.run(fn, *args, **kwargs)
    if not _is_poller(poller):
        return poller
    attempt = 0
    while True:
        try:
            if inspect.iscoroutinefunction(getattr(poller, "result", None)):
                return await poller.result()
            res = poller.result()
            if inspect.isawaitable(res):
                return await res
            return await asyncio.to_thread(poller.result)
        except BaseException as e:
            retryable, code, sc = _classify(e)
            if not retryable or attempt >= _RETRY_MAX_ATTEMPTS - 1:
                logger.error(
                    "azure_clients.poller.error",
                    extra={
                        "subscription_id": clients.subscription_id,
                        "error_type": type(e).__name__,
                        "error_code": code,
                        "http_status": sc,
                        "attempt": attempt + 1,
                    },
                    exc_info=True,
                )
                raise AzureOperationError(
                    code=code, message=str(e), status_code=sc, retryable=retryable
                ) from e
            base = min(_RETRY_BASE_SECONDS * (2**attempt), _RETRY_CAP_SECONDS)
            delay = base * (0.5 + random() * 0.5)
            attempt += 1
            logger.debug(
                "azure_clients.poller.retry",
                extra={
                    "subscription_id": clients.subscription_id,
                    "attempt": attempt,
                    "delay_s": delay,
                    "http_status": sc,
                    "error_code": code,
                },
            )
            await asyncio.sleep(delay)
