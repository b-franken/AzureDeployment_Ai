from __future__ import annotations

from typing import Sequence
from azure.identity import (
    ClientSecretCredential,
    ManagedIdentityCredential,
    AzureCliCredential,
    DeviceCodeCredential,
    AzureDeveloperCliCredential,
    WorkloadIdentityCredential,
    EnvironmentCredential,
    DefaultAzureCredential,
)
from azure.core.credentials import TokenCredential

from app.core.config import settings, AzureConfig

_ARM_SCOPE = "https://management.azure.com/.default"


def _authority_host(cfg: AzureConfig) -> str:
    if cfg.authority_host:
        return cfg.authority_host.rstrip("/")
    if cfg.cloud == "public":
        return "https://login.microsoftonline.com"
    if cfg.cloud == "usgov":
        return "https://login.microsoftonline.us"
    if cfg.cloud == "china":
        return "https://login.chinacloudapi.cn"
    if cfg.cloud == "germany":
        return "https://login.microsoftonline.de"
    return "https://login.microsoftonline.com"


def build_credential(cfg: AzureConfig | None = None) -> TokenCredential:
    cfg = cfg or settings.azure
    if cfg.auth_mode == "service_principal":
        if not (cfg.tenant_id and cfg.client_id and cfg.client_secret):
            raise ValueError(
                "tenant_id, client_id and client_secret are required for service_principal")
        return ClientSecretCredential(
            tenant_id=cfg.tenant_id,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret.get_secret_value(),
            authority=_authority_host(cfg),
        )
    if cfg.auth_mode == "managed_identity":
        return ManagedIdentityCredential(client_id=cfg.user_assigned_identity_client_id)
    if cfg.auth_mode == "azure_cli":
        return AzureCliCredential()
    if cfg.auth_mode == "device_code":
        return DeviceCodeCredential(tenant_id=cfg.tenant_id, client_id=cfg.client_id)
    if cfg.auth_mode == "workload_identity":
        if not (cfg.tenant_id and cfg.client_id and cfg.workload_identity_token_file):
            raise ValueError(
                "tenant_id, client_id and workload_identity_token_file are required for workload_identity")
        return WorkloadIdentityCredential(
            tenant_id=cfg.tenant_id,
            client_id=cfg.client_id,
            token_file_path=cfg.workload_identity_token_file,
            authority=_authority_host(cfg),
        )
    if cfg.auth_mode == "environment":
        return EnvironmentCredential(authority=_authority_host(cfg))
    return DefaultAzureCredential(authority=_authority_host(cfg))


def arm_scopes() -> Sequence[str]:
    return [_ARM_SCOPE]
