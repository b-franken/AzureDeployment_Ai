from __future__ import annotations

import asyncio
import inspect
import os
import types
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, TypeVar, Union, cast, get_args, get_origin
from weakref import WeakKeyDictionary, WeakValueDictionary

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

T = TypeVar("T")
logger = get_logger(__name__)


class Scope(str, Enum):
    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


class InjectionToken[T]:
    def __init__(self, name: str, type_hint: type[T] | None = None):
        self.name = name
        self.type_hint = type_hint

    def __repr__(self) -> str:
        return f"InjectionToken({self.name})"

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, InjectionToken) and self.name == other.name


@dataclass
class ServiceDescriptor:
    service_type: type[Any] | InjectionToken
    implementation: type[Any] | Callable | Any
    scope: Scope
    factory: Callable | None = None
    dependencies: list[type[Any] | InjectionToken] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_factory(self) -> bool:
        return self.factory is not None

    @property
    def is_instance(self) -> bool:
        return not inspect.isclass(self.implementation) and not callable(self.implementation)


class ServiceProvider(ABC):
    @abstractmethod
    def get(self, service_type: type[T] | InjectionToken[T]) -> T: ...

    @abstractmethod
    def get_all(self, service_type: type[T] | InjectionToken[T]) -> list[T]: ...

    @abstractmethod
    async def aget(self, service_type: type[T] | InjectionToken[T]) -> T: ...


