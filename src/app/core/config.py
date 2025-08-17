from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from cryptography.fernet import Fernet
from pydantic import (
    AliasChoices,
    AnyHttpUrl,
    BaseModel,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecurityConfig(BaseModel):
    """Security configuration with encryption and JWT settings."""

    jwt_secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(Fernet.generate_key().decode()),
        min_length=32,
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168)

    encryption_key: SecretStr = Field(
        default_factory=lambda: SecretStr(Fernet.generate_key().decode()),
        min_length=32,
    )
    api_rate_limit_per_minute: int = Field(default=60, ge=1)
    api_rate_limit_per_hour: int = Field(default=1000, ge=1)

    allowed_cors_origins: list[AnyHttpUrl] = Field(default_factory=list)
    enable_audit_logging: bool = Field(default=True)

    min_password_length: int = Field(default=12, ge=8)
    password_history_count: int = Field(default=5, ge=0)

    @field_validator("encryption_key", mode="before")
    @classmethod
    def validate_encryption_key(cls, v: Any) -> str:
        if not v:
            return Fernet.generate_key().decode()
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        try:
            Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception as err:
            raise ValueError("Invalid encryption key format") from err
        return raw if isinstance(raw, str) else raw.decode()


class DatabaseConfig(BaseModel):
    """Database configuration for PostgreSQL and Redis."""

    postgres_dsn: PostgresDsn | None = None
    redis_dsn: RedisDsn | None = None

    db_pool_size: int = Field(default=20, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_pool_recycle: int = Field(default=3600, ge=60)

    redis_max_connections: int = Field(default=50, ge=1)
    redis_socket_timeout: int = Field(default=5, ge=1)

    enable_query_logging: bool = Field(default=False)
    slow_query_threshold_ms: int = Field(default=100, ge=1)


class AzureConfig(BaseModel):
    """Azure-specific configuration."""

    subscription_id: str | None = Field(
        default=None,
        pattern="^[a-f0-9-]{36}$",
        validation_alias=AliasChoices("AZURE_SUBSCRIPTION_ID", "AZURE__SUBSCRIPTION_ID"),
    )
    tenant_id: str | None = Field(
        default=None,
        pattern="^[a-f0-9-]{36}$",
        validation_alias=AliasChoices("AZURE_TENANT_ID", "AZURE__TENANT_ID"),
    )
    client_id: str | None = Field(
        default=None, validation_alias=AliasChoices("AZURE_CLIENT_ID", "AZURE__CLIENT_ID")
    )
    client_secret: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("AZURE_CLIENT_SECRET", "AZURE__CLIENT_SECRET")
    )

    default_location: str = Field(default="westeurope")
    allowed_locations: list[str] = Field(
        default_factory=lambda: ["westeurope", "northeurope", "eastus", "westus"]
    )

    resource_naming_prefix: str = Field(
        default="devops",
        pattern="^[a-z][a-z0-9-]{1,20}$",
    )

    max_vms_per_deployment: int = Field(default=10, ge=1, le=100)
    max_cost_per_month: float = Field(default=10000.0, ge=0)

    deployment_timeout_seconds: int = Field(default=3600, ge=60)
    max_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices("RETRY_MAX_ATTEMPTS", "AZURE__MAX_RETRY_ATTEMPTS"),
    )
    retry_backoff_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60,
        validation_alias=AliasChoices("RETRY_BACKOFF_SECONDS", "AZURE__RETRY_BACKOFF_SECONDS"),
    )


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    default_provider: Literal["openai", "gemini", "ollama", "azure"] = Field(
        default="openai",
        validation_alias=AliasChoices("LLM_PROVIDER", "LLM__DEFAULT_PROVIDER"),
    )

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPENAI_KEY", "LLM__OPENAI_API_KEY"),
    )
    openai_api_base: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "LLM__OPENAI_API_BASE"),
    )

    openai_model: str = Field(
        default="gpt-5", validation_alias=AliasChoices("OPENAI_MODEL", "LLM__OPENAI_MODEL")
    )
    openai_max_tokens: int = Field(default=4096, ge=1, le=128000)
    openai_temperature: float = Field(default=0.7, ge=0, le=2)

    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "LLM__GEMINI_API_KEY")
    )
    gemini_model: str = Field(
        default="gemini-1.5-pro", validation_alias=AliasChoices("GEMINI_MODEL", "LLM__GEMINI_MODEL")
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "LLM__OLLAMA_BASE_URL"),
    )
    ollama_model: str = Field(
        default="llama3.1", validation_alias=AliasChoices("OLLAMA_MODEL", "LLM__OLLAMA_MODEL")
    )

    requests_per_minute: int = Field(default=60, ge=1)
    tokens_per_minute: int = Field(default=90000, ge=1)

    enable_response_caching: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600, ge=0)

    max_context_length: int = Field(default=16000, ge=100)


class ObservabilityConfig(BaseModel):
    """Observability configuration for monitoring and logging."""

    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9090, ge=1024, le=65535)

    enable_tracing: bool = Field(default=True)
    trace_sample_rate: float = Field(default=0.1, ge=0, le=1)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_file: Path | None = None
    log_rotation_size_mb: int = Field(default=100, ge=1)
    log_retention_days: int = Field(default=30, ge=1)

    enable_health_checks: bool = Field(default=True)
    health_check_interval_seconds: int = Field(default=30, ge=1)


