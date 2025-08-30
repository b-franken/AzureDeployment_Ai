from __future__ import annotations

from typing import Any, Dict, List, Type, Optional, Callable
from collections import defaultdict

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .base import Plugin, PluginMetadata, PluginConfig, PluginType, PluginStatus

tracer = trace.get_tracer(__name__)


class PluginRegistry:
    _instance: "PluginRegistry | None" = None
    _plugins: Dict[str, Plugin] = {}
    _plugin_types: Dict[PluginType, List[str]] = defaultdict(list)
    _plugin_dependencies: Dict[str, List[str]] = {}
    _load_order: List[str] = []
    
    def __new__(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True
    
    def register_plugin(self, plugin: Plugin) -> bool:
        with tracer.start_as_current_span("plugin_registration") as span:
            plugin_name = plugin.metadata.name
            
            span.set_attributes({
                "plugin.name": plugin_name,
                "plugin.version": plugin.metadata.version,
                "plugin.type": plugin.metadata.plugin_type.value,
                "plugin.author": plugin.metadata.author,
                "plugin.dependencies": plugin.metadata.dependencies
            })
            
            if plugin_name in self._plugins:
                existing_version = self._plugins[plugin_name].metadata.version
                span.add_event("plugin_already_registered", {
                    "existing_version": existing_version,
                    "new_version": plugin.metadata.version
                })
            
            try:
                dependency_errors = self._validate_dependencies(plugin.metadata.dependencies)
                if dependency_errors:
                    error_msg = f"Dependency validation failed: {', '.join(dependency_errors)}"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return False
                
                self._plugins[plugin_name] = plugin
                self._plugin_types[plugin.metadata.plugin_type].append(plugin_name)
                self._plugin_dependencies[plugin_name] = plugin.metadata.dependencies
                
                self._update_load_order()
                
                span.set_attributes({
                    "registration.success": True,
                    "registry.total_plugins": len(self._plugins),
                    "registry.plugins_of_type": len(self._plugin_types[plugin.metadata.plugin_type])
                })
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False
    
    def get_plugin(self, name: str) -> Plugin | None:
        with tracer.start_as_current_span("plugin_retrieval") as span:
            span.set_attributes({
                "plugin.name": name,
                "available_plugins": list(self._plugins.keys())
            })
            
            plugin = self._plugins.get(name)
            
            span.set_attributes({
                "plugin.found": plugin is not None,
                "plugin.status": plugin.status.value if plugin else "not_found",
                "plugin.type": plugin.metadata.plugin_type.value if plugin else "unknown"
            })
            
            if plugin is None:
                span.set_status(Status(StatusCode.ERROR, f"Plugin {name} not found"))
            else:
                span.set_status(Status(StatusCode.OK))
            
            return plugin
    
    def list_plugins(self, plugin_type: PluginType | None = None, status: PluginStatus | None = None) -> Dict[str, Plugin]:
        with tracer.start_as_current_span("plugin_listing") as span:
            span.set_attributes({
                "filter.type": plugin_type.value if plugin_type else "all",
                "filter.status": status.value if status else "all",
                "total_plugins": len(self._plugins)
            })
            
            filtered_plugins = {}
            
            for name, plugin in self._plugins.items():
                type_match = plugin_type is None or plugin.metadata.plugin_type == plugin_type
                status_match = status is None or plugin.status == status
                
                if type_match and status_match:
                    filtered_plugins[name] = plugin
            
            span.set_attributes({
                "filtered_plugins": len(filtered_plugins),
                "available_types": [pt.value for pt in set(p.metadata.plugin_type for p in self._plugins.values())],
                "available_statuses": [ps.value for ps in set(p.status for p in self._plugins.values())]
            })
            span.set_status(Status(StatusCode.OK))
            
            return filtered_plugins
    
    def get_plugins_by_type(self, plugin_type: PluginType) -> List[Plugin]:
        with tracer.start_as_current_span("plugins_by_type") as span:
            span.set_attributes({
                "plugin.type": plugin_type.value,
                "type.plugin_count": len(self._plugin_types[plugin_type])
            })
            
            plugin_names = self._plugin_types[plugin_type]
            plugins = [self._plugins[name] for name in plugin_names if name in self._plugins]
            
            span.set_attributes({
                "result.count": len(plugins),
                "result.active_count": len([p for p in plugins if p.status == PluginStatus.ACTIVE])
            })
            span.set_status(Status(StatusCode.OK))
            
            return plugins
    
    def get_load_order(self) -> List[str]:
        with tracer.start_as_current_span("plugin_load_order") as span:
            span.set_attributes({
                "load_order.count": len(self._load_order),
                "load_order.plugins": self._load_order
            })
            span.set_status(Status(StatusCode.OK))
            
            return self._load_order.copy()
    
    def unregister_plugin(self, name: str) -> bool:
        with tracer.start_as_current_span("plugin_unregistration") as span:
            span.set_attribute("plugin.name", name)
            
            if name not in self._plugins:
                span.set_status(Status(StatusCode.ERROR, f"Plugin {name} not found"))
                return False
            
            try:
                plugin = self._plugins[name]
                plugin_type = plugin.metadata.plugin_type
                
                dependents = self._get_dependent_plugins(name)
                if dependents:
                    error_msg = f"Cannot unregister plugin {name}: still has dependents {dependents}"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return False
                
                del self._plugins[name]
                
                if name in self._plugin_types[plugin_type]:
                    self._plugin_types[plugin_type].remove(name)
                
                self._plugin_dependencies.pop(name, None)
                
                self._update_load_order()
                
                span.set_attributes({
                    "unregistration.success": True,
                    "plugin.type": plugin_type.value,
                    "remaining_plugins": len(self._plugins)
                })
                span.set_status(Status(StatusCode.OK))
                
                return True
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False
    
    def _validate_dependencies(self, dependencies: List[str]) -> List[str]:
        errors = []
        
        for dep in dependencies:
            if dep not in self._plugins:
                errors.append(f"Dependency '{dep}' not found")
        
        return errors
    
    def _get_dependent_plugins(self, plugin_name: str) -> List[str]:
        dependents = []
        
        for name, deps in self._plugin_dependencies.items():
            if plugin_name in deps and name in self._plugins:
                dependents.append(name)
        
        return dependents
    
    def _update_load_order(self) -> None:
        with tracer.start_as_current_span("update_load_order") as span:
            visited = set()
            temp_visited = set()
            load_order = []
            
            def visit_plugin(name: str) -> None:
                if name in temp_visited:
                    raise ValueError(f"Circular dependency detected involving plugin: {name}")
                if name in visited:
                    return
                
                temp_visited.add(name)
                
                for dep in self._plugin_dependencies.get(name, []):
                    if dep in self._plugins:
                        visit_plugin(dep)
                
                temp_visited.remove(name)
                visited.add(name)
                load_order.append(name)
            
            try:
                plugin_priority = {
                    name: plugin.config.load_priority 
                    for name, plugin in self._plugins.items()
                }
                
                sorted_plugins = sorted(self._plugins.keys(), key=lambda x: plugin_priority[x])
                
                for plugin_name in sorted_plugins:
                    if plugin_name not in visited:
                        visit_plugin(plugin_name)
                
                self._load_order = load_order
                
                span.set_attributes({
                    "load_order.success": True,
                    "load_order.count": len(load_order)
                })
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self._load_order = list(self._plugins.keys())
    
    def get_registry_stats(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("plugin_registry_stats") as span:
            stats = {
                "total_plugins": len(self._plugins),
                "plugins_by_type": {
                    plugin_type.value: len(plugin_list) 
                    for plugin_type, plugin_list in self._plugin_types.items()
                },
                "plugins_by_status": {
                    status.value: len([
                        p for p in self._plugins.values() if p.status == status
                    ]) for status in PluginStatus
                },
                "load_order_length": len(self._load_order),
                "has_circular_dependencies": len(self._load_order) != len(self._plugins)
            }
            
            span.set_attributes({
                "stats.total_plugins": stats["total_plugins"],
                "stats.active_plugins": stats["plugins_by_status"].get(PluginStatus.ACTIVE.value, 0),
                "stats.has_circular_deps": stats["has_circular_dependencies"]
            })
            span.set_status(Status(StatusCode.OK))
            
            return stats
    
    async def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        with tracer.start_as_current_span("plugin_registry_health_check") as span:
            span.set_attribute("plugins.count", len(self._plugins))
            
            health_results = {}
            healthy_count = 0
            
            for name, plugin in self._plugins.items():
                try:
                    health_status = await plugin.health_check()
                    health_results[name] = health_status
                    
                    if health_status.get("status") == PluginStatus.ACTIVE.value:
                        healthy_count += 1
                        
                except Exception as e:
                    health_results[name] = {
                        "name": name,
                        "status": PluginStatus.ERROR.value,
                        "error": str(e)
                    }
            
            span.set_attributes({
                "health.total_plugins": len(self._plugins),
                "health.healthy_plugins": healthy_count,
                "health.overall_healthy": healthy_count == len(self._plugins)
            })
            
            if healthy_count == len(self._plugins):
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(Status(StatusCode.ERROR, f"Only {healthy_count}/{len(self._plugins)} plugins healthy"))
            
            return health_results


_registry = PluginRegistry()


def register_plugin(metadata: PluginMetadata, config: PluginConfig | None = None):
    def decorator(plugin_class: Type[Plugin]) -> Type[Plugin]:
        plugin_config = config or PluginConfig()
        plugin_instance = plugin_class(metadata, plugin_config)
        _registry.register_plugin(plugin_instance)
        return plugin_class
    return decorator


def get_plugin_registry() -> PluginRegistry:
    return _registry