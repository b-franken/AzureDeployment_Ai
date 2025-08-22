from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from cryptography.fernet import Fernet
from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    Field,
    RedisDsn,
    SecretStr,
    UrlConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

PostgresUrl = Annotated[
    AnyUrl,
    UrlConstraints(
        allowed_schemes=[
            "postgres",
            "postgresql",
            "postgresql+asyncpg",
            "postgresql+psycopg",
        ]
    ),
]


class SecurityConfig(BaseModel):
    jwt_secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(Fernet.generate_key().decode())
    )
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168)
    encryption_key: SecretStr = Field(
        default_factory=lambda: SecretStr(Fernet.generate_key().decode())
    )
    allowed_cors_origins: list[AnyHttpUrl] = Field(default_factory=list)
    enable_audit_logging: bool = True
    api_rate_limit_per_minute: int = Field(default=60, ge=1)
    api_rate_limit_per_hour: int = Field(default=1000, ge=1)
    api_rate_limit_tracker_max_age_seconds: int = Field(default=7200, ge=1)
    api_rate_limit_cleanup_interval_seconds: int = Field(default=60, ge=1)

    @field_validator("encryption_key", mode="before")
    @classmethod
    def validate_encryption_key(cls, v: Any) -> str:
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        if not raw:
            return Fernet.generate_key().decode()
        try:
            Fernet(
                raw
                if isinstance(raw, bytes)
                else raw.encode()
                if isinstance(raw, str)
                else str(raw).encode()
            )
        except Exception as err:
            raise ValueError("Invalid encryption key") from err
        return raw if isinstance(raw, str) else raw.decode()


