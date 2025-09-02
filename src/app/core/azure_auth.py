from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Sequence
from types import TracebackType
from typing import Any

from azure.core.credentials import AccessToken, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity import (
    AzureCliCredential,
    AzureDeveloperCliCredential,
    ChainedTokenCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
    DeviceCodeCredential,
    EnvironmentCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)
from azure.identity.aio import AzureCliCredential as AzureCliCredentialAsync
from azure.identity.aio import AzureDeveloperCliCredential as AzureDeveloperCliCredentialAsync
from azure.identity.aio import ChainedTokenCredential as ChainedTokenCredentialAsync
from azure.identity.aio import ClientSecretCredential as ClientSecretCredentialAsync
from azure.identity.aio import DefaultAzureCredential as DefaultAzureCredentialAsync
from azure.identity.aio import EnvironmentCredential as EnvironmentCredentialAsync
from azure.identity.aio import ManagedIdentityCredential as ManagedIdentityCredentialAsync
from azure.identity.aio import WorkloadIdentityCredential as WorkloadIdentityCredentialAsync

from app.core.config import AzureConfig, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_ARM_SCOPE = "https://management.azure.com/.default"
_CREDENTIAL_CACHE: TokenCredential | None = None
_ASYNC_CREDENTIAL_CACHE: AsyncTokenCredential | None = None


class _SyncToAsyncCredential(AsyncTokenCredential):
    def __init__(self, sync_cred: TokenCredential) -> None:
        self._sync_cred = sync_cred

    async def __aenter__(self) -> _SyncToAsyncCredential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.aclose()

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        start = time.perf_counter()
        try:
            return await asyncio.to_thread(self._sync_cred.get_token, *scopes, **kwargs)
        except Exception as exc:
            logger.error(
                "SyncToAsyncCredential.get_token failed",
                extra={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "scopes": list(scopes),
                },
                exc_info=True,
            )
            raise
        finally:
            logger.debug(
                "SyncToAsyncCredential.get_token completed",
                extra={"duration_ms": (time.perf_counter() - start) * 1000.0},
            )

    async def close(self) -> None:
        close = getattr(self._sync_cred, "close", None)
        if callable(close):
            await asyncio.to_thread(close)

    async def aclose(self) -> None:
        await self.close()


def _setup_environment() -> None:
    if settings.azure.tenant_id:
        os.environ.setdefault("AZURE_TENANT_ID", settings.azure.tenant_id)
    if settings.azure.client_id:
        os.environ.setdefault("AZURE_CLIENT_ID", settings.azure.client_id)
    if settings.azure.client_secret:
        os.environ.setdefault(
            "AZURE_CLIENT_SECRET", settings.azure.client_secret.get_secret_value()
        )
    if settings.azure.subscription_id:
        os.environ.setdefault("AZURE_SUBSCRIPTION_ID", settings.azure.subscription_id)


def _authority_host(cfg: AzureConfig) -> str:
    if cfg.authority_host:
        return cfg.authority_host.rstrip("/")
    cloud_hosts = {
        "public": "https://login.microsoftonline.com",
        "usgov": "https://login.microsoftonline.us",
        "china": "https://login.chinacloudapi.cn",
        "germany": "https://login.microsoftonline.de",
    }
    return cloud_hosts.get(cfg.cloud, "https://login.microsoftonline.com")


