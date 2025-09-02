from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .providers.base import VectorProvider

tracer = trace.get_tracer(__name__)


class VectorProviderType(str, Enum):
    CHROMA = "chroma"
    PINECONE = "pinecone"
    CUSTOM = "custom"


class VectorRegistry:
    _instance: VectorRegistry | None = None
    _providers: dict[str, VectorProvider] = {}
    _provider_configs: dict[str, dict[str, Any]] = {}
    _default_provider: str | None = None

    def __new__(cls) -> VectorRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True

    async def register_provider(
        self,
        name: str,
        provider: VectorProvider,
        config: dict[str, Any] | None = None,
        set_as_default: bool = False,
    ) -> bool:
        with tracer.start_as_current_span("vector_provider_registration") as span:
            span.set_attributes(
                {
                    "provider.name": name,
                    "provider.type": provider.__class__.__name__,
                    "provider.set_as_default": set_as_default,
                }
            )

            try:
                if not provider._initialized:
                    await provider.initialize()

                self._providers[name] = provider
                self._provider_configs[name] = config or {}

                if set_as_default or self._default_provider is None:
                    self._default_provider = name

                span.set_attributes(
                    {
                        "registration.success": True,
                        "provider.initialized": provider._initialized,
                        "registry.total_providers": len(self._providers),
                        "registry.default_provider": self._default_provider,
                    }
                )
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    def get_provider(self, name: str | None = None) -> VectorProvider | None:
        with tracer.start_as_current_span("vector_provider_retrieval") as span:
            provider_name = name or self._default_provider
            span.set_attributes(
                {
                    "requested_provider": name or "",
                    "resolved_provider": provider_name or "",
                }
            )

            if provider_name and provider_name in self._providers:
                provider = self._providers[provider_name]
                span.set_attributes(
                    {
                        "provider.found": True,
                        "provider.type": provider.__class__.__name__,
                        "provider.initialized": provider._initialized,
                    }
                )
                span.set_status(Status(StatusCode.OK))
                return provider
            else:
                span.set_attribute("provider.found", False)
                span.set_status(Status(StatusCode.ERROR, f"Provider {provider_name} not found"))
                return None

    def list_providers(self) -> dict[str, dict[str, Any]]:
        with tracer.start_as_current_span("vector_provider_listing") as span:
            provider_info = {}

            for name, provider in self._providers.items():
                provider_info[name] = {
                    "name": name,
                    "type": provider.__class__.__name__,
                    "initialized": provider._initialized,
                    "is_default": name == self._default_provider,
                    "config": self._provider_configs.get(name, {}),
                }

            span.set_attributes(
                {
                    "providers.count": len(provider_info),
                    "default_provider": self._default_provider or "",
                }
            )
            span.set_status(Status(StatusCode.OK))

            return provider_info

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        with tracer.start_as_current_span("vector_registry_health_check") as span:
            span.set_attribute("providers.count", len(self._providers))

            health_results = {}
            healthy_count = 0

            for name, provider in self._providers.items():
                try:
                    health_status = await provider.health_check()
                    health_results[name] = health_status

                    if health_status.get("status") == "healthy":
                        healthy_count += 1

                except Exception as e:
                    health_results[name] = {
                        "provider": name,
                        "status": "unhealthy",
                        "error": str(e),
                    }

            span.set_attributes(
                {
                    "health.total_providers": len(self._providers),
                    "health.healthy_providers": healthy_count,
                    "health.overall_healthy": healthy_count == len(self._providers),
                }
            )

            if healthy_count == len(self._providers):
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        f"Only {healthy_count}/{len(self._providers)} providers healthy",
                    )
                )

            return health_results

    def set_default_provider(self, name: str) -> bool:
        with tracer.start_as_current_span("vector_set_default_provider") as span:
            span.set_attributes(
                {"provider.name": name, "current_default": self._default_provider or ""}
            )

            if name in self._providers:
                old_default = self._default_provider
                self._default_provider = name

                span.set_attributes(
                    {"default.changed": True, "default.old": old_default or "", "default.new": name}
                )
                span.set_status(Status(StatusCode.OK))

                return True
            else:
                span.set_attributes({"default.changed": False, "error": "Provider not found"})
                span.set_status(Status(StatusCode.ERROR, f"Provider {name} not found"))

                return False

    async def unregister_provider(self, name: str) -> bool:
        with tracer.start_as_current_span("vector_provider_unregistration") as span:
            span.set_attributes(
                {"provider.name": name, "is_default": name == self._default_provider}
            )

            if name not in self._providers:
                span.set_status(Status(StatusCode.ERROR, f"Provider {name} not found"))
                return False

            try:
                provider = self._providers.pop(name)
                self._provider_configs.pop(name, None)

                if name == self._default_provider:
                    self._default_provider = (
                        list(self._providers.keys())[0] if self._providers else None
                    )

                if hasattr(provider, "shutdown") and callable(provider.shutdown):
                    await provider.shutdown()

                span.set_attributes(
                    {
                        "unregistration.success": True,
                        "new_default": self._default_provider or "",
                        "remaining_providers": len(self._providers),
                    }
                )
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    def get_registry_stats(self) -> dict[str, Any]:
        with tracer.start_as_current_span("vector_registry_stats") as span:
            stats = {
                "total_providers": len(self._providers),
                "default_provider": self._default_provider,
                "provider_types": {
                    provider_name: provider.__class__.__name__
                    for provider_name, provider in self._providers.items()
                },
                "initialized_providers": {
                    provider_name: provider._initialized
                    for provider_name, provider in self._providers.items()
                },
            }

            span.set_attributes(
                {
                    "stats.total_providers": len(self._providers),
                    "stats.default_provider": self._default_provider or "",
                }
            )
            span.set_status(Status(StatusCode.OK))

            return stats

    async def similarity_search(self, embedding: list[float], limit: int = 10) -> list[Any]:
        with tracer.start_as_current_span("registry_similarity_search") as span:
            span.set_attributes(
                {
                    "search.embedding_dim": len(embedding),
                    "search.limit": limit,
                    "registry.provider": self._default_provider or "",
                }
            )

            try:
                provider = self.get_provider()
                if not provider:
                    span.set_status(Status(StatusCode.ERROR, "No provider available"))
                    return []

                if hasattr(provider, "similarity_search"):
                    results = await provider.similarity_search(embedding=embedding, limit=limit)
                    span.set_attribute("search.results_count", len(results))
                    span.set_status(Status(StatusCode.OK))
                    return list(results) if results else []
                else:
                    span.set_status(
                        Status(StatusCode.ERROR, "Provider does not support similarity search")
                    )
                    return []

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return []

    async def cleanup_old_vectors(self, max_age: timedelta) -> int:
        with tracer.start_as_current_span("registry_cleanup_vectors") as span:
            span.set_attribute("cleanup.max_age", str(max_age))

            try:
                provider = self.get_provider()
                if not provider:
                    span.set_status(Status(StatusCode.ERROR, "No provider available"))
                    return 0

                if hasattr(provider, "cleanup_old_vectors"):
                    cleaned_count = await provider.cleanup_old_vectors(max_age=max_age)
                    span.set_attribute("cleanup.cleaned_count", cleaned_count)
                    span.set_status(Status(StatusCode.OK))
                    return int(cleaned_count) if cleaned_count is not None else 0
                else:
                    span.set_status(Status(StatusCode.OK, "Provider does not support cleanup"))
                    return 0

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return 0

    async def shutdown(self) -> None:
        with tracer.start_as_current_span("registry_shutdown") as span:
            try:
                shutdown_results = []
                for name, provider in self._providers.items():
                    if hasattr(provider, "shutdown"):
                        await provider.shutdown()
                        shutdown_results.append(name)

                span.set_attributes(
                    {
                        "shutdown.providers_count": len(shutdown_results),
                        "shutdown.providers": shutdown_results,
                    }
                )
                span.set_status(Status(StatusCode.OK))

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise


async def create_chroma_provider(config: dict[str, Any]) -> VectorProvider:
    from .providers.chroma import ChromaProvider

    provider = ChromaProvider(config)
    await provider.initialize()
    return provider


async def create_pinecone_provider(config: dict[str, Any]) -> VectorProvider:
    from .providers.pinecone import PineconeProvider

    provider = PineconeProvider(config)
    await provider.initialize()
    return provider


_registry = VectorRegistry()


async def register_provider(
    name: str,
    provider: VectorProvider,
    config: dict[str, Any] | None = None,
    set_as_default: bool = False,
) -> bool:
    return await _registry.register_provider(name, provider, config, set_as_default)


def get_provider(name: str | None = None) -> VectorProvider | None:
    return _registry.get_provider(name)


def get_registry() -> VectorRegistry:
    return _registry