class DatabaseConfig(BaseModel):
    postgres_dsn: PostgresUrl | None = None
    redis_dsn: RedisDsn | None = None
    db_pool_size: int = Field(default=20, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_pool_recycle: int = Field(default=3600, ge=60)
    redis_max_connections: int = Field(default=50, ge=1)
    redis_socket_timeout: int = Field(default=5, ge=1)
    enable_query_logging: bool = False
    slow_query_threshold_ms: int = Field(default=100, ge=1)

    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def _normalize_pg(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class AzureConfig(BaseModel):
    subscription_id: str | None = Field(
        default=None, pattern="^[a-f0-9-]{36}$")
    tenant_id: str | None = Field(default=None, pattern="^[a-f0-9-]{36}$")
    client_id: str | None = None
    client_secret: SecretStr | None = None
    auth_mode: Literal[
        "managed_identity",
        "service_principal",
        "azure_cli",
        "workload_identity",
        "environment",
        "device_code",
    ] = "managed_identity"
    user_assigned_identity_client_id: str | None = None
    workload_identity_token_file: str | None = None
    cloud: Literal["public", "usgov", "china", "germany"] = "public"
    authority_host: str | None = None
    resource_manager_endpoint: str | None = None
    default_location: str = "westeurope"
    allowed_locations: list[str] = Field(
        default_factory=lambda: [
            "westeurope",
            "northeurope",
            "uksouth",
            "eastus",
            "westus",
        ]
    )
    default_resource_group: str | None = None
    environment: Literal["dev", "test", "acc", "prod"] = "dev"
    name_prefix: str = "ff"
    enable_cli_fallback: bool = True
    tags: dict[str, str] = Field(default_factory=lambda: {
                                 "managed_by": "devops-ai"})

    @field_validator("allowed_locations", mode="before")
    @classmethod
    def _normalize_locations(cls, v: Any) -> list[str]:
        if not v:
            return ["westeurope", "northeurope", "uksouth", "eastus", "westus"]
        return [str(x).lower().strip() for x in v]

    @field_validator("default_location", mode="before")
    @classmethod
    def _normalize_default_location(cls, v: Any) -> str:
        return str(v).lower().strip() if v else "westeurope"

    @model_validator(mode="after")
    def _validate_cloud_and_location(self) -> AzureConfig:
        if self.default_location not in set(self.allowed_locations):
            raise ValueError(
                "default_location must be one of allowed_locations")
        if self.cloud == "public" and not self.authority_host:
            self.authority_host = "https://login.microsoftonline.com"
        if self.cloud == "public" and not self.resource_manager_endpoint:
            self.resource_manager_endpoint = "https://management.azure.com/"
        return self


class LLMConfig(BaseModel):
    default_provider: Literal["openai", "gemini", "ollama", "azure"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5"
    openai_max_tokens: int = Field(default=4096, ge=1, le=128000)
    openai_temperature: float = Field(default=0.7, ge=0, le=2)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-1.5-pro"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    requests_per_minute: int = Field(default=60, ge=1)
    tokens_per_minute: int = Field(default=90000, ge=1)
    enable_response_caching: bool = True
    cache_ttl_seconds: int = Field(default=3600, ge=0)
    max_context_length: int = Field(default=16000, ge=100)


class ObservabilityConfig(BaseModel):
    enable_metrics: bool = True
    metrics_port: int = Field(default=9090, ge=1024, le=65535)
    enable_tracing: bool = True
    trace_sample_rate: float = Field(default=0.1, ge=0, le=1)
    log_level: Literal["DEBUG", "INFO",
                       "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_file: Path | None = None
    log_rotation_size_mb: int = Field(default=100, ge=1)
    log_retention_days: int = Field(default=30, ge=1)
    enable_health_checks: bool = True
    health_check_interval_seconds: int = Field(default=30, ge=1)
    applicationinsights_connection_string: str | None = None
    otel_service_name: str = "devops-ai-api"


class CacheConfig(BaseModel):
    enable_caching: bool = True
    cache_backend: Literal["memory", "redis", "memcached"] = "redis"
    memory_cache_max_size: int = Field(default=1000, ge=1)
    memory_cache_ttl_seconds: int = Field(default=300, ge=1)
    default_ttl_seconds: int = Field(default=3600, ge=1)
    max_ttl_seconds: int = Field(default=86400, ge=1)
    auto_invalidate_on_update: bool = True


class MemoryConfig(BaseModel):
    max_memory: int = Field(default=25, ge=1)
    max_total_memory: int = Field(default=100, ge=1)


class RetryConfig(BaseModel):
    request_timeout_seconds: float = Field(default=60.0, ge=1)
    retry_max_attempts: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=0.8, ge=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "DevOps AI Platform"
    app_version: str = "2.0.0"
    environment: Literal["development",
                         "staging", "production"] = "development"
    debug: bool = False

    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1024, le=65535)
    api_prefix: str = "/api"
    api_docs_enabled: bool = True

    security: SecurityConfig = Field(default_factory=SecurityConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    azure: AzureConfig = Field(default_factory=AzureConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    observability: ObservabilityConfig = Field(
        default_factory=ObservabilityConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)

    api_jwt_secret: SecretStr | None = None
    api_jwt_hours: int | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    llm_provider: str | None = None
    applicationinsights_connection_string: str | None = None
    otel_service_name: str | None = None

    @model_validator(mode="after")
    def apply_legacy_env(self) -> Settings:
        if self.api_jwt_secret:
            self.security.jwt_secret_key = self.api_jwt_secret
        if self.api_jwt_hours is not None:
            self.security.jwt_expiration_hours = self.api_jwt_hours
        if self.openai_api_key:
            self.llm.openai_api_key = self.openai_api_key
        if self.openai_model:
            self.llm.openai_model = self.openai_model
        if self.llm_provider:
            # type: ignore[assignment]
            self.llm.default_provider = self.llm_provider
        if self.applicationinsights_connection_string:
            self.observability.applicationinsights_connection_string = (
                self.applicationinsights_connection_string
            )
        if self.otel_service_name:
            self.observability.otel_service_name = self.otel_service_name
        base_url = os.getenv("OPENAI_BASE_URL")
        if base_url:
            self.llm.openai_api_base = base_url
        return self

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
        if self.environment == "production":
            if self.debug:
                raise ValueError("Debug must be disabled in production")
            if not self.security.enable_audit_logging:
                raise ValueError("Audit logging must be enabled in production")
            jwt_env_present = any(
                os.getenv(k) for k in ["API_JWT_SECRET", "SECURITY__JWT_SECRET_KEY"]
            )
            if not jwt_env_present:
                raise ValueError(
                    "JWT secret must be set via environment in production")
        return self


class Config:
    def __init__(self) -> None:
        self._settings = Settings()
        key = self._settings.security.encryption_key.get_secret_value()
        key_bytes = key if isinstance(key, bytes) else key.encode()
        self._cipher = Fernet(key_bytes)

    @property
    def settings(self) -> Settings:
        return self._settings

    def encrypt_value(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt_value(self, encrypted: str) -> str:
        return self._cipher.decrypt(encrypted.encode()).decode()

    def reload(self) -> None:
        self.__init__()

    def export_safe_config(self) -> dict[str, Any]:
        cfg = self._settings.model_dump()
        redactions = [
            ["security", "jwt_secret_key"],
            ["security", "encryption_key"],
            ["azure", "client_secret"],
            ["llm", "openai_api_key"],
            ["llm", "gemini_api_key"],
        ]
        for path in redactions:
            current = cfg
            for key in path[:-1]:
                current = current.get(key, {})
            if path[-1] in current:
                current[path[-1]] = "***REDACTED***"
        return cfg


@lru_cache
def get_config() -> Config:
    return Config()


@lru_cache
def get_settings() -> Settings:
    return get_config().settings


def get_env_var(key: str, default: str = "") -> str:
    return os.getenv(key, default)


settings = get_settings()

API_HOST = settings.api_host
API_PORT = settings.api_port
API_PREFIX = settings.api_prefix

JWT_SECRET = settings.security.jwt_secret_key.get_secret_value()
JWT_ALGORITHM = settings.security.jwt_algorithm
JWT_EXPIRATION_HOURS = settings.security.jwt_expiration_hours

POSTGRES_DSN = str(
    settings.database.postgres_dsn) if settings.database.postgres_dsn else None
REDIS_DSN = str(
    settings.database.redis_dsn) if settings.database.redis_dsn else None

AZURE_SUBSCRIPTION_ID = settings.azure.subscription_id
AZURE_TENANT_ID = settings.azure.tenant_id
AZURE_CLIENT_ID = settings.azure.client_id
AZURE_CLIENT_SECRET = (
    settings.azure.client_secret.get_secret_value(
    ) if settings.azure.client_secret else None
)

LLM_PROVIDER = settings.llm.default_provider
OPENAI_API_KEY = (
    settings.llm.openai_api_key.get_secret_value(
    ) if settings.llm.openai_api_key else None
)
GEMINI_API_KEY = (
    settings.llm.gemini_api_key.get_secret_value(
    ) if settings.llm.gemini_api_key else None
)
OLLAMA_BASE_URL = settings.llm.ollama_base_url

OPENAI_MODEL = settings.llm.openai_model
GEMINI_MODEL = settings.llm.gemini_model
OLLAMA_MODEL = settings.llm.ollama_model

MAX_MEMORY = settings.memory.max_memory
MAX_TOTAL_MEMORY = settings.memory.max_total_memory
REQUEST_TIMEOUT_SECONDS = settings.retry.request_timeout_seconds
RETRY_MAX_ATTEMPTS = settings.retry.retry_max_attempts
RETRY_BACKOFF_SECONDS = settings.retry.retry_backoff_seconds
