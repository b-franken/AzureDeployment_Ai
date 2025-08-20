import logging
import os
from collections.abc import Sequence

from azure.core.credentials import TokenCredential
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

from app.core.config import AzureConfig, settings

logger = logging.getLogger(__name__)

_ARM_SCOPE = "https://management.azure.com/.default"
_CREDENTIAL_CACHE: TokenCredential | None = None


def _setup_environment() -> None:
    """Set up Azure environment variables from settings"""
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
    """Get the Azure authority host URL"""
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
    """
    Build Azure credential based on configuration.

    Args:
        cfg: Azure configuration object
        use_cache: Whether to use cached credential

    Returns:
        TokenCredential: Configured Azure credential

    Raises:
        ValueError: If required configuration is missing
    """
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
            logger.info("Using service principal authentication")

        elif cfg.auth_mode == "managed_identity":
            credential = ManagedIdentityCredential(client_id=cfg.user_assigned_identity_client_id)
            logger.info("Using managed identity authentication")

        elif cfg.auth_mode == "azure_cli":
            credential = AzureCliCredential()
            logger.info("Using Azure CLI authentication")

        elif cfg.auth_mode == "device_code":
            if not cfg.tenant_id:
                raise ValueError("tenant_id is required for device_code authentication")
            credential = DeviceCodeCredential(
                tenant_id=cfg.tenant_id, client_id=cfg.client_id, authority=authority
            )
            logger.info("Using device code authentication")

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
            logger.info("Using workload identity authentication")

        elif cfg.auth_mode == "environment":
            credential = EnvironmentCredential(authority=authority)
            logger.info("Using environment variable authentication")

        else:
            credentials = []

            try:
                credentials.append(EnvironmentCredential(authority=authority))
            except Exception as exc:
                logger.debug("EnvironmentCredential unavailable: %s", exc)

            try:
                credentials.append(ManagedIdentityCredential())
            except Exception as exc:
                logger.debug("ManagedIdentityCredential unavailable: %s", exc)

            if cfg.enable_cli_fallback:
                try:
                    credentials.append(AzureCliCredential())
                except Exception as exc:
                    logger.debug("AzureCliCredential unavailable: %s", exc)

            try:
                credentials.append(AzureDeveloperCliCredential())
            except Exception as exc:
                logger.debug("AzureDeveloperCliCredential unavailable: %s", exc)

            if credentials:
                credential = ChainedTokenCredential(*credentials)
                logger.info(f"Using chained credential with {len(credentials)} providers")
            else:
                credential = DefaultAzureCredential(authority=authority)
                logger.info("Using default Azure credential")

    except Exception as e:
        logger.error(f"Failed to build credential: {e}")
        credential = DefaultAzureCredential(authority=authority)
        logger.warning("Falling back to DefaultAzureCredential")

    if credential and use_cache:
        _CREDENTIAL_CACHE = credential

    return credential


def arm_scopes() -> Sequence[str]:
    """Get Azure Resource Manager scopes"""
    return [_ARM_SCOPE]


def clear_credential_cache() -> None:
    """Clear the cached credential"""
    global _CREDENTIAL_CACHE
    _CREDENTIAL_CACHE = None
    logger.info("Credential cache cleared")


async def test_credential(credential: TokenCredential | None = None) -> bool:
    """
    Test if the credential can acquire a token.

    Args:
        credential: Credential to test (uses default if None)

    Returns:
        bool: True if credential is valid
    """
    if credential is None:
        credential = build_credential()

    try:
        token = credential.get_token(_ARM_SCOPE)
        return token is not None and token.token is not None
    except Exception as e:
        logger.error(f"Credential test failed: {e}")
        return False