class Container(ServiceProvider):
    def __init__(self) -> None:
        self._services: dict[type | InjectionToken, list[ServiceDescriptor]] = {}
        self._singletons: dict[type | InjectionToken, Any] = {}
        self._scoped_instances: WeakKeyDictionary[Any, dict[type | InjectionToken, Any]] = (
            WeakKeyDictionary()
        )
        self._resolving: set[type | InjectionToken] = set()
        self._parent: Container | None = None
        self._children: WeakValueDictionary[str, Container] = WeakValueDictionary()

    def register(
        self,
        service_type: type[T] | InjectionToken[T],
        implementation: type[T] | Callable[..., T] | T | None = None,
        scope: Scope = Scope.TRANSIENT,
        factory: Callable[..., T] | None = None,
        **metadata: Any,
    ) -> Container:
        if implementation is None and factory is None:
            if isinstance(service_type, type):
                implementation = service_type
            else:
                raise ConfigurationError(
                    "service_type",
                    "Implementation or factory must be provided for tokens",
                )
        dependencies = self._extract_dependencies(implementation or factory)
        descriptor = ServiceDescriptor(
            service_type=service_type,
            implementation=implementation,
            scope=scope,
            factory=factory,
            dependencies=dependencies,
            metadata=metadata,
        )
        if service_type not in self._services:
            self._services[service_type] = []
        self._services[service_type].append(descriptor)
        logger.debug(
            "registered service %s scope=%s has_factory=%s",
            str(service_type),
            scope.value,
            str(factory is not None),
        )
        return self

    def register_singleton(
        self,
        service_type: type[T] | InjectionToken[T],
        implementation: type[T] | Callable[..., T] | T | None = None,
        **metadata: Any,
    ) -> Container:
        return self.register(service_type, implementation, Scope.SINGLETON, **metadata)

    def register_scoped(
        self,
        service_type: type[T] | InjectionToken[T],
        implementation: type[T] | Callable[..., T] | T | None = None,
        **metadata: Any,
    ) -> Container:
        return self.register(service_type, implementation, Scope.SCOPED, **metadata)

    def register_transient(
        self,
        service_type: type[T] | InjectionToken[T],
        implementation: type[T] | Callable[..., T] | T | None = None,
        **metadata: Any,
    ) -> Container:
        return self.register(service_type, implementation, Scope.TRANSIENT, **metadata)

    def _sync_await(self, coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("sync resolution is not allowed inside a running event loop")

    def get(self, service_type: type[T] | InjectionToken[T], scope_context: Any = None) -> T:
        return cast(T, self._sync_await(self.aget(service_type, scope_context)))

    def get_all(
        self, service_type: type[T] | InjectionToken[T], scope_context: Any = None
    ) -> list[T]:
        return cast(list[T], self._sync_await(self.aget_all(service_type, scope_context)))

    async def aget(self, service_type: type[T] | InjectionToken[T], scope_context: Any = None) -> T:
        instances = await self.aget_all(service_type, scope_context)
        if not instances:
            raise ConfigurationError(
                str(service_type),
                f"No service registered for {service_type}",
            )
        return instances[-1]

    async def aget_all(
        self, service_type: type[T] | InjectionToken[T], scope_context: Any = None
    ) -> list[T]:
        if service_type in self._resolving:
            raise ConfigurationError(
                str(service_type),
                f"Circular dependency detected for {service_type}",
            )
        self._resolving.add(service_type)
        try:
            descriptors = self._get_descriptors(service_type)
            instances: list[T] = []
            for descriptor in descriptors:
                instance = await self._resolve_instance(descriptor, scope_context)
                instances.append(cast(T, instance))
            return instances
        finally:
            self._resolving.discard(service_type)

    def _get_descriptors(self, service_type: type | InjectionToken) -> list[ServiceDescriptor]:
        descriptors = self._services.get(service_type, [])
        if not descriptors and self._parent:
            descriptors = self._parent._get_descriptors(service_type)
        return descriptors

    async def _resolve_instance(
        self, descriptor: ServiceDescriptor, scope_context: Any = None
    ) -> Any:
        if descriptor.scope == Scope.SINGLETON:
            if descriptor.service_type in self._singletons:
                return self._singletons[descriptor.service_type]
        elif descriptor.scope == Scope.SCOPED and scope_context is not None:
            if scope_context not in self._scoped_instances:
                self._scoped_instances[scope_context] = {}
            if descriptor.service_type in self._scoped_instances[scope_context]:
                return self._scoped_instances[scope_context][descriptor.service_type]
        instance = await self._create_instance(descriptor, scope_context)
        if descriptor.scope == Scope.SINGLETON:
            self._singletons[descriptor.service_type] = instance
        elif descriptor.scope == Scope.SCOPED and scope_context is not None:
            self._scoped_instances[scope_context][descriptor.service_type] = instance
        return instance

    async def _create_instance(
        self, descriptor: ServiceDescriptor, scope_context: Any = None
    ) -> Any:
        if descriptor.is_instance:
            return descriptor.implementation
        dependencies: dict[str, Any] = {}
        for dep in descriptor.dependencies:
            dep_instance = await self.aget(dep, scope_context)
            target = descriptor.implementation or descriptor.factory
            param_name = self._get_param_name(target, dep)
            dependencies[param_name] = dep_instance
        if descriptor.factory:
            if asyncio.iscoroutinefunction(descriptor.factory):
                return await descriptor.factory(**dependencies)
            return descriptor.factory(**dependencies)
        impl = descriptor.implementation
        if inspect.isclass(impl):
            return impl(**dependencies)
        return impl(**dependencies)

    def _extract_dependencies(self, target: Any) -> list[type | InjectionToken]:
        if target is None or not callable(target):
            return []
        if inspect.isclass(target):
            signature = inspect.signature(target.__init__)
            params = list(signature.parameters.values())[1:]
        else:
            signature = inspect.signature(target)
            params = list(signature.parameters.values())
        deps: list[type | InjectionToken] = []
        for param in params:
            ann = param.annotation
            if ann == inspect.Parameter.empty:
                continue
            origin = get_origin(ann)
            if origin in (Union, types.UnionType):
                args = [a for a in get_args(ann) if a is not types.NoneType]
                if args:
                    deps.append(args[0])
                continue
            deps.append(ann)
        return deps

    def _get_param_name(self, target: Any, dep_type: type | InjectionToken) -> str:
        if not callable(target):
            return "dependency"
        if inspect.isclass(target):
            signature = inspect.signature(target.__init__)
            params = list(signature.parameters.values())[1:]
        else:
            signature = inspect.signature(target)
            params = list(signature.parameters.values())
        for param in params:
            ann = param.annotation
            if ann == dep_type:
                return param.name
            origin = get_origin(ann)
            if origin in (Union, types.UnionType):
                if dep_type in get_args(ann):
                    return param.name
        return "dependency"

    @asynccontextmanager
    async def create_scope(self) -> AsyncIterator[ScopedServiceProvider]:
        scope_context = object()
        try:
            yield ScopedServiceProvider(self, scope_context)
        finally:
            if scope_context in self._scoped_instances:
                del self._scoped_instances[scope_context]

    def create_child_container(self, name: str) -> Container:
        child = Container()
        child._parent = self
        self._children[name] = child
        return child


class ScopedServiceProvider(ServiceProvider):
    def __init__(self, container: Container, scope_context: Any):
        self._container = container
        self._scope_context = scope_context

    def get(self, service_type: type[T] | InjectionToken[T]) -> T:
        return self._container.get(service_type, self._scope_context)

    def get_all(self, service_type: type[T] | InjectionToken[T]) -> list[T]:
        return self._container.get_all(service_type, self._scope_context)

    async def aget(self, service_type: type[T] | InjectionToken[T]) -> T:
        return await self._container.aget(service_type, self._scope_context)


def injectable(
    scope: Scope = Scope.TRANSIENT,
    token: InjectionToken[Any] | None = None,
) -> Callable[[type[T]], type[T]]:
    def decorator(cls: type[T]) -> type[T]:
        c = cast(Any, cls)
        c.__injection_scope__ = scope
        c.__injection_token__ = token
        return cls

    return decorator


def inject(container: Container) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            signature = inspect.signature(func)
            strict = os.getenv("DI_STRICT_MODE", "").lower() in {"1", "true", "yes"}
            for name, param in signature.parameters.items():
                if param.annotation != inspect.Parameter.empty and name not in kwargs:
                    try:
                        dependency = await container.aget(param.annotation)
                        kwargs[name] = dependency
                    except Exception as exc:  # pragma: no cover - defensive
                        message = (
                            f"Failed to resolve dependency '{param.annotation}' for parameter "
                            f"'{name}' in {func.__name__}: {exc}"
                        )
                        if strict:
                            raise ConfigurationError(str(param.annotation), message) from exc
                        logger.warning(message)
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(async_wrapper(*args, **kwargs))
            raise RuntimeError("sync injection wrapper cannot run inside an active event loop")

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


_global_container = Container()


def get_container() -> Container:
    return _global_container
