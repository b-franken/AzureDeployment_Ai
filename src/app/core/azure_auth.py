from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import Any

from azure.core.credentials import TokenCredential
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
from azure.identity.aio import (
    AzureCliCredential as AzureCliCredentialAsync,
)
from azure.identity.aio import (
    AzureDeveloperCliCredential as AzureDeveloperCliCredentialAsync,
)
from azure.identity.aio import (
    ChainedTokenCredential as ChainedTokenCredentialAsync,
)
from azure.identity.aio import (
    ClientSecretCredential as ClientSecretCredentialAsync,
)
from azure.identity.aio import (
    DefaultAzureCredential as DefaultAzureCredentialAsync,
)
from azure.identity.aio import (
    EnvironmentCredential as EnvironmentCredentialAsync,
)
from azure.identity.aio import (
    ManagedIdentityCredential as ManagedIdentityCredentialAsync,
)
from azure.identity.aio import (
    WorkloadIdentityCredential as WorkloadIdentityCredentialAsync,
)

from app.core.config import AzureConfig, settings

logger = logging.getLogger(__name__)

_ARM_SCOPE = "https://management.azure.com/.default"
_CREDENTIAL_CACHE: TokenCredential | None = None
_ASYNC_CREDENTIAL_CACHE: AsyncTokenCredential | None = None


class _SyncToAsyncCredential(AsyncTokenCredential):
    def __init__(self, sync_cred: TokenCredential) -> None:
        self._sync_cred = sync_cred

    async def get_token(self, *scopes: str, **kwargs: Any):
        return await asyncio.to_thread(self._sync_cred.get_token, *scopes, **kwargs)

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
        os.environ.setdefault("AZURE_SUBSCRIPTION_ID",
                              settings.azure.subscription_id)


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
    try:
        if cfg.auth_mode == "service_principal":
            if not all([cfg.tenant_id, cfg.client_id, cfg.client_secret]):
                raise ValueError(
                    "tenant_id, client_id and client_secret are required for service_principal"
                )
            credential = ClientSecretCredential(
                tenant_id=cfg.tenant_id,
                client_id=cfg.client_id,
                client_secret=cfg.client_secret.get_secret_value(),
                authority=authority,
            )
        elif cfg.auth_mode == "managed_identity":
            credential = ManagedIdentityCredential(
                client_id=cfg.user_assigned_identity_client_id)
        elif cfg.auth_mode == "azure_cli":
            credential = AzureCliCredential()
        elif cfg.auth_mode == "device_code":
            if not cfg.tenant_id:
                raise ValueError(
                    "tenant_id is required for device_code authentication")
            credential = DeviceCodeCredential(
                tenant_id=cfg.tenant_id, client_id=cfg.client_id, authority=authority
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
            credentials = []
            try:
                credentials.append(EnvironmentCredential(authority=authority))
            except Exception:
                pass
            try:
                credentials.append(ManagedIdentityCredential())
            except Exception:
                pass
            if cfg.enable_cli_fallback:
                try:
                    credentials.append(AzureCliCredential())
                except Exception:
                    pass
            try:
                credentials.append(AzureDeveloperCliCredential())
            except Exception:
                pass
            credential = (
                ChainedTokenCredential(*credentials)
                if credentials
                else DefaultAzureCredential(authority=authority)
            )
    except Exception:
        credential = DefaultAzureCredential(authority=authority)
    if credential and use_cache:
        _CREDENTIAL_CACHE = credential
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
    try:
        if cfg.auth_mode == "service_principal":
            if not all([cfg.tenant_id, cfg.client_id, cfg.client_secret]):
                raise ValueError(
                    "tenant_id, client_id and client_secret are required for service_principal"
                )
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
                raise ValueError(
                    "tenant_id is required for device_code authentication")
            sync_dc = DeviceCodeCredential(
                tenant_id=cfg.tenant_id, client_id=cfg.client_id, authority=authority
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
            credentials = []
            try:
                credentials.append(
                    EnvironmentCredentialAsync(authority=authority))
            except Exception:
                pass
            try:
                credentials.append(ManagedIdentityCredentialAsync())
            except Exception:
                pass
            if cfg.enable_cli_fallback:
                try:
                    credentials.append(AzureCliCredentialAsync())
                except Exception:
                    pass
            try:
                credentials.append(AzureDeveloperCliCredentialAsync())
            except Exception:
                pass
            credential = (
                ChainedTokenCredentialAsync(*credentials)
                if credentials
                else DefaultAzureCredentialAsync(authority=authority)
            )
    except Exception:
        credential = DefaultAzureCredentialAsync(authority=authority)
    if credential and use_cache:
        _ASYNC_CREDENTIAL_CACHE = credential
    return credential


def arm_scopes() -> Sequence[str]:
    return [_ARM_SCOPE]


def clear_credential_cache() -> None:
    global _CREDENTIAL_CACHE, _ASYNC_CREDENTIAL_CACHE
    _CREDENTIAL_CACHE = None
    _ASYNC_CREDENTIAL_CACHE = None


async def test_credential(credential: TokenCredential | None = None) -> bool:
    if credential is None:
        credential = build_credential()
    try:
        token = await asyncio.to_thread(credential.get_token, _ARM_SCOPE)
        return token is not None and token.token is not None
    except Exception:
        return False


async def test_credential_async(credential: AsyncTokenCredential | None = None) -> bool:
    if credential is None:
        credential = await build_async_credential()
    try:
        token = await credential.get_token(_ARM_SCOPE)
        return token is not None and token.token is not None
    except Exception:
        return False