class CacheConfig(BaseModel):
    """Cache configuration."""

    enable_caching: bool = Field(default=True)
    cache_backend: Literal["memory", "redis", "memcached"] = "redis"

    memory_cache_max_size: int = Field(default=1000, ge=1)
    memory_cache_ttl_seconds: int = Field(default=300, ge=1)

    default_ttl_seconds: int = Field(default=3600, ge=1)
    max_ttl_seconds: int = Field(default=86400, ge=1)

    auto_invalidate_on_update: bool = Field(default=True)


class MemoryConfig(BaseModel):
    """In-app memory caps. Legacy envs supported."""

    max_memory: int = Field(
        default=25, ge=1, validation_alias=AliasChoices("MAX_MEMORY", "MEMORY__MAX_MEMORY")
    )
    max_total_memory: int = Field(
        default=100,
        ge=1,
        validation_alias=AliasChoices("MAX_TOTAL_MEMORY", "MEMORY__MAX_TOTAL_MEMORY"),
    )


class RetryConfig(BaseModel):
    """HTTP timeouts and retry strategy. Legacy envs supported."""

    request_timeout_seconds: float = Field(
        default=60.0,
        ge=1,
        validation_alias=AliasChoices("REQUEST_TIMEOUT_SECONDS", "HTTP__REQUEST_TIMEOUT_SECONDS"),
    )
    retry_max_attempts: int = Field(
        default=3,
        ge=0,
        validation_alias=AliasChoices("RETRY_MAX_ATTEMPTS", "HTTP__RETRY_MAX_ATTEMPTS"),
    )
    retry_backoff_seconds: float = Field(
        default=0.8,
        ge=0,
        validation_alias=AliasChoices("RETRY_BACKOFF_SECONDS", "HTTP__RETRY_BACKOFF_SECONDS"),
    )


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    app_name: str = Field(default="DevOps AI Platform")
    app_version: str = Field(default="2.0.0")
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = Field(default=False)

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1024, le=65535)
    api_prefix: str = Field(default="/api")
    api_docs_enabled: bool = Field(default=True)

    security: SecurityConfig = Field(default_factory=lambda: SecurityConfig())
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig())
    azure: AzureConfig = Field(default_factory=lambda: AzureConfig())
    llm: LLMConfig = Field(default_factory=lambda: LLMConfig())
    observability: ObservabilityConfig = Field(default_factory=lambda: ObservabilityConfig())
    cache: CacheConfig = Field(default_factory=lambda: CacheConfig())
    memory: MemoryConfig = Field(default_factory=lambda: MemoryConfig())
    retry: RetryConfig = Field(default_factory=lambda: RetryConfig())

    def validate_environment_settings(self) -> None:
        """Validate settings based on environment."""
        if self.environment == "production":
            assert self.security.jwt_secret_key, "JWT secret required in production"
            assert not self.debug, "Debug must be disabled in production"
            assert self.security.enable_audit_logging, "Audit logging required in production"
            assert not self.api_docs_enabled, "API docs should be disabled in production"


class ConfigManager:
    """Singleton configuration manager."""

    _instance: ConfigManager | None = None
    _settings: Settings | None = None
    _cipher: Fernet | None = None

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._settings is None:
            self._load_settings()

    def _load_settings(self) -> None:
        """Load and validate settings."""
        self._settings = Settings()

        key = self._settings.security.encryption_key.get_secret_value()
        self._cipher = Fernet(key.encode() if isinstance(key, str) else key)

        self._settings.validate_environment_settings()

    @property
    def settings(self) -> Settings:
        """Get current settings."""
        if self._settings is None:
            self._load_settings()
        return self._settings  # type: ignore

    def encrypt_value(self, value: str) -> str:
        """Encrypt a string value."""
        if not self._cipher:
            raise RuntimeError("Encryption not configured")
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt_value(self, encrypted: str) -> str:
        """Decrypt an encrypted string."""
        if not self._cipher:
            raise RuntimeError("Encryption not configured")
        return self._cipher.decrypt(encrypted.encode()).decode()

    def reload(self) -> None:
        """Reload configuration from environment."""
        self._settings = None
        self._cipher = None
        self._load_settings()

    def export_safe_config(self) -> dict[str, Any]:
        """Export configuration with sensitive values redacted."""
        config_dict = self.settings.model_dump()

        sensitive_paths = [
            ["security", "jwt_secret_key"],
            ["security", "encryption_key"],
            ["azure", "client_secret"],
            ["llm", "openai_api_key"],
            ["llm", "gemini_api_key"],
        ]

        for path in sensitive_paths:
            current = config_dict
            for key in path[:-1]:
                if key in current and isinstance(current[key], dict):
                    current = current[key]
            if path[-1] in current:
                current[path[-1]] = "***REDACTED***"

        return config_dict


@lru_cache
def get_config() -> ConfigManager:
    return ConfigManager()


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

POSTGRES_DSN = str(settings.database.postgres_dsn) if settings.database.postgres_dsn else None
REDIS_DSN = str(settings.database.redis_dsn) if settings.database.redis_dsn else None

AZURE_SUBSCRIPTION_ID = settings.azure.subscription_id
AZURE_TENANT_ID = settings.azure.tenant_id
AZURE_CLIENT_ID = settings.azure.client_id
AZURE_CLIENT_SECRET = (
    settings.azure.client_secret.get_secret_value() if settings.azure.client_secret else None
)

LLM_PROVIDER = settings.llm.default_provider
OPENAI_API_KEY = (
    settings.llm.openai_api_key.get_secret_value() if settings.llm.openai_api_key else None
)
GEMINI_API_KEY = (
    settings.llm.gemini_api_key.get_secret_value() if settings.llm.gemini_api_key else None
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