def build_credential(cfg: AzureConfig | None = None, use_cache: bool = True) -> TokenCredential:
    global _CREDENTIAL_CACHE
    if use_cache and _CREDENTIAL_CACHE is not None:
        return _CREDENTIAL_CACHE
    cfg = cfg or settings.azure
    _setup_environment()
    authority = _authority_host(cfg)
    credential: TokenCredential | None = None
    start = time.perf_counter()
    logger.debug(
        "build_credential.start",
        extra={"auth_mode": cfg.auth_mode, "authority": authority, "use_cache": use_cache},
    )
    try:
        if cfg.auth_mode == "service_principal":
            if not all([cfg.tenant_id, cfg.client_id, cfg.client_secret]):
                raise ValueError(
                    "tenant_id, client_id and client_secret are required for service_principal"
                )
            if cfg.tenant_id is None or cfg.client_id is None or cfg.client_secret is None:
                raise ValueError("Required credentials cannot be None for service principal")

            assert cfg.tenant_id is not None
            assert cfg.client_id is not None
            assert cfg.client_secret is not None

            credential = ClientSecretCredential(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                client_secret=cfg.client_secret.get_secret_value(),
                authority=authority,
            )
        elif cfg.auth_mode == "managed_identity":
            credential = ManagedIdentityCredential(client_id=cfg.user_assigned_identity_client_id)
        elif cfg.auth_mode == "azure_cli":
            credential = AzureCliCredential()
        elif cfg.auth_mode == "device_code":
            if not cfg.tenant_id:
                raise ValueError("tenant_id is required for device_code authentication")
            if cfg.client_id is None:
                raise ValueError("client_id cannot be None for device_code authentication")

            assert cfg.client_id is not None

            credential = DeviceCodeCredential(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                authority=authority,
            )
        elif cfg.auth_mode == "workload_identity":
            if not all([cfg.tenant_id, cfg.client_id, cfg.workload_identity_token_file]):
                raise ValueError(
                    "tenant_id, client_id and workload_identity_token_file are required"
                )
            credential = WorkloadIdentityCredential(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                token_file_path=cfg.workload_identity_token_file,
                authority=authority,
            )
        elif cfg.auth_mode == "environment":
            credential = EnvironmentCredential(authority=authority)
        else:
            credentials: list[TokenCredential] = []
            try:
                credentials.append(EnvironmentCredential(authority=authority))
            except Exception as e:
                logger.debug(
                    "EnvironmentCredential unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    credential_type="EnvironmentCredential",
                )
            try:
                credentials.append(ManagedIdentityCredential())
            except Exception as e:
                logger.debug(
                    "ManagedIdentityCredential unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    credential_type="ManagedIdentityCredential",
                )
            if cfg.enable_cli_fallback:
                try:
                    credentials.append(AzureCliCredential())
                except Exception as e:
                    logger.debug(
                        "AzureCliCredential unavailable",
                        error=str(e),
                        error_type=type(e).__name__,
                        credential_type="AzureCliCredential",
                    )
            try:
                credentials.append(AzureDeveloperCliCredential())
            except Exception as e:
                logger.debug(
                    "AzureDeveloperCliCredential unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    credential_type="AzureDeveloperCliCredential",
                )
            credential = (
                ChainedTokenCredential(*credentials)
                if credentials
                else DefaultAzureCredential(authority=authority)
            )
    except Exception as exc:
        logger.exception(
            "build_credential error, falling back to DefaultAzureCredential",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
        credential = DefaultAzureCredential(authority=authority)
    if credential and use_cache:
        _CREDENTIAL_CACHE = credential
    logger.debug(
        "build_credential.end",
        extra={"duration_ms": (time.perf_counter() - start) * 1000.0, "cached": use_cache},
    )
    return credential


async def build_async_credential(
    cfg: AzureConfig | None = None, use_cache: bool = True
) -> AsyncTokenCredential:
    global _ASYNC_CREDENTIAL_CACHE
    if use_cache and _ASYNC_CREDENTIAL_CACHE is not None:
        return _ASYNC_CREDENTIAL_CACHE
    cfg = cfg or settings.azure
    _setup_environment()
    authority = _authority_host(cfg)
    credential: AsyncTokenCredential | None = None
    start = time.perf_counter()
    logger.debug(
        "build_async_credential.start",
        extra={"auth_mode": cfg.auth_mode, "authority": authority, "use_cache": use_cache},
    )
    try:
        if cfg.auth_mode == "service_principal":
            if not all([cfg.tenant_id, cfg.client_id, cfg.client_secret]):
                raise ValueError(
                    "tenant_id, client_id and client_secret are required for service_principal"
                )
            if cfg.tenant_id is None or cfg.client_id is None or cfg.client_secret is None:
                raise ValueError("Required credentials cannot be None for service principal")

            assert cfg.tenant_id is not None
            assert cfg.client_id is not None
            assert cfg.client_secret is not None

            credential = ClientSecretCredentialAsync(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                client_secret=cfg.client_secret.get_secret_value(),
                authority=authority,
            )
        elif cfg.auth_mode == "managed_identity":
            credential = ManagedIdentityCredentialAsync(
                client_id=cfg.user_assigned_identity_client_id
            )
        elif cfg.auth_mode == "azure_cli":
            credential = AzureCliCredentialAsync()
        elif cfg.auth_mode == "device_code":
            if not cfg.tenant_id:
                raise ValueError("tenant_id is required for device_code authentication")
            if cfg.client_id is None:
                raise ValueError("client_id cannot be None for device_code authentication")

            assert cfg.client_id is not None

            sync_dc = DeviceCodeCredential(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                authority=authority,
            )
            credential = _SyncToAsyncCredential(sync_dc)
        elif cfg.auth_mode == "workload_identity":
            if not all([cfg.tenant_id, cfg.client_id, cfg.workload_identity_token_file]):
                raise ValueError(
                    "tenant_id, client_id and workload_identity_token_file are required"
                )
            credential = WorkloadIdentityCredentialAsync(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                token_file_path=cfg.workload_identity_token_file,
                authority=authority,
            )
        elif cfg.auth_mode == "environment":
            credential = EnvironmentCredentialAsync(authority=authority)
        else:
            credentials: list[AsyncTokenCredential] = []
            try:
                credentials.append(EnvironmentCredentialAsync(authority=authority))
            except Exception as e:
                logger.debug(
                    "EnvironmentCredentialAsync unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    credential_type="EnvironmentCredentialAsync",
                )
            try:
                credentials.append(ManagedIdentityCredentialAsync())
            except Exception as e:
                logger.debug(
                    "ManagedIdentityCredentialAsync unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    credential_type="ManagedIdentityCredentialAsync",
                )
            if cfg.enable_cli_fallback:
                try:
                    credentials.append(AzureCliCredentialAsync())
                except Exception as e:
                    logger.debug(
                        "AzureCliCredentialAsync unavailable",
                        error=str(e),
                        error_type=type(e).__name__,
                        credential_type="AzureCliCredentialAsync",
                    )
            try:
                credentials.append(AzureDeveloperCliCredentialAsync())
            except Exception as e:
                logger.debug(
                    "AzureDeveloperCliCredentialAsync unavailable",
                    error=str(e),
                    error_type=type(e).__name__,
                    credential_type="AzureDeveloperCliCredentialAsync",
                )
            credential = (
                ChainedTokenCredentialAsync(*credentials)
                if credentials
                else DefaultAzureCredentialAsync(authority=authority)
            )
    except Exception as exc:
        logger.exception(
            "build_async_credential error, falling back to DefaultAzureCredentialAsync",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
        credential = DefaultAzureCredentialAsync(authority=authority)
    if credential and use_cache:
        _ASYNC_CREDENTIAL_CACHE = credential
    logger.debug(
        "build_async_credential.end",
        extra={"duration_ms": (time.perf_counter() - start) * 1000.0, "cached": use_cache},
    )
    return credential


def arm_scopes() -> Sequence[str]:
    return [_ARM_SCOPE]


def clear_credential_cache() -> None:
    global _CREDENTIAL_CACHE, _ASYNC_CREDENTIAL_CACHE
    _CREDENTIAL_CACHE = None
    _ASYNC_CREDENTIAL_CACHE = None


async def test_credential(credential: TokenCredential | None = None) -> bool:
    cred = credential or build_credential()
    try:
        token = await asyncio.to_thread(cred.get_token, _ARM_SCOPE)
        return bool(getattr(token, "token", None))
    except Exception as exc:
        logger.error(
            "test_credential failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
            exc_info=True,
        )
        return False


async def test_credential_async(credential: AsyncTokenCredential | None = None) -> bool:
    cred = credential or await build_async_credential()
    try:
        token = await cred.get_token(_ARM_SCOPE)
        return bool(getattr(token, "token", None))
    except Exception as exc:
        logger.error(
            "test_credential_async failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
            exc_info=True,
        )
        return False
