"""
Enhanced configuration management with validation, encryption, and environment-specific settings.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar, cast

from cryptography.fernet import Fernet
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

T = TypeVar("T", bound=BaseModel)


class SecurityConfig(BaseModel):
    jwt_secret_key: SecretStr = Field(default=..., min_length=32)
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168)

    encryption_key: SecretStr = Field(default=..., min_length=32)
    api_rate_limit_per_minute: int = Field(default=60, ge=1)
    api_rate_limit_per_hour: int = Field(default=1000, ge=1)

    allowed_cors_origins: list[AnyHttpUrl] = Field(default_factory=list)
    allowed_ip_ranges: list[str] = Field(default_factory=list)

    enable_audit_logging: bool = Field(default=True)
    enable_security_headers: bool = Field(default=True)

    min_password_length: int = Field(default=12, ge=8)
    require_uppercase: bool = Field(default=True)
    require_lowercase: bool = Field(default=True)
    require_numbers: bool = Field(default=True)
    require_special_chars: bool = Field(default=True)
    password_history_count: int = Field(default=5, ge=0)

    @field_validator("encryption_key", mode="before")
    def validate_encryption_key(cls, v: Any) -> str:
        if v is None or v == "":
            return Fernet.generate_key().decode()
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        try:
            Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception as err:
            raise ValueError("Invalid encryption key format") from err
        return raw if isinstance(raw, str) else raw.decode()


class DatabaseConfig(BaseModel):
    postgres_dsn: PostgresDsn | None = None
    redis_dsn: RedisDsn | None = None

    db_pool_size: int = Field(default=20, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_pool_recycle: int = Field(default=3600, ge=60)

    redis_max_connections: int = Field(default=50, ge=1)
    redis_socket_timeout: int = Field(default=5, ge=1)
    redis_socket_connect_timeout: int = Field(default=5, ge=1)
    redis_decode_responses: bool = Field(default=True)

    enable_query_logging: bool = Field(default=False)
    slow_query_threshold_ms: int = Field(default=100, ge=1)


class AzureConfig(BaseModel):
    subscription_id: str | None = Field(
        default=None,
        pattern="^[a-f0-9-]{36}$",
    )
    tenant_id: str | None = Field(
        default=None,
        pattern="^[a-f0-9-]{36}$",
    )
    client_id: str | None = Field(default=None)
    client_secret: SecretStr | None = Field(default=None)

    default_location: str = Field(default="westeurope")
    allowed_locations: list[str] = Field(
        default_factory=lambda: ["westeurope", "northeurope", "eastus", "westus"]
    )

    resource_naming_prefix: str = Field(
        default="devops",
        pattern="^[a-z][a-z0-9-]{1,20}$",
    )
    default_tags: dict[str, str] = Field(default_factory=dict)

    max_vms_per_deployment: int = Field(default=10, ge=1, le=100)
    max_storage_accounts: int = Field(default=20, ge=1, le=100)
    max_cost_per_month: float = Field(default=10000.0, ge=0)

    deployment_timeout_seconds: int = Field(default=3600, ge=60)
    operation_timeout_seconds: int = Field(default=300, ge=30)

    max_retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.1, le=60)


class LLMConfig(BaseModel):
    default_provider: str = Field(
        default="openai",
        pattern="^(openai|gemini|ollama|azure)$",
    )
    default_model: str | None = None

    openai_api_key: SecretStr | None = None
    openai_api_base: AnyHttpUrl = Field(default=cast(AnyHttpUrl, "https://api.openai.com/v1"))
    openai_model: str = Field(default="gpt-4o-mini")
    openai_max_tokens: int = Field(default=4096, ge=1, le=128000)
    openai_temperature: float = Field(default=0.7, ge=0, le=2)

    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-1.5-pro")

    ollama_base_url: AnyHttpUrl = Field(default=cast(AnyHttpUrl, "http://localhost:11434"))
    ollama_model: str = Field(default="llama3.1")

    azure_openai_api_key: SecretStr | None = None
    azure_openai_endpoint: AnyHttpUrl | None = None
    azure_openai_deployment: str | None = None

    requests_per_minute: int = Field(default=60, ge=1)
    tokens_per_minute: int = Field(default=90000, ge=1)

    enable_response_caching: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600, ge=0)

    enable_content_filtering: bool = Field(default=True)
    max_context_length: int = Field(default=16000, ge=100)


class ObservabilityConfig(BaseModel):
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9090, ge=1024, le=65535)
    metrics_path: str = Field(default="/metrics")

    enable_tracing: bool = Field(default=True)
    jaeger_agent_host: str = Field(default="localhost")
    jaeger_agent_port: int = Field(default=6831, ge=1024, le=65535)
    trace_sample_rate: float = Field(default=0.1, ge=0, le=1)

    log_level: str = Field(
        default="INFO",
        pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
    )
    log_format: str = Field(default="json", pattern="^(json|text)$")
    log_file: Path | None = None
    log_rotation_size_mb: int = Field(default=100, ge=1)
    log_retention_days: int = Field(default=30, ge=1)

    enable_health_checks: bool = Field(default=True)
    health_check_interval_seconds: int = Field(default=30, ge=1)

    enable_alerting: bool = Field(default=True)
    alert_webhook_url: AnyHttpUrl | None = None
    alert_email_addresses: list[str] = Field(default_factory=list)

    app_insights_connection_string: str | None = None
    app_insights_sampling_percentage: float = Field(default=100.0, ge=0, le=100)


class CacheConfig(BaseModel):
    enable_caching: bool = Field(default=True)
    cache_backend: str = Field(
        default="redis",
        pattern="^(memory|redis|memcached)$",
    )

    memory_cache_max_size: int = Field(default=1000, ge=1)
    memory_cache_ttl_seconds: int = Field(default=300, ge=1)

    default_ttl_seconds: int = Field(default=3600, ge=1)
    max_ttl_seconds: int = Field(default=86400, ge=1)

    llm_cache_prefix: str = Field(default="llm:")
    azure_cache_prefix: str = Field(default="azure:")
    cost_cache_prefix: str = Field(default="cost:")

    auto_invalidate_on_update: bool = Field(default=True)
    invalidation_batch_size: int = Field(default=100, ge=1)


class FeatureFlags(BaseModel):
    enable_mcp_integration: bool = Field(default=True)
    enable_advanced_nlu: bool = Field(default=True)
    enable_cost_optimization: bool = Field(default=True)
    enable_auto_remediation: bool = Field(default=False)
    enable_predictive_scaling: bool = Field(default=False)
    enable_multi_cloud: bool = Field(default=False)
    enable_chaos_engineering: bool = Field(default=False)
    enable_ai_ops: bool = Field(default=True)

    enable_experimental_backends: bool = Field(default=False)
    enable_beta_models: bool = Field(default=False)

    new_ui_rollout_percentage: int = Field(default=0, ge=0, le=100)
    advanced_analytics_rollout_percentage: int = Field(default=50, ge=0, le=100)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = Field(default="DevOps AI Platform")
    app_version: str = Field(default="2.0.0")
    environment: str = Field(
        default="development",
        pattern="^(development|staging|production)$",
    )
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
    features: FeatureFlags = Field(default_factory=lambda: FeatureFlags())


class ConfigManager:
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
        self._settings = Settings()

        key_src = self._settings.security.encryption_key
        if key_src:
            key = key_src.get_secret_value()
            self._cipher = Fernet(key.encode() if isinstance(key, str) else key)

        self._validate_environment_settings()

    def _validate_environment_settings(self) -> None:
        s = self._settings
        assert s is not None
        if s.environment == "production":
            assert s.security.jwt_secret_key, "JWT secret required in production"
            assert not s.debug, "Debug must be disabled in production"
            assert s.security.enable_audit_logging, "Audit logging required in production"
            assert not s.api_docs_enabled, "API docs should be disabled in production"

            if s.database.enable_query_logging:
                import warnings

                warnings.warn(
                    "Query logging is enabled in production",
                    UserWarning,
                    stacklevel=2,
                )

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._load_settings()
        assert self._settings is not None
        return self._settings

    def encrypt_value(self, value: str) -> str:
        if not self._cipher:
            raise RuntimeError("Encryption not configured")
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt_value(self, encrypted: str) -> str:
        if not self._cipher:
            raise RuntimeError("Encryption not configured")
        return self._cipher.decrypt(encrypted.encode()).decode()

    def get_secret(self, key: str) -> str | None:
        value = os.getenv(key)
        if value:
            return value

        if self.settings.azure.client_id:
            pass

        return None

    def reload(self) -> None:
        self._settings = None
        self._cipher = None
        self._load_settings()

    def export_safe_config(self) -> dict:
        config_dict: dict[str, Any] = self.settings.model_dump()

        sensitive_paths = [
            ["security", "jwt_secret_key"],
            ["security", "encryption_key"],
            ["azure", "client_secret"],
            ["llm", "openai_api_key"],
            ["llm", "gemini_api_key"],
            ["llm", "azure_openai_api_key"],
        ]

        for path in sensitive_paths:
            current: dict[str, Any] = config_dict
            for key in path[:-1]:
                if key in current and isinstance(current[key], dict):
                    current = current[key]
            last = path[-1]
            if last in current:
                current[last] = "***REDACTED***"

        return config_dict


@lru_cache
def get_config() -> ConfigManager:
    return ConfigManager()


@lru_cache
def get_settings() -> Settings:
    return get_config().settings


def validate_config_schema(config_class: type[T], data: dict) -> T:
    try:
        return config_class(**data)
    except Exception as e:
        raise ValueError(f"Invalid configuration: {e}") from e


def load_development_config() -> Settings:
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("API_DOCS_ENABLED", "true")
    return get_settings()


def load_production_config() -> Settings:
    os.environ["ENVIRONMENT"] = "production"
    os.environ["DEBUG"] = "false"
    os.environ["API_DOCS_ENABLED"] = "false"
    return get_settings()
